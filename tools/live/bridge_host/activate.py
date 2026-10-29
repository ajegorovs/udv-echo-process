"""The passive preflight as a script, so a parent can exercise it before any recording grant.

It prints the activation report as JSON and exits **0** only when every check passed, **2** when one
did not — the same "a refusal is a message and an exit code, never a traceback" shape the live verbs
use. It dispatches nothing and presses nothing: it reads the config, starts one bounded session to
observe the identity, the owner and the routines, and closes it.

    python tools/live/bridge_host/activate.py --table <machine-local table.json>
    python tools/live/bridge_host/activate.py --table <table.json> --target-digest <sha256> --strip
    python tools/live/bridge_host/activate.py --table <table.json> --sequence store --strip

``--strip`` reads the strip through the GUI surface, which is a window read; it needs the
interactive session like every other screen read. Without it the preflight still answers for the
binding, which is the part a decision to record depends on.

``--sequence`` picks which *closed* operation sequence is being activated — the record/stop/store
cycle by default, or ``store`` for the store-completed path — and it must agree with the host config
beside the table. A disagreement is a failed check, and a failed check is a gate: nothing is attached
to, because starting the producer runs its own start-up (on the recording sequence, a parameter prime).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make its own package importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge_host.api import HostRefusal, _new_actuator, activation_report
from udv_echo_process.acquire.bridge import BridgeUnavailable, load_table

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Print the report and answer with an exit code; refuse rather than raise."""
    parser = argparse.ArgumentParser(
        prog="activate.py",
        description="Report whether the guarded cycle's host can run, without recording anything",
    )
    parser.add_argument("--table", required=True, help="the machine-local bridge table")
    parser.add_argument(
        "--target-digest",
        default=None,
        help="the build digest the caller believes is running (checked against the table)",
    )
    parser.add_argument("--channel", type=int, default=None, help="measurement channel")
    parser.add_argument(
        "--sequence",
        choices=("record_stop_store", "store"),
        default="record_stop_store",
        help=(
            "which closed operation sequence to activate: the record/stop/store cycle (default) or "
            "the store-completed path, which must match the host config beside the table"
        ),
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="static checks only: do not attach, so nothing is observed and nothing is bound",
    )
    parser.add_argument(
        "--menu-dispatch-module",
        default=None,
        help=(
            "path to the proven menu dispatch module; without it the channel verification would "
            "hover, so background readiness is refused"
        ),
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="also read the strip through the GUI surface (needs the interactive session)",
    )
    args = parser.parse_args(argv)

    table_path = Path(args.table)
    try:
        table = load_table(table_path)
    except BridgeUnavailable as refusal:
        print(
            json.dumps(
                {
                    "ready": False,
                    "checks": [{"name": "table", "ok": False, "detail": str(refusal)}],
                },
                indent=2,
            )
        )
        return 2

    strip_reader = None
    if args.strip:
        try:
            actuator = _new_actuator(args.channel)
        except HostRefusal as refusal:
            print(
                json.dumps(
                    {
                        "ready": False,
                        "checks": [
                            {"name": "actuator", "ok": False, "detail": str(refusal)}
                        ],
                    },
                    indent=2,
                )
            )
            return 2
        strip_reader = actuator.strip_state  # type: ignore[attr-defined]

    menu_dispatch = None
    if args.menu_dispatch_module is not None:
        try:
            from bridge_host.menu import legacy_dispatch

            menu_dispatch = legacy_dispatch(args.menu_dispatch_module)
        except HostRefusal as refusal:
            print(
                json.dumps(
                    {
                        "ready": False,
                        "checks": [
                            {
                                "name": "menu_dispatch",
                                "ok": False,
                                "detail": str(refusal),
                            }
                        ],
                    },
                    indent=2,
                )
            )
            return 2

    report = activation_report(
        table=table,
        table_path=table_path,
        target_digest=args.target_digest,
        channel=args.channel,
        sequence=args.sequence,
        probe=not args.no_probe,
        strip_reader=strip_reader,
        menu_dispatch=menu_dispatch,
    )
    print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
