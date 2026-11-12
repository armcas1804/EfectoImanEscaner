"""NYSE session times with holidays, DST and early closes from exchange_calendars."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
HERMOSILLO = ZoneInfo("America/Hermosillo")
CUTS = (10, 30, 60, 90)


@dataclass(frozen=True)
class MarketSession:
    day: date
    opens: datetime
    closes: datetime

    @property
    def prepare_at(self):
        return self.opens - timedelta(minutes=5)

    def deadline(self, seconds):
        return self.opens + timedelta(seconds=seconds)


@lru_cache(maxsize=5)
def _calendar(year):
    import exchange_calendars as xcals
    return xcals.get_calendar("XNYS", start=f"{year - 1}-01-01", end=f"{year + 1}-12-31")


def session_for_day(day: date | str) -> MarketSession | None:
    day = date.fromisoformat(day) if isinstance(day, str) else day
    calendar = _calendar(day.year)
    label = pd.Timestamp(day)
    if not calendar.is_session(label):
        return None
    return MarketSession(day, calendar.session_open(label).to_pydatetime().astimezone(NY),
                         calendar.session_close(label).to_pydatetime().astimezone(NY))


def next_opening(now: datetime) -> MarketSession:
    """Next opening not in the past, expressed in the market's time zone."""
    local = now.astimezone(NY)
    day = local.date()
    for _ in range(370):
        session = session_for_day(day)
        if session and session.opens > local:
            return session
        day += timedelta(days=1)
    raise RuntimeError("El calendario no contiene una próxima sesión")


def calendar_status(now: datetime) -> dict:
    local = now.astimezone(NY)
    today = session_for_day(local.date())
    following = next_opening(now)
    return {"calendar": "XNYS", "date": local.date().isoformat(),
            "now_ny": local.isoformat(), "now_hermosillo": now.astimezone(HERMOSILLO).isoformat(),
            "is_trading_day": today is not None,
            "is_open": bool(today and today.opens <= local < today.closes),
            "open": today.opens.isoformat() if today else None,
            "close": today.closes.isoformat() if today else None,
            "next_open": following.opens.isoformat(),
            "prepare_at": following.prepare_at.isoformat()}
