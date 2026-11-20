"""Config loading for the ACP remote-eval service (design section 13)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

CONFIG_FILE_ENV = "PAWBENCH_EVAL_CONFIG"
DEFAULT_CONFIG_PATH = Path("pawbench/cpd/acp_remote_eval/service/config.yaml")

_URL_SCHEMES = ("http://", "https://")

#: Filenames a grading process collects or imports on its own, so accepting
#: them from a submission would let the submitter run code on the scoring
#: machine.  Shared by package validation and artifact ingest: the policy has
#: to be one policy, or a task file passes where an artifact would not.
SCORE_HIJACK_FILENAMES = frozenset(
    {
        "conftest.py",
        "pytest.ini",
        "pytest.py",
        "tox.ini",
        "setup.cfg",
        "sitecustomize.py",
        "usercustomize.py",
    }
)
SCORE_HIJACK_SUFFIXES = frozenset({".pth"})

_ARTIFACT_EXTENSIONS = (
    "xlsx xls csv tsv json jsonl yaml yml md txt html htm xml pdf png jpg jpeg "
    "gif webp bmp svg mp3 wav m4a mp4 docx pptx py sql log"
).split()


class ConfigError(ValueError):
    """Raised when the service config is missing or unusable.

    The service refuses to start on this: every absolute URL handed to a remote
    agent is built from ``service.public_base_url``, so an implicit default
    would either produce unreachable fixture links or, worse, fall back to the
    caller-controlled ``Host`` header.
    """


@dataclass(frozen=True)
class ServiceConfig:
    bind: str
    public_base_url: str
    state_db: Path
    max_concurrent_jobs: int
    max_running_per_user: int
    artifact_max_bytes_per_task: int
    exchange_ttl_multiplier: float
    #: Ceiling on one job's whole run, not on one task.  Without it a 15-task
    #: submission may outlive the night window it was queued into.
    max_job_seconds: int
    #: How long a ``running`` row may be believed without a beat from the process
    #: that owns it.  Shorter than ``max_job_seconds`` by design: this is about
    #: liveness, not about how long work may take.
    lease_ttl_seconds: float


@dataclass(frozen=True)
class ScheduleConfig:
    timezone: str
    tick_seconds: float
    night_open: str
    night_close: str
    night_min_lead_seconds: int
    hard_stop: bool
    custom_window_max_days: int


@dataclass(frozen=True)
class DatasetConfig:
    builtin_dir: Path
    custom_dir: Path
    max_task_ids_per_dataset: int
    builtin_view_filter_keys: frozenset[str]
    category_create_scope: str
    category_delete_scope: str
    pilot_dataset_id: str


@dataclass(frozen=True)
class ExchangeConfig:
    """The data plane: fixture links, upload budgets and the write defenses."""

    exchange_dir: Path
    asset_url_ttl_seconds: int
    max_uploads_per_run: int
    max_bytes_per_artifact: int
    allowed_extensions: frozenset[str]
    allowed_output_prefixes: tuple[str, ...]
    forbidden_names: frozenset[str]
    forbidden_suffixes: frozenset[str]


@dataclass(frozen=True)
class JudgeConfig:
    """How the scoring side reaches the LLM judge (design section 13).

    The API key is deliberately *not* a field: it is read from ``api_key_env``
    when a request is made, so no config object -- which is echoed into job
    snapshots, reports and the startup log -- can ever carry one.
    """

    base_url: str
    model: str
    #: Set to ask one fixed backend instead of the free routing.  Comparing two
    #: rounds then means comparing the same judge, which is the only way a
    #: number can be quoted outside the team (design section 13.1).
    pinned_model: str
    api_key_env: str
    timeout_seconds: float
    #: Rate-limit backoff: attempts in total, and the first wait.
    max_attempts: int
    base_delay_seconds: float


@dataclass(frozen=True)
class EvalConfig:
    service: ServiceConfig
    schedule: ScheduleConfig
    datasets: DatasetConfig
    exchange: ExchangeConfig
    judge: JudgeConfig
    allowlist_path: Path | None
    source: Mapping[str, Any]


_SCHEDULE_DEFAULTS = {
    "timezone": "Asia/Shanghai",
    "tick_seconds": 5,
    "night_window": ["00:00", "07:00"],
    "night_min_lead_seconds": 1800,
    "hard_stop": False,
    "custom_window_max_days": 7,
}

_SERVICE_DEFAULTS = {
    "bind": "127.0.0.1:8471",
    "max_concurrent_jobs": 4,
    "max_running_per_user": 1,
    "artifact_max_bytes_per_task": 268_435_456,
    "exchange_ttl_multiplier": 1.5,
    "max_job_seconds": 7200,
    "lease_ttl_seconds": 90,
}

_DATASET_DEFAULTS = {
    "max_task_ids_per_dataset": 500,
    "builtin_view_filter_keys": [
        "scenario",
        "capability",
        "complexity",
        "environment",
        "modality",
        "source",
        "grading_type",
        "task_ids",
    ],
    "category_create_scope": "any",
    "category_delete_scope": "owner_or_admin",
    "pilot_dataset_id": "pilot_v1",
}

_EXCHANGE_DEFAULTS: dict[str, Any] = {
    "exchange_dir": "runtime/exchange",
    "asset_url_ttl_seconds": 3600,
    "max_uploads_per_run": 64,
    "max_bytes_per_artifact": 67_108_864,
    "allowed_extensions": _ARTIFACT_EXTENSIONS,
    # The empty prefix means "anywhere inside the workspace": the corpus does
    # not declare per-task expected outputs, so narrowing to a subdirectory
    # would reject correct answers.  Tightening is a config change once tasks
    # carry output declarations (design section 8, milestone M5).
    "allowed_output_prefixes": [""],
}


_JUDGE_DEFAULTS: dict[str, Any] = {
    "judge_base_url": "https://openrouter.ai/api/v1",
    "judge_model": "openrouter/free",
    "judge_pinned_model": "",
    "api_key_env": "OPENROUTER_API_KEY",
    "judge_timeout_seconds": 120,
    "max_attempts": 5,
    "base_delay_seconds": 2,
}


def load_config(path: Path | str | None = None) -> EvalConfig:
    """Read the service YAML and return a validated :class:`EvalConfig`."""
    config_path = _resolve_config_path(path)
    raw = _read_mapping(config_path)
    return parse_config(raw, config_path.parent)


def parse_config(raw: Mapping[str, Any], relative_to: Path | None = None) -> EvalConfig:
    """Validate a config mapping; ``relative_to`` anchors relative paths."""
    base = Path(relative_to) if relative_to else Path.cwd()
    service = _section(raw, "service")
    schedule = _section(raw, "schedule")
    datasets = _section(raw, "datasets")
    exchange = _section(raw, "exchange")

    public_base_url = _public_base_url(service)
    state_db = _path(service.get("state_db"), base, Path("runtime/state.db"))
    models = _section(raw, "models")
    tick_seconds = float(schedule.get("tick_seconds", _SCHEDULE_DEFAULTS["tick_seconds"]))
    lease_ttl_seconds = float(
        service.get("lease_ttl_seconds", _SERVICE_DEFAULTS["lease_ttl_seconds"])
    )
    max_job_seconds = _as_int(service, "max_job_seconds", _SERVICE_DEFAULTS)
    # A zero or negative interval is not "tick constantly" but "never sleep at
    # all": the loop would hold the event loop and starve the data plane it
    # shares it with.  Rejected here, because nothing downstream can tell a
    # mis-typed 0 from an intended one.
    if tick_seconds <= 0:
        raise ConfigError("schedule.tick_seconds must be a positive number of seconds")
    # A lease that goes stale inside one tick would settle jobs that are alive,
    # and the settle is not reversible: it writes terminal rows.  Two intervals
    # is the least that can tell "the beat is late" from "the process is gone".
    if lease_ttl_seconds < 2 * tick_seconds:
        raise ConfigError(
            "service.lease_ttl_seconds must be at least twice schedule.tick_seconds "
            f"(got {lease_ttl_seconds} and {tick_seconds})"
        )
    if max_job_seconds < 1:
        raise ConfigError("service.max_job_seconds must be a positive number of seconds")

    return EvalConfig(
        service=ServiceConfig(
            bind=_as_str(service, "bind", _SERVICE_DEFAULTS),
            public_base_url=public_base_url,
            state_db=state_db,
            max_concurrent_jobs=_as_int(service, "max_concurrent_jobs", _SERVICE_DEFAULTS),
            max_running_per_user=_as_int(service, "max_running_per_user", _SERVICE_DEFAULTS),
            artifact_max_bytes_per_task=_as_int(
                service, "artifact_max_bytes_per_task", _SERVICE_DEFAULTS
            ),
            exchange_ttl_multiplier=float(
                service.get("exchange_ttl_multiplier", _SERVICE_DEFAULTS["exchange_ttl_multiplier"])
            ),
            max_job_seconds=max_job_seconds,
            lease_ttl_seconds=lease_ttl_seconds,
        ),
        schedule=ScheduleConfig(
            timezone=_as_str(schedule, "timezone", _SCHEDULE_DEFAULTS),
            tick_seconds=tick_seconds,
            night_open=_night_edge(schedule, 0),
            night_close=_night_edge(schedule, 1),
            night_min_lead_seconds=_as_int(
                schedule, "night_min_lead_seconds", _SCHEDULE_DEFAULTS
            ),
            hard_stop=bool(schedule.get("hard_stop", _SCHEDULE_DEFAULTS["hard_stop"])),
            custom_window_max_days=_as_int(schedule, "custom_window_max_days", _SCHEDULE_DEFAULTS),
        ),
        datasets=DatasetConfig(
            # Four levels up is this package's depth below the repository root
            # (service -> acp_remote_eval -> cpd -> pawbench); the corpus ships
            # at the root, not inside the package.
            builtin_dir=_path(
                datasets.get("builtin_dir"),
                base,
                Path("../../../../data/pawbench-v1.0"),
            ),
            custom_dir=_path(datasets.get("custom_dir"), base, Path("runtime/datasets")),
            max_task_ids_per_dataset=_as_int(datasets, "max_task_ids_per_dataset", _DATASET_DEFAULTS),
            builtin_view_filter_keys=frozenset(
                datasets.get("builtin_view_filter_keys", _DATASET_DEFAULTS["builtin_view_filter_keys"])
            ),
            category_create_scope=_as_str(datasets, "category_create_scope", _DATASET_DEFAULTS),
            category_delete_scope=_as_str(datasets, "category_delete_scope", _DATASET_DEFAULTS),
            pilot_dataset_id=_as_str(datasets, "pilot_dataset_id", _DATASET_DEFAULTS),
        ),
        exchange=ExchangeConfig(
            exchange_dir=_path(
                exchange.get("exchange_dir"),
                base,
                Path(_EXCHANGE_DEFAULTS["exchange_dir"]),
            ),
            asset_url_ttl_seconds=_as_int(
                exchange, "asset_url_ttl_seconds", _EXCHANGE_DEFAULTS
            ),
            max_uploads_per_run=_as_int(exchange, "max_uploads_per_run", _EXCHANGE_DEFAULTS),
            max_bytes_per_artifact=_as_int(
                exchange, "max_bytes_per_artifact", _EXCHANGE_DEFAULTS
            ),
            allowed_extensions=frozenset(
                _extensions(
                    _string_list(
                        exchange.get(
                            "allowed_extensions", _EXCHANGE_DEFAULTS["allowed_extensions"]
                        )
                    )
                )
            ),
            allowed_output_prefixes=_prefix_list(
                exchange.get(
                    "allowed_output_prefixes",
                    _EXCHANGE_DEFAULTS["allowed_output_prefixes"],
                )
            ),
            # The hijack list is a floor, not a default: config may add names
            # but cannot remove one and reopen the scoring machine.
            forbidden_names=SCORE_HIJACK_FILENAMES
            | frozenset(_casefolded(_string_list(exchange.get("forbidden_names")))),
            forbidden_suffixes=SCORE_HIJACK_SUFFIXES
            | frozenset(_dotted(_casefolded(_string_list(exchange.get("forbidden_suffixes"))))),
        ),
        judge=_judge_config(models),
        allowlist_path=_optional_path(service.get("allowlist_file"), base),
        source=dict(raw),
    )


def _judge_config(models: Mapping[str, Any]) -> JudgeConfig:
    """The judge half of ``models:``, with the backoff bounds checked.

    ``retry_429`` is validated here rather than in the client because a service
    that starts with ``max_attempts: 0`` would answer every ``llm_judge`` task
    with ``judge_unavailable`` and look, from the outside, like a working service.
    """
    retry = models.get("retry_429") or {}
    if not isinstance(retry, dict):
        raise ConfigError("models.retry_429 must be a mapping of max_attempts / base_delay_seconds")
    max_attempts = int(retry.get("max_attempts", _JUDGE_DEFAULTS["max_attempts"]))
    base_delay = float(retry.get("base_delay_seconds", _JUDGE_DEFAULTS["base_delay_seconds"]))
    if max_attempts < 1:
        raise ConfigError(f"models.retry_429.max_attempts must be at least 1 (got {max_attempts})")
    if base_delay < 0:
        raise ConfigError(
            f"models.retry_429.base_delay_seconds cannot be negative (got {base_delay})"
        )
    timeout_seconds = float(
        models.get("judge_timeout_seconds", _JUDGE_DEFAULTS["judge_timeout_seconds"])
    )
    if timeout_seconds <= 0:
        raise ConfigError("models.judge_timeout_seconds must be a positive number of seconds")
    api_key_env = _as_str(models, "api_key_env", _JUDGE_DEFAULTS)
    if not api_key_env.strip():
        raise ConfigError("models.api_key_env must name the environment variable to read")
    return JudgeConfig(
        base_url=_as_str(models, "judge_base_url", _JUDGE_DEFAULTS),
        model=_as_str(models, "judge_model", _JUDGE_DEFAULTS),
        pinned_model=str(models.get("judge_pinned_model") or "").strip(),
        api_key_env=api_key_env.strip(),
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay,
    )


def _resolve_config_path(path: Path | str | None) -> Path:
    if path is not None:
        return Path(path)
    env_value = os.environ.get(CONFIG_FILE_ENV)
    return Path(env_value) if env_value else DEFAULT_CONFIG_PATH


def _read_mapping(config_path: Path) -> Mapping[str, Any]:
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"top level of {config_path} must be a mapping")
    return raw


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = raw.get(name) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"config section '{name}' must be a mapping")
    return value


def _public_base_url(service: Mapping[str, Any]) -> str:
    value = str(service.get("public_base_url") or "").strip()
    if not value:
        raise ConfigError(
            "service.public_base_url is required. Set it to the address the "
            "evaluated agent can reach this service on (http://localhost:8471 "
            "while developing). It must not be taken from the request Host header."
        )
    if not value.startswith(_URL_SCHEMES):
        raise ConfigError(f"service.public_base_url must start with http:// or https://: {value!r}")
    return value.rstrip("/")


def _as_int(section: Mapping[str, Any], key: str, defaults: Mapping[str, Any]) -> int:
    return int(section.get(key, defaults[key]))


def _as_str(section: Mapping[str, Any], key: str, defaults: Mapping[str, Any]) -> str:
    return str(section.get(key, defaults[key]))


def _string_list(value: Any) -> list[str]:
    """Accept one scalar or a sequence of them, as operators expect to type it."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return [text for text in (str(item).strip() for item in items) if text]


def _casefolded(values: Sequence[str]) -> list[str]:
    """Filenames compare case-insensitively: ``CONFTEST.PY`` is still a trap."""
    return [value.casefold() for value in values]


def _extensions(values: Sequence[str]) -> list[str]:
    """Bare extensions, so ``md``, ``.md`` and ``MD`` all mean the same entry."""
    return [value.casefold().lstrip(".") for value in values if value.strip(".")]


def _dotted(values: Sequence[str]) -> list[str]:
    return [value if value.startswith(".") else f".{value}" for value in values]


def _prefix_list(value: Any) -> tuple[str, ...]:
    """Allowed output prefixes; the empty entry means "anywhere in the workspace"."""
    if value is None:
        return ("",)
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return tuple(str(item).strip().strip("/") for item in items)


def _night_edge(schedule: Mapping[str, Any], index: int) -> str:
    window = schedule.get("night_window", _SCHEDULE_DEFAULTS["night_window"])
    if not isinstance(window, (list, tuple)) or len(window) != 2:
        raise ConfigError(f"schedule.night_window must be [open, close], got: {window!r}")
    return _clock_str(str(window[index]), f"schedule.night_window[{index}]")


def _clock_str(value: str, label: str) -> str:
    hours, _, minutes = value.partition(":")
    if not minutes:
        raise ConfigError(f"{label} must be HH:MM, got {value!r}")
    try:
        hour_int, minute_int = int(hours), int(minutes)
    except ValueError as exc:
        raise ConfigError(f"{label} must be HH:MM, got {value!r}") from exc
    if not (0 <= hour_int <= 23 and 0 <= minute_int <= 59):
        raise ConfigError(f"{label} out of range: {value!r}")
    return f"{hour_int:02d}:{minute_int:02d}"


def _path(value: Any, base: Path, default: Path) -> Path:
    """Resolve a configured path, falling back to ``default`` under ``base``.

    ``base`` is the directory holding the config file, not the repository root,
    so every fallback is written in the same shape as ``config.example.yaml``:
    ``runtime/...`` beside the config, and the corpus reached by climbing out of
    the package.  A repo-root-shaped default such as ``service/state.db``
    resolves to ``<package>/service/state.db`` -- inside ``pawbench/cpd/**``,
    which is what a ``git add`` of this feature picks up, and that database
    holds run tokens and subject endpoint URLs.
    """
    resolved = _optional_path(value, base)
    if resolved is None:
        return (base / default).resolve()
    return resolved


def _optional_path(value: Any, base: Path) -> Path | None:
    if value is None or value == "":
        return None
    candidate = Path(str(value)).expanduser()
    return candidate if candidate.is_absolute() else (base / candidate).resolve()
