# -*- coding: utf-8 -*-
"""Window resolution against a settable clock (design section 5.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from pawbench.cpd.acp_remote_eval.service.config import ScheduleConfig
from pawbench.cpd.acp_remote_eval.service.schedule import (
    FrozenClock,
    Window,
    WindowError,
    next_night_window,
    resolve_window,
    window_from_row,
)

TZ = "Asia/Shanghai"


def schedule_config(**overrides) -> ScheduleConfig:
    values = {
        "timezone": TZ,
        "tick_seconds": 5,
        "night_open": "00:00",
        "night_close": "07:00",
        "night_min_lead_seconds": 1800,
        "hard_stop": False,
        "custom_window_max_days": 7,
    }
    values.update(overrides)
    return ScheduleConfig(**values)


def shanghai(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))


def test_immediate_window_opens_now_and_never_closes() -> None:
    now = shanghai(2026, 11, 10, 14, 30)
    window = resolve_window("immediate", now, schedule_config())
    assert window.not_before == now.astimezone(timezone.utc)
    assert window.not_after is None
    assert window.blocks_starts_at(now) is False


@pytest.mark.parametrize(
    "submitted_at,expected_local_day",
    [
        (shanghai(2026, 11, 10, 9, 0), 11),
        (shanghai(2026, 11, 10, 23, 30), 11),
        (shanghai(2026, 11, 10, 1, 0), 10),
    ],
)
def test_night_window_lands_on_the_next_night(
    submitted_at: datetime, expected_local_day: int
) -> None:
    """Days are read in the service zone: 00:00 Shanghai is 16:00 UTC."""
    window = resolve_window("night", submitted_at, schedule_config())
    local_open = window.not_before.astimezone(ZoneInfo(TZ))
    assert local_open.day == expected_local_day
    assert local_open.strftime("%H:%M") == "00:00"
    assert window.not_after.astimezone(ZoneInfo(TZ)).strftime("%H:%M") == "07:00"
    # The window has not closed yet, whichever night it landed on.
    assert window.not_after > submitted_at.astimezone(timezone.utc)


def test_a_night_window_about_to_close_is_not_split_in_half() -> None:
    """Submitting at 06:45 waits for tomorrow instead of starting a 15-minute run."""
    window = resolve_window("night", shanghai(2026, 11, 10, 6, 45), schedule_config())
    local = window.not_before.astimezone(ZoneInfo(TZ))
    assert (local.day, local.hour, local.minute) == (11, 0, 0)


def test_a_night_window_with_lead_left_starts_immediately() -> None:
    window = resolve_window("night", shanghai(2026, 11, 10, 1, 0), schedule_config())
    assert window.not_before.astimezone(ZoneInfo(TZ)).day == 10
    assert window.seconds_until_open(shanghai(2026, 11, 10, 1, 30)) == 0.0


def test_night_window_that_crosses_midnight() -> None:
    cfg = schedule_config(night_open="22:00", night_close="06:00")
    window = resolve_window("night", shanghai(2026, 11, 10, 20, 0), cfg)
    local_open = window.not_before.astimezone(ZoneInfo(TZ))
    local_close = window.not_after.astimezone(ZoneInfo(TZ))
    assert (local_open.day, local_open.hour) == (10, 22)
    assert (local_close.day, local_close.hour) == (11, 6)
    assert (window.not_after - window.not_before).total_seconds() == 8 * 3600


def test_night_window_rejects_explicit_bounds() -> None:
    with pytest.raises(WindowError) as caught:
        resolve_window(
            "night", shanghai(2026, 11, 10, 9, 0), schedule_config(), not_before="2026-11-11T00:00:00"
        )
    assert caught.value.code == "night_window_is_fixed"


def test_custom_window_naive_time_is_service_wall_clock() -> None:
    window = resolve_window(
        "custom",
        shanghai(2026, 11, 10, 9, 0),
        schedule_config(),
        not_before="2026-11-10T22:00:00",
        not_after="2026-11-11T06:00:00",
    )
    assert window.not_before == shanghai(2026, 11, 10, 22, 0).astimezone(timezone.utc)
    assert window.not_after == shanghai(2026, 11, 11, 6, 0).astimezone(timezone.utc)
    payload = window.to_payload()
    assert payload["not_before"].endswith("+00:00")
    assert payload["not_before_local"].endswith("+08:00")
    assert payload["tz"] == TZ


def test_custom_window_accepts_an_offset_and_stores_utc() -> None:
    window = resolve_window(
        "custom",
        shanghai(2026, 11, 10, 9, 0),
        schedule_config(),
        not_before="2026-11-10T22:00:00+08:00",
        not_after="2026-11-11T04:00:00Z",
    )
    assert window.not_before == datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
    assert window.not_after == datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)
    # Shanghai is +08:00 all year, so an explicit offset and the service's own
    # wall clock must resolve to the same instant.
    naive = resolve_window(
        "custom",
        shanghai(2026, 11, 10, 9, 0),
        schedule_config(),
        not_before="2026-11-10T22:00:00",
        not_after="2026-11-11T04:00:00Z",
    )
    assert naive.not_before == window.not_before


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"not_before": "2026-11-11T06:00:00", "not_after": "2026-11-10T22:00:00"}, "window_inverted"),
        ({"not_before": "2026-11-09T22:00:00", "not_after": "2026-11-10T06:00:00"}, "window_in_the_past"),
        (
            {"not_before": "2026-11-10T22:00:00", "not_after": "2026-12-20T06:00:00"},
            "window_too_long",
        ),
        ({"not_before": "2026-11-10T22:00:00"}, "custom_window_needs_bounds"),
        ({"not_before": "not a time", "not_after": "2026-11-11T06:00:00"}, "bad_window_time"),
    ],
)
def test_custom_window_validation(kwargs: dict, code: str) -> None:
    with pytest.raises(WindowError) as caught:
        resolve_window("custom", shanghai(2026, 11, 10, 9, 0), schedule_config(), **kwargs)
    assert caught.value.code == code


def test_custom_window_must_fit_one_task_timeout() -> None:
    cfg = schedule_config()
    common = {"not_before": "2026-11-10T22:00:00", "not_after": "2026-11-10T22:20:00"}
    resolve_window("custom", shanghai(2026, 11, 10, 9, 0), cfg, **common)
    with pytest.raises(WindowError) as caught:
        resolve_window(
            "custom", shanghai(2026, 11, 10, 9, 0), cfg, required_seconds=1800, **common
        )
    assert caught.value.code == "window_too_short"


def test_unknown_window_kind() -> None:
    with pytest.raises(WindowError) as caught:
        resolve_window("cron", shanghai(2026, 11, 10, 9, 0), schedule_config())
    assert caught.value.code == "unknown_window_kind"


def test_window_from_row_round_trip() -> None:
    cfg = schedule_config()
    window = resolve_window(
        "custom",
        shanghai(2026, 11, 10, 9, 0),
        cfg,
        not_before="2026-11-10T22:00:00",
        not_after="2026-11-11T06:00:00",
    )
    row = {
        "window_kind": window.kind,
        "not_before": window.to_payload()["not_before"],
        "not_after": window.to_payload()["not_after"],
    }
    rebuilt = window_from_row(row, cfg)
    assert rebuilt == window
    assert window_from_row({"window_kind": "immediate"}, cfg).not_before.year == 1970


def test_blocks_starts_at_close_boundary() -> None:
    window = Window("custom", shanghai(2026, 11, 10, 22, 0).astimezone(timezone.utc),
                    shanghai(2026, 11, 11, 6, 0).astimezone(timezone.utc))
    assert window.blocks_starts_at(shanghai(2026, 11, 11, 5, 59)) is False
    assert window.blocks_starts_at(shanghai(2026, 11, 11, 6, 0)) is True
    assert window.is_open is False


def test_frozen_clock_advances() -> None:
    clock = FrozenClock(shanghai(2026, 11, 10, 23, 55))
    assert clock.now().year == 2026
    opened = clock.advance(minutes=6)
    assert opened == shanghai(2026, 11, 11, 0, 1).astimezone(timezone.utc)


def test_next_night_window_is_utc_pair() -> None:
    cfg = schedule_config()
    start, end = next_night_window(shanghai(2026, 11, 10, 12, 0), cfg)
    assert start.tzinfo == timezone.utc and end.tzinfo == timezone.utc
    assert (end - start).total_seconds() == 7 * 3600
