# -*- coding: utf-8 -*-
"""Run-time windows and the clock the service reasons with (design section 5.1).

Three rules hold everything together:

* ``not_before`` / ``not_after`` are the only window fields stored, and they are
  always UTC.  The service timezone is applied when a window is *written* (a
  user says "tonight"), never when it is compared.
* A window gates *starts*.  Crossing ``not_after`` does not kill a task that is
  already running, because a killed task reads as "the agent failed" instead of
  "we ran out of time".
* Everything here takes a clock.  The nightly window cannot be tested any other
  way, and a test that waits for midnight is not a test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo, timezone
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo

from .config import ScheduleConfig

logger = logging.getLogger(__name__)

WINDOW_IMMEDIATE = "immediate"
WINDOW_NIGHT = "night"
WINDOW_CUSTOM = "custom"
WINDOW_KINDS = (WINDOW_IMMEDIATE, WINDOW_NIGHT, WINDOW_CUSTOM)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Wall clock; always returns an aware UTC datetime."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    """Settable clock for window and queue tests."""

    def __init__(self, instant: datetime) -> None:
        self._instant = _as_utc(instant)

    def now(self) -> datetime:
        return self._instant

    def set(self, instant: datetime) -> None:
        self._instant = _as_utc(instant)

    def advance(self, **kwargs: int) -> datetime:
        self._instant += timedelta(**kwargs)
        return self._instant


class WindowError(ValueError):
    """A window the service will not accept, with the code the dashboard shows."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Window:
    kind: str
    not_before: datetime
    not_after: datetime | None = None
    timezone: str = "UTC"

    @property
    def is_open(self) -> bool:
        return self.not_after is None

    def seconds_until_open(self, now: datetime) -> float:
        return max(0.0, (self.not_before - _as_utc(now)).total_seconds())

    def blocks_starts_at(self, now: datetime) -> bool:
        """True once the window has closed: no new task may start."""
        return self.not_after is not None and _as_utc(now) >= self.not_after

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "not_before": _iso(self.not_before),
            "not_after": _iso(self.not_after) if self.not_after else None,
            "tz": self.timezone,
            "not_before_local": _local_text(self.not_before, self.timezone),
            "not_after_local": _local_text(self.not_after, self.timezone) if self.not_after else "",
        }


def service_zone(config: ScheduleConfig) -> tzinfo:
    return ZoneInfo(config.timezone)


def resolve_window(
    kind: str,
    now: datetime,
    config: ScheduleConfig,
    *,
    not_before: str | datetime | None = None,
    not_after: str | datetime | None = None,
    required_seconds: int = 0,
) -> Window:
    """Normalise a submitted window into absolute UTC bounds."""
    if kind not in WINDOW_KINDS:
        raise WindowError(
            "unknown_window_kind", f"window kind must be one of {list(WINDOW_KINDS)}"
        )
    zone = service_zone(config)
    current = _as_utc(now)

    if kind == WINDOW_IMMEDIATE:
        return Window(WINDOW_IMMEDIATE, current, None, config.timezone)

    if kind == WINDOW_NIGHT:
        if not_before or not_after:
            raise WindowError(
                "night_window_is_fixed",
                "the night window comes from schedule.night_window; drop not_before/not_after",
            )
        start, end = next_night_window(current, config, zone)
        return Window(WINDOW_NIGHT, start, end, config.timezone)

    if not_before is None or not_after is None:
        raise WindowError("custom_window_needs_bounds", "custom windows require not_before and not_after")

    start = _parse_instant(not_before, zone, "not_before")
    end = _parse_instant(not_after, zone, "not_after")
    if end <= start:
        raise WindowError("window_inverted", "not_after must be later than not_before")

    max_span = timedelta(days=config.custom_window_max_days)
    if end - start > max_span:
        raise WindowError(
            "window_too_long",
            f"a custom window may span at most {config.custom_window_max_days} days",
        )
    if start < current:
        raise WindowError("window_in_the_past", "not_before is already in the past")
    if required_seconds and (end - start) < timedelta(seconds=required_seconds):
        raise WindowError(
            "window_too_short",
            f"the window is shorter than one task timeout ({required_seconds}s)",
        )
    return Window(WINDOW_CUSTOM, start, end, config.timezone)


def next_night_window(
    now: datetime, config: ScheduleConfig, zone: tzinfo | None = None
) -> tuple[datetime, datetime]:
    """The next night whose remaining length is at least ``night_min_lead_seconds``.

    Submitting at 23:30 gets tonight 00:00-07:00; submitting at 06:45 (15 minutes
    left) waits for tomorrow rather than starting a run that will be cut off.
    """
    zone = zone or service_zone(config)
    current = _as_utc(now).astimezone(zone)
    open_at = _time_from(config.night_open)
    close_at = _time_from(config.night_close)

    candidate_open = datetime.combine(current.date(), open_at, tzinfo=zone)
    span = datetime.combine(date.min, close_at) - datetime.combine(date.min, open_at)
    if span <= timedelta(0):
        span += timedelta(days=1)  # a window that runs past midnight, e.g. 22:00-06:00
    for _ in range(3):
        candidate_close = candidate_open + span
        remaining = (candidate_close - current).total_seconds()
        if current < candidate_open or remaining >= config.night_min_lead_seconds:
            return _as_utc(candidate_open), _as_utc(candidate_close)
        candidate_open = candidate_open + timedelta(days=1)

    # Unreachable for sane config: three consecutive windows cannot all be short
    # of a lead time measured in minutes while the window itself is hours long.
    raise WindowError("night_window_unusable", "no upcoming night window is long enough")


def window_from_row(row: Mapping[str, Any], config: ScheduleConfig) -> Window:
    """Rebuild a :class:`Window` from a ``jobs`` row for scheduling decisions."""
    not_before = row.get("not_before")
    not_after = row.get("not_after")
    zone = service_zone(config)
    return Window(
        kind=str(row.get("window_kind") or WINDOW_IMMEDIATE),
        not_before=_parse_instant(not_before, zone, "not_before") if not_before else _EPOCH,
        not_after=_parse_instant(not_after, zone, "not_after") if not_after else None,
        timezone=config.timezone,
    )


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _time_from(text: str) -> time:
    hours, minutes = (int(part) for part in text.split(":"))
    return time(hour=hours, minute=minutes)


def _parse_instant(value: str | datetime, zone: tzinfo, label: str) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value, default_zone=zone)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WindowError(
            "bad_window_time", f"{label} must be an ISO-8601 timestamp, got {text!r}"
        ) from exc
    if parsed.tzinfo is None:
        # A timestamp without an offset is wall-clock time in the service zone,
        # which is what the dashboard sends; guessing the browser zone instead
        # would make a submission mean different things to different people.
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime, default_zone: tzinfo = timezone.utc) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_zone)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="seconds")


def _local_text(value: datetime | None, zone_name: str) -> str:
    if value is None:
        return ""
    return _as_utc(value).astimezone(ZoneInfo(zone_name)).isoformat(timespec="seconds")
