"""Experimental pattern quality calculated from information available at the cutoff."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
import math

from .legacy.indicators import BOLLINGER_DEVIATIONS, BOLLINGER_WINDOW


VERSION = "pattern-b-v1"
WEIGHTS = {"lateral": 0.30, "narrow": 0.30, "stable": 0.20, "distance": 0.20}
# The scales below are experimental; at the scale, the corresponding quality is 50%.
PRIOR_SLOPE_SCALE = 0.15  # % per 15 min candle
LIVE_MOVE_SCALE = 0.15  # % from the first provisional band
PRIOR_WIDTH_SCALE = 1.25  # % of the middle band
CUT_WIDTH_SCALE = 2.0  # allow some immediate reaction to the gap
DISTANCE_TARGET = 0.75  # fractions of the previous band's full width


def _quality(value, scale):
    return 1 / (1 + (value / scale) ** 2)


def _bands_at(price, cut_price, cut_upper, cut_lower):
    """Recover BB(20,2) at an observed price by replacing only the provisional close.

    The other 19 closes are unchanged. Express both moments around the cutoff
    mean to avoid subtracting large, nearly equal raw second moments.
    """
    middle = (cut_upper + cut_lower) / 2
    std = (cut_upper - cut_lower) / (2 * BOLLINGER_DEVIATIONS)
    shift = (price - cut_price) / BOLLINGER_WINDOW
    variance = (std ** 2 + ((price - middle) ** 2 - (cut_price - middle) ** 2)
                / BOLLINGER_WINDOW - shift ** 2)
    if variance < -1e-8 or middle + shift <= 0:
        return None
    spread = BOLLINGER_DEVIATIONS * math.sqrt(max(0, variance))
    return middle + shift + spread, middle + shift - spread


def _events_by_ticker(snapshot, quotes):
    end = datetime.fromisoformat(snapshot["cutoff_at"])
    start = end - timedelta(seconds=snapshot["seconds"])
    groups = defaultdict(list)
    for quote in quotes:
        event = datetime.fromisoformat(quote["event_time"])
        received = datetime.fromisoformat(quote["received_at"])
        if start <= event <= end and start <= received <= end:
            groups[quote["ticker"]].append((event, received, quote["price"]))
    return groups


def _observed_prices(row, events):
    first_price, cut_price = row["first_price"], row["price_at_cutoff"]
    endpoints = [first_price, cut_price]
    # A different feed, or an incomplete/mismatched local stream, cannot fill gaps
    # in the frozen record. Fall back to the two actual prices in the snapshot.
    if (row.get("source") != "yahoo_websocket_local" or len(events) < 2 or
            len(events) != row.get("event_count") or not row.get("first_time") or not row.get("last_time")):
        return endpoints, "endpoints"
    first = min(events, key=lambda x: (x[1], x[0]))
    last = max(events, key=lambda x: (x[0], x[1]))
    if (first[0] != datetime.fromisoformat(row["first_time"]) or
            last[0] != datetime.fromisoformat(row["last_time"]) or
            not math.isclose(first[2], first_price) or not math.isclose(last[2], cut_price)):
        return endpoints, "endpoints"
    return [first_price, *(e[2] for e in sorted(events)), cut_price], "observations"


def _components(row, events, prior_widths):
    required = ("first_price", "price_at_cutoff", "prior_bb_upper", "prior_bb_lower",
                "cutoff_bb_upper", "cutoff_bb_lower", "prior_target_band_slope_pct",
                "angle_cutoff_event_span_seconds")
    if not all(isinstance(row.get(k), (int, float)) and math.isfinite(row[k]) for k in required):
        return {}
    first, price, pu, pl, upper, lower, slope, span = (row[k] for k in required)
    if not (pu > pl > 0 and upper > lower > 0 and first > 0 and price > 0 and span > 0):
        return {}

    prices, coverage = _observed_prices(row, events)
    path = [_bands_at(p, price, upper, lower) for p in prices]
    if any(point is None for point in path):
        return {}
    widths = [200 * (u - l) / (u + l) for u, l in path]
    upward = row.get("gap_direction") == "UP"
    target = [point[0 if upward else 1] for point in path]
    if target[0] <= 0:
        return {}
    excursion = max(abs(b - target[0]) for b in target) / target[0] * 100
    prior_width = 200 * (pu - pl) / (pu + pl)
    percentile = None
    if len(prior_widths) >= 10:
        i = bisect_left(prior_widths, prior_width)
        j = bisect_right(prior_widths, prior_width)
        percentile = (i + j) / (2 * len(prior_widths))
    expansion = max(widths) - widths[0]
    distance = ((price - upper) if upward else (lower - price)) / (pu - pl)
    if distance <= 0:
        return {}

    qualities = {
        "lateral": min(_quality(abs(slope), PRIOR_SLOPE_SCALE),
                       _quality(excursion, LIVE_MOVE_SCALE)),
        "narrow": min(_quality(prior_width, PRIOR_WIDTH_SCALE),
                      _quality(widths[-1], CUT_WIDTH_SCALE)),
        "stable": _quality(expansion, max(0.15, 0.25 * prior_width)),
        "distance": min(1, distance / DISTANCE_TARGET),
    }
    if percentile is not None:
        # Relative compression can refine the absolute test, never rescue a wide band.
        qualities["narrow"] *= 1 - 0.15 * percentile
    weighted = 100 * math.prod(value ** WEIGHTS[key] for key, value in qualities.items())
    ceiling = 50 + 50 * min(qualities[key] for key in ("lateral", "narrow", "stable"))
    return {"score_home_b": round(min(weighted, ceiling), 1),
            "pattern_score_ceiling": round(ceiling, 1), "pattern_coverage": coverage,
            "pattern_prior_width_percentile": percentile,
            "pattern_first_width_pct": widths[0], "pattern_expansion_pp": expansion,
            "pattern_band_excursion_pct": excursion, "pattern_distance_relative": distance,
            **{f"pattern_quality_{key}": round(value * 100, 1)
               for key, value in qualities.items()}}


def apply_pattern_score(snapshot, quotes=(), prior_widths=None):
    """Return a scored view without changing the stored cutoff or original score."""
    groups = _events_by_ticker(snapshot, quotes)
    prior_widths = prior_widths or {}
    rows = []
    for old in snapshot["rows"]:
        ticker = old["ticker"]
        row = {**old, "score_home_b_previous": old.get("score_home_b"),
               "score_home_b": None, "score_version": VERSION}
        if old.get("home_b_candidate") is True:
            row.update(_components(row, groups.get(ticker, ()), prior_widths.get(ticker, ())))
        rows.append(row)
    rows.sort(key=lambda row: (not row.get("home_b_candidate"),
                               -(row["score_home_b"] or 0), row["ticker"]))
    return {**snapshot, "rows": rows, "stored_score_version": snapshot["score_version"],
            "score_version": VERSION, "scored": sum(r["score_home_b"] is not None for r in rows)}
