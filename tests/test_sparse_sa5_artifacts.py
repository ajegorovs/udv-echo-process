"""Freeze the two independently published SA5 within-sitting artifact quartets.

The verifier derives its expected numbers from committed sources without importing
the writer. Regeneration is then compared byte for byte at the manifest's pinned
analysis and generator revisions; no cross-sitting arithmetic is performed.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from udv_echo_process.analysis.sparse_passes import pass_by_name
from udv_echo_process.analysis.sparse_sa5_report import build_sa5_report
from udv_echo_process.analysis.sparse_sa5_verify import verify_sa5_artifacts

ARTIFACT_DIR = Path("reports/sparse-signal")


@pytest.mark.parametrize("sitting", ("sparse-mixer-live-1", "sparse-mixer-live-2"))
def test_published_sitting_recomputes_and_regenerates_byte_for_byte(
    sitting: str,
    tmp_path: Path,
) -> None:
    """Check sources first; independently reproduce each published file's bytes."""
    ref = pass_by_name(sitting)
    verification = verify_sa5_artifacts(ref)
    assert verification.effect_count == verification.csv_rows == 72
    assert all(verification.checks.values())

    stem = f"sa5-live-{sitting[-1]}-effects"
    document = json.loads((ARTIFACT_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    assert document["sitting"] == sitting
    regenerated = build_sa5_report(
        ref,
        analysis_commit=document["analysis_commit"],
        generator_revision=document["generator_revision"],
    )
    assert len(regenerated.files) == 4
    for name, data in regenerated.files:
        assert (ARTIFACT_DIR / name).read_bytes() == data, name

    readme = (ARTIFACT_DIR / f"{stem}.README.md").read_text(encoding="utf-8")
    command = readme.split("## Reproduce\n", 1)[1].split("```bash\n", 1)[1]
    command = command.split("\n```", 1)[0]
    argv = [
        str(tmp_path) if arg == "$SA5_SCRATCH" else arg for arg in shlex.split(command)
    ]
    assert argv[:2] == ["python", "-m"]
    subprocess.run(
        [sys.executable, *argv[1:]], check=True, capture_output=True, text=True
    )
    for name, data in regenerated.files:
        assert (tmp_path / name).read_bytes() == data, name
