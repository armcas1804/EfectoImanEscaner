"""Approved B scoring adapter; the snapshot never reads later prices."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .config import SCORE_VERSION, TICKERS
from .legacy.opening_scan import opening_setups
from .legacy.trial_variants import (live_quote_observations, opening_reversal_table,
                                    score_home_trial_b)


def _universe(setups):
    return setups.set_index("ticker").reindex(TICKERS).rename_axis("ticker").reset_index()


def _decorate(result, day, seconds):
    result = result.copy()
    result["date"] = day
    result["window_seconds"] = seconds
    result["score_version"] = SCORE_VERSION
    cutoff = pd.Timestamp(day + " 09:30:00", tz="America/New_York") + pd.Timedelta(seconds=seconds)
    events = pd.to_datetime(result.last_time, utc=True, errors="coerce")
    result["quote_age_seconds"] = (cutoff.tz_convert("UTC") - events).dt.total_seconds()
    result["quote_status"] = "Sin cotización"
    result.loc[events.notna(), "quote_status"] = "Cotización disponible"
    result.loc[result.quote_age_seconds.gt(15), "quote_status"] = "Cotización antigua al corte"
    result["data_status"] = "Datos disponibles"
    missing_bands = result.prior_bb_upper.isna() | result.prior_bb_lower.isna()
    missing_price = result.price_at_cutoff.isna()
    missing_interval = result.angle_cutoff_event_span_seconds.isna() | result.angle_cutoff_event_span_seconds.le(0)
    result.loc[missing_interval, "data_status"] = "Intervalo de banda no medible"
    result.loc[missing_bands, "data_status"] = "Sin bandas previas suficientes"
    result.loc[missing_bands, "home_b_status"] = "Sin bandas previas suficientes"
    result.loc[missing_price, "data_status"] = "Sin cotización en este corte"
    result.loc[missing_price, "home_b_status"] = "Sin cotización en este corte"
    return result.sort_values(["home_b_candidate", "score_home_b", "ticker"],
        ascending=[False, False, True], na_position="last").reset_index(drop=True)


def score_cut(prior_bars, quotes, day, seconds):
    opened = datetime.combine(datetime.fromisoformat(day).date(), time(9, 30),
                               ZoneInfo("America/New_York"))
    deadline = opened + timedelta(seconds=int(seconds))
    frame = pd.DataFrame.from_records(quotes)
    needed = ["ticker", "price", "quote_event_time", "quote_received_at"]
    for original, standard in (("event_time", "quote_event_time"), ("received_at", "quote_received_at")):
        if standard not in frame.columns and original in frame.columns:
            frame[standard] = frame[original]
    frame = frame.reindex(columns=needed)
    received = pd.to_datetime(frame.quote_received_at, utc=True, errors="coerce")
    events_at = pd.to_datetime(frame.quote_event_time, utc=True, errors="coerce")
    frame = frame.loc[received.between(opened, deadline) & events_at.between(opened, deadline)]
    observations = live_quote_observations(frame, opened, int(seconds))
    events = {}
    for ticker, group in frame.groupby("ticker"):
        events[ticker] = [(pd.Timestamp(r.quote_event_time).to_pydatetime(), float(r.price))
                          for r in group.itertuples()]
    prior = prior_bars.copy()
    if prior.empty:
        prior = pd.DataFrame(columns=["ticker", "bar_index", "session", "time", "open", "high", "low", "close"])
    else:
        prior = prior.loc[prior.session.eq("PREVIA")].copy()
    setups = opening_setups(prior, opening_prices=dict(zip(observations.ticker, observations.price)),
                            cutoff_seconds=int(seconds), opening_events=events)
    setups = _universe(setups)
    result = score_home_trial_b(setups, opening_reversal_table(setups, observations, int(seconds), 1.0))
    return _decorate(result, day, int(seconds))


def rescore_export(frame):
    required = {"date", "ticker", "window_seconds", "previous_close", "source",
        "first_price", "price_at_cutoff", "first_time", "last_time", "event_count",
        "prior_bb_width_pct", "prior_bb_width_change", "prior_bb_upper", "prior_bb_lower",
        "prior_target_band_slope_pct", "cutoff_bb_upper", "cutoff_bb_lower",
        "target_angle_cutoff_deg", "angle_cutoff_event_span_seconds"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError("Se necesita un CSV de diagnóstico completo con fecha, corte y bandas")
    days = frame.date.dropna().astype(str).unique()
    seconds = pd.to_numeric(frame.window_seconds, errors="coerce").unique()
    if len(days) != 1 or len(seconds) != 1 or seconds[0] not in (10, 30, 60, 90):
        raise ValueError("El archivo debe contener una fecha y un corte de 10, 30, 60 o 90 segundos")
    datetime.fromisoformat(days[0])
    if frame.ticker.duplicated().any() or not set(frame.ticker).issubset(TICKERS):
        raise ValueError("Símbolos duplicados o ajenos al universo configurado")
    setups = _universe(frame.rename(columns={"previous_close": "prior_close"}))
    obs = frame[["ticker", "source", "first_price", "price_at_cutoff", "first_time", "last_time", "event_count"]].rename(columns={"price_at_cutoff": "price"})
    obs["window_seconds"] = int(seconds[0])
    result = score_home_trial_b(setups, opening_reversal_table(setups, obs, int(seconds[0]), 1.0))
    return _decorate(result, days[0], int(seconds[0]))
