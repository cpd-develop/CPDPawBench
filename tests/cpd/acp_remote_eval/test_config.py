# -*- coding: utf-8 -*-
"""Config validation for the ACP remote-eval service."""

from __future__ import annotations

from pathlib import Path

import pytest

from pawbench.cpd.acp_remote_eval.service.config import (
    ConfigError,
    load_config,
    parse_config,
)

#: The example the repo ships as the starting point for a local service.  It is
#: read here rather than only documented, because a key that drifted out of it
#: would be copied into every deployment and then silently fall back.
EXAMPLE_CONFIG = (
    Path(__file__).parents[3] / "pawbench/cpd/acp_remote_eval/service/config.example.yaml"
)


def _raw(**overrides) -> dict:
    raw = {
        "service": {"public_base_url": "http://localhost:8471"},
        "schedule": {"timezone": "Asia/Shanghai"},
        "datasets": {"builtin_dir": "data/pawbench-v1.0"},
    }
    for key, value in overrides.items():
        raw.setdefault(key, {}).update(value)
    return raw


def test_public_base_url_is_required() -> None:
    with pytest.raises(ConfigError, match="public_base_url is required"):
        parse_config({"service": {"bind": "127.0.0.1:8471"}}, Path("."))


def test_public_base_url_scheme_and_trailing_slash() -> None:
    cfg = parse_config(_raw(service={"public_base_url": "https://eval.example.com/"}), Path("."))
    assert cfg.service.public_base_url == "https://eval.example.com"

    with pytest.raises(ConfigError, match="must start with"):
        parse_config(_raw(service={"public_base_url": "eval.example.com"}), Path("."))


def test_defaults_match_the_design() -> None:
    cfg = parse_config(_raw(), Path("."))
    assert cfg.service.max_concurrent_jobs == 4
    assert cfg.service.max_running_per_user == 1
    assert cfg.service.max_job_seconds == 7200
    assert cfg.service.lease_ttl_seconds == 90.0
    assert cfg.schedule.tick_seconds == 5
    assert cfg.schedule.night_open == "00:00"
    assert cfg.schedule.night_close == "07:00"
    assert cfg.schedule.night_min_lead_seconds == 1800
    assert cfg.schedule.hard_stop is False
    assert cfg.datasets.category_create_scope == "any"
    assert "environment" in cfg.datasets.builtin_view_filter_keys


def test_relative_paths_anchor_to_the_config_directory(tmp_path: Path) -> None:
    cfg = parse_config(_raw(), tmp_path)
    assert cfg.service.state_db == (tmp_path / "runtime" / "state.db").resolve()
    assert cfg.datasets.builtin_dir == (tmp_path / "data/pawbench-v1.0").resolve()

    absolute = _raw(service={"state_db": str(tmp_path / "elsewhere.db")})
    assert parse_config(absolute, tmp_path).service.state_db == tmp_path / "elsewhere.db"


def test_omitting_the_paths_lands_where_the_example_says(tmp_path: Path) -> None:
    """The fallbacks are anchored to the config file, not to the repo root.

    A config that only sets ``public_base_url`` is the one somebody writes
    first, and the defaults it gets must be the ones the example documents:
    runtime state under ``runtime/`` beside the config, and the corpus reached
    by climbing out of the package.  Repo-root-shaped defaults would put the
    state database -- which holds run tokens and subject endpoint URLs --
    inside ``pawbench/cpd/**``, where ``git add`` of this feature picks it up.
    """
    cfg = parse_config({"service": {"public_base_url": "http://localhost:8471"}}, tmp_path)

    assert cfg.service.state_db == (tmp_path / "runtime" / "state.db").resolve()
    assert cfg.datasets.custom_dir == (tmp_path / "runtime" / "datasets").resolve()
    assert cfg.exchange.exchange_dir == (tmp_path / "runtime" / "exchange").resolve()
    for path in (cfg.service.state_db, cfg.datasets.custom_dir, cfg.exchange.exchange_dir):
        assert not path.is_relative_to(Path(__file__).parents[3] / "pawbench"), path


def test_the_omitted_corpus_default_is_the_shipped_one() -> None:
    """Anchored at the real config directory, the fallback finds the corpus."""
    cfg = parse_config(
        {"service": {"public_base_url": "http://localhost:8471"}},
        EXAMPLE_CONFIG.parent,
    )
    example = load_config(EXAMPLE_CONFIG)

    assert cfg.datasets.builtin_dir == example.datasets.builtin_dir
    assert cfg.datasets.builtin_dir.is_dir(), f"no corpus at {cfg.datasets.builtin_dir}"


@pytest.mark.parametrize(
    "window,expected",
    [
        (["00:00", "07:00"], ("00:00", "07:00")),
        (["0:0", "7:00"], ("00:00", "07:00")),
        (["22:30", "06:00"], ("22:30", "06:00")),
    ],
)
def test_night_window_is_normalised_to_hh_mm(window, expected) -> None:
    cfg = parse_config(_raw(schedule={"night_window": window}), Path("."))
    assert (cfg.schedule.night_open, cfg.schedule.night_close) == expected


@pytest.mark.parametrize("window", [["07:00"], ["07", "09"], ["25:00", "07:00"], ["07:00", "7:61"]])
def test_bad_night_window_fails_at_startup(window) -> None:
    with pytest.raises(ConfigError):
        parse_config(_raw(schedule={"night_window": window}), Path("."))


# ── the numbers the always-on service is driven by ────────────────────────────


@pytest.mark.parametrize("ttl,tick", [(9.9, 5), (4, 5), (0.9, 0.5), (0, 5)])
def test_a_lease_shorter_than_two_ticks_is_refused(ttl: float, tick: float) -> None:
    """A lease that expires inside one tick would settle live jobs.

    The settle writes terminal rows, so the mistake cannot be taken back once
    the next tick has run: catching it at startup is the only cheap version.
    """
    with pytest.raises(ConfigError, match="lease_ttl_seconds"):
        parse_config(
            _raw(service={"lease_ttl_seconds": ttl}, schedule={"tick_seconds": tick}), Path(".")
        )


@pytest.mark.parametrize("ttl,tick", [(10, 5), (90, 5), (30, 15), (1, 0.5)])
def test_the_two_tick_boundary_is_accepted(ttl: float, tick: float) -> None:
    cfg = parse_config(
        _raw(service={"lease_ttl_seconds": ttl}, schedule={"tick_seconds": tick}), Path(".")
    )
    assert (cfg.service.lease_ttl_seconds, cfg.schedule.tick_seconds) == (float(ttl), float(tick))


@pytest.mark.parametrize("seconds", [0, -1])
def test_a_job_with_no_wall_clock_is_refused(seconds: int) -> None:
    """``0`` reads as "unbounded" to a runner and as "stop immediately" to a queue."""
    with pytest.raises(ConfigError, match="max_job_seconds"):
        parse_config(_raw(service={"max_job_seconds": seconds}), Path("."))


@pytest.mark.parametrize("tick", [0, -0.5])
def test_a_scheduler_that_never_sleeps_is_refused(tick: float) -> None:
    """A tick of zero is not "constantly": it is a loop that never yields.

    The scheduler shares this process's one event loop with the data plane the
    remote agent uploads to, so a busy tick would starve the half of the service
    the submitter is waiting on -- and the lease-to-tick rule below cannot say
    which of the two numbers the operator mistyped.
    """
    with pytest.raises(ConfigError, match="tick_seconds"):
        parse_config(_raw(schedule={"tick_seconds": tick}), Path("."))


def test_the_shipped_example_config_parses() -> None:
    cfg = load_config(EXAMPLE_CONFIG)

    assert cfg.service.public_base_url.startswith(("http://", "https://"))
    assert (cfg.service.max_concurrent_jobs, cfg.service.max_running_per_user) == (4, 1)
    assert cfg.service.lease_ttl_seconds >= 2 * cfg.schedule.tick_seconds
    assert cfg.schedule.timezone == "Asia/Shanghai"
    # An example that left auth out would teach the one default nobody wants.
    assert cfg.allowlist_path is not None


def test_the_example_paths_reach_the_real_corpus() -> None:
    """Relative paths anchor to the file, so this checks the level count too."""
    cfg = load_config(EXAMPLE_CONFIG)

    assert cfg.datasets.builtin_dir.is_dir(), f"no corpus at {cfg.datasets.builtin_dir}"
    assert cfg.service.state_db.parent.name == "runtime"
    assert cfg.exchange.exchange_dir.parent.name == "runtime"
