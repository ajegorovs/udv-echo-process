"""The real acquire parser/loader with a file-based, explicitly fake backend."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from test_acquire_finite_workflow import BDD, Backend

from udv_echo_process.cli import acquire_main


def files(tmp_path):
    provider = tmp_path / "provider.py"
    marker = tmp_path / "factory-called"
    provider.write_text(
        "from pathlib import Path\nimport shutil\n"
        + "BDD = Path("
        + repr(str(BDD))
        + ")\n"
        + inspect.getsource(Backend)
        + "\ndef finite_preflight(*, request, config_path):\n"
        + "    return {'ready': config_path.read_text() == 'ready'}\n"
        + "\ndef finite_backend(*, request, config_path):\n"
        + "    Path("
        + repr(str(marker))
        + ").write_text('called')\n"
        + "    return Backend(request)\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.json"
    config.write_text("ready")
    definition = tmp_path / "definition.json"
    definition.write_text(
        json.dumps(
            {
                "channels": [
                    {
                        "channel": c,
                        "frequency_khz": 4000,
                        "profiles": 5,
                        "gates": 80,
                        "prf_us": 600,
                        "emissions": 50,
                    }
                    for c in (1, 2)
                ]
            }
        )
    )
    args = [
        "finite",
        "--provider",
        str(provider),
        "--config",
        str(config),
        "--definition",
        str(definition),
        "--name",
        "cli-finite",
        "--store-dir",
        str(tmp_path),
        "--expect-mode",
        "instrument",
    ]
    return args, marker, config


def call(args, capsys):
    with pytest.raises(SystemExit) as result:
        acquire_main(args)
    captured = capsys.readouterr()
    return result.value.code, json.loads(captured.out)


def test_check_uses_actual_loader_but_never_constructs_backend(tmp_path, capsys):
    args, marker, _ = files(tmp_path)
    code, report = call(args + ["--check"], capsys)
    assert code == 0 and report["ready"] is True
    assert report["executes"] is False
    assert not marker.exists()


def test_execution_reaches_real_coordinator_and_decoder(tmp_path, capsys):
    args, marker, _ = files(tmp_path)
    code, report = call(args + ["--execute"], capsys)
    assert code == 0 and report["ok"] is True
    assert report["outcome"] == "stored_and_restored"
    assert marker.exists()
    assert report["artifact"]["streams"] == 2
    assert (tmp_path / "cli-finite.BDD").read_bytes() == BDD.read_bytes()


def test_failed_static_preflight_stops_before_factory(tmp_path, capsys):
    args, marker, config = files(tmp_path)
    config.write_text("not ready")
    code, report = call(args + ["--execute"], capsys)
    assert code == 2 and report["outcome"] == "refused_preflight"
    assert not marker.exists()
    assert not (tmp_path / "cli-finite.BDD").exists()


def test_bad_timing_precedes_provider_import(tmp_path, capsys):
    args, marker, _ = files(tmp_path)
    provider = Path(args[args.index("--provider") + 1])
    provider.write_text("raise AssertionError('provider must not import')")
    code, report = call(args + ["--execute", "--poll-s", "nan"], capsys)
    assert code == 2 and "ValidationError" in report["reason"]
    assert not marker.exists()


def test_input_changed_in_preflight_refuses_before_factory(tmp_path, capsys):
    args, marker, _ = files(tmp_path)
    provider = Path(args[args.index("--provider") + 1])
    text = provider.read_text()
    text = text.replace(
        "return {'ready': config_path.read_text() == 'ready'}",
        "config_path.write_text('changed')\n    return {'ready': True}",
    )
    provider.write_text(text)
    code, report = call(args + ["--execute"], capsys)
    assert code == 2 and "inputs_changed_during_preflight" in report["reason"]
    assert not marker.exists()


def test_report_write_failure_preserves_successful_artifact_and_nonzero_exit(
    tmp_path, capsys, monkeypatch
):
    args, _, _ = files(tmp_path)
    target = tmp_path / "report.json"
    original = Path.open

    def open_path(self, mode="r", *values, **kwargs):
        if self == target and mode == "x":
            raise PermissionError("fixture evidence write denied")
        return original(self, mode, *values, **kwargs)

    monkeypatch.setattr(Path, "open", open_path)
    code, report = call(args + ["--execute", "--report", str(target)], capsys)
    assert code == 2 and not report["ok"]
    assert report["outcome"] == "stored_and_restored"
    assert "PermissionError" in report["evidence_write_problem"]
    assert report["artifact"]["streams"] == 2
    assert report["restoration_owed"] is False
