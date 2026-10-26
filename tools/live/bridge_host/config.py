"""The host config: everything machine-specific, in one explicit file beside the table.

The run is already configured with a machine-local table (``--bridge-table`` /
``UDV_BRIDGE_TABLE``). The host needs a few more facts — where the producer lives, where the store
directory is, how long a session may last — and none of them belongs in code, in a tracked file, or
in a new environment variable. So they live in a JSON file **next to the table**, which makes the
path explicit and derivable from an input the caller already passed: no new environment read, no
search path, no fallback to a guessed location.

Nothing here carries an address. The handler addresses stay in the table, which is already
build-pinned; this file adds only what the host does, never what the application is.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError

from bridge_host.contract import HOST_CONFIG_SCHEMA, HostRefusal
from udv_echo_process.models.base import ValueModel

__all__ = ["HostConfig", "ProducerCommand", "host_config_path", "load_host_config"]


class ProducerCommand(ValueModel):
    """How to start the machine-local producer.

    ``argv`` is an explicit argument vector — never a shell string — so an argument containing a
    space cannot become two arguments, and the session directory is appended by the channel as the
    producer's last argument (the protocol's one positional convention).
    """

    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str | None = None


class HostConfig(ValueModel):
    """The host half's configuration, validated as a whole.

    The timing fields mirror the cycle's own knobs rather than inventing a second vocabulary: a host
    that needs a short window for a rehearsal sets it here, and the cycle it builds carries it. The
    defaults are the cycle's defaults, so an empty config behaves like `RoutineCycle`'s constructor.

    ``schema`` is an alias rather than a field name for the reason ``BridgeTable`` gives: a field
    called ``schema`` shadows a deprecated ``BaseModel`` member, so the field is ``schema_id`` and the
    file says ``schema``.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_default=True, populate_by_name=True
    )

    schema_id: str = Field(default=HOST_CONFIG_SCHEMA, alias="schema")
    #: Where a point lands. Required: the dialog's remembered directory is not evidence.
    store_directory: str = Field(min_length=1)
    producer: ProducerCommand | None = None
    #: Bounds around the producer. A session never outlives its budget.
    start_timeout_s: float = Field(default=90.0, ge=0.0)
    dispatch_timeout_s: float = Field(default=60.0, ge=0.0)
    probe_timeout_s: float = Field(default=20.0, ge=0.0)
    close_timeout_s: float = Field(default=5.0, ge=0.0)
    total_budget_s: float = Field(default=600.0, ge=0.0)
    #: Around the Store dialog, and the cycle's own waits.
    dialog_timeout_s: float = Field(default=10.0, ge=0.0)
    stop_settle_s: float = Field(default=1.5, ge=0.0)
    store_settle_s: float = Field(default=1.5, ge=0.0)
    store_timeout_s: float = Field(default=30.0, ge=0.0)
    state_timeout_s: float = Field(default=5.0, ge=0.0)
    poll_s: float = Field(default=0.5, ge=0.0)

    @classmethod
    def defaults_for(cls, store_directory: Path) -> HostConfig:
        """A config carrying only the store directory — the defaults, for a caller that has no file.

        It is not a usable host config on its own (there is no producer), and every consumer checks
        that before it attaches: this exists so timing questions can be asked without inventing a
        producer command.
        """
        return cls(store_directory=str(store_directory))


def host_config_path(table_path: str | Path) -> Path:
    """The host config belonging to a table: its sibling, named after it.

    ``table.json`` → ``table.host.json``. A pair that travels together stays together, and a run that
    names its table has therefore named its host config — with no second flag to forget.
    """
    location = Path(table_path)
    return location.with_name(f"{location.stem}.host.json")


def load_host_config(table_path: str | Path) -> HostConfig:
    """Read and validate the host config beside ``table_path``, or refuse by name."""
    location = host_config_path(table_path)
    if not location.is_file():
        raise HostRefusal(f"host_config_missing:{location}")
    try:
        raw = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HostRefusal(
            f"host_config_unreadable:{location}:{type(exc).__name__}"
        ) from None
    if not isinstance(raw, Mapping):
        raise HostRefusal("host_config_invalid:not an object")
    found = raw.get("schema")
    if found != HOST_CONFIG_SCHEMA:
        raise HostRefusal(f"host_config_schema:{found}")
    try:
        return HostConfig.model_validate(dict(raw))
    except ValidationError as exc:
        raise HostRefusal(f"host_config_invalid:{exc}") from None
