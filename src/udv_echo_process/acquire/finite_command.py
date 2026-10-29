"""CLI construction for an explicit trusted finite provider; never a GUI fallback."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from udv_echo_process.acquire.finite_workflow import (
    FiniteInvocation,
    invocation_problem,
    run_finite,
)


def add_parser(subcommands) -> None:
    """Register the opt-in finite command without constructing a backend."""
    parser = subcommands.add_parser(
        "finite", help="one finite Run/store/restore through a private provider"
    )
    parser.add_argument("--provider", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--store-dir", type=Path, required=True)
    parser.add_argument(
        "--expect-mode", choices=("instrument", "simulation"), required=True
    )
    parser.add_argument("--observe-timeout-s", type=float, default=25.0)
    parser.add_argument("--poll-s", type=float, default=0.2)
    parser.add_argument("--attachment-window-s", type=float, default=4.0)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--json", action="store_true", help="JSON is always emitted for this command"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--check",
        action="store_true",
        help="static provider admission only; no backend construction",
    )
    action.add_argument(
        "--execute",
        action="store_true",
        help="one gated phase chain; no automatic recovery",
    )


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("udv_finite_provider", path)
    if spec is None or spec.loader is None:
        raise ValueError("finite_provider_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(args: argparse.Namespace) -> int:
    """Validate before loading trusted code; never construct after failed static admission.

    Provider imports and finite_preflight are contractually static: Python code
    is trusted and cannot be sandboxed by this loader. The factory must not
    attach/mutate during construction; guarded effects start at phase methods.
    Reports are JSON on stdout even when post-effect report persistence fails.
    """
    result: dict = {"ok": False, "outcome": "refused_preflight"}
    try:
        definition = json.loads(args.definition.read_text(encoding="utf-8"))
        if not isinstance(definition, dict) or set(definition) - {
            "channels",
            "sequences",
        }:
            raise ValueError("finite_definition_fields_invalid")
        request = FiniteInvocation(
            **definition,
            name=args.name,
            store_directory=args.store_dir,
            expect_mode=args.expect_mode,
            observe_timeout_s=args.observe_timeout_s,
            poll_s=args.poll_s,
            attachment_window_s=args.attachment_window_s,
        )
        problem = invocation_problem(request)
        if problem:
            raise ValueError(problem)
        if not args.provider.is_file() or not args.config.is_file():
            raise ValueError("finite_provider_or_config_missing")
        if args.report is not None:
            if args.report.exists() or not args.report.parent.is_dir():
                raise ValueError("finite_report_taken_or_parent_missing")
            if (
                args.report.resolve()
                == (request.store_directory / (request.name + ".BDD")).resolve()
            ):
                raise ValueError("finite_report_is_artifact_path")
        pins = {
            "provider": _digest(args.provider),
            "config": _digest(args.config),
            "definition": _digest(args.definition),
        }
        module = _load(args.provider)
        preflight = getattr(module, "finite_preflight", None)
        factory = getattr(module, "finite_backend", None)
        if not callable(preflight) or not callable(factory):
            raise TypeError("finite_provider_exports_missing")
        admission = preflight(request=request, config_path=args.config)
        if not isinstance(admission, dict) or admission.get("ready") is not True:
            result["preflight"] = admission
            raise ValueError("finite_provider_preflight_refused")
        current = {
            "provider": _digest(args.provider),
            "config": _digest(args.config),
            "definition": _digest(args.definition),
        }
        if pins != current:
            raise ValueError("finite_inputs_changed_during_preflight")
        if args.check:
            result = {
                "ready": True,
                "executes": False,
                "constructs_backend": False,
                "preflight": admission,
                "source": pins,
            }
        else:
            backend = factory(request=request, config_path=args.config)
            required = (
                "prepare",
                "configure",
                "enable",
                "observe",
                "store",
                "close",
                "restore",
                "verify",
                "residual",
                "source_evidence",
            )
            if any(not callable(getattr(backend, name, None)) for name in required):
                raise ValueError("finite_backend_contract_incomplete")
            result = run_finite(request, backend)
            result["provider_source"] = pins
    except Exception as exc:  # noqa: BLE001 - retain provider/refusal diagnostics on the CLI boundary
        result["reason"] = f"{type(exc).__name__}:{exc}"
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, default=str)
                handle.write("\n")
        except OSError as exc:
            result["evidence_write_problem"] = f"{type(exc).__name__}:{exc}"
            result["ok"] = False
    print(json.dumps(result, indent=2, default=str))
    if result.get("evidence_write_problem"):
        return 2
    return (
        0
        if result.get("ok") is True or (args.check and result.get("ready") is True)
        else 2
    )
