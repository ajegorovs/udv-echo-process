"""Real-sitting integration: one writer, independent source-recomputing verifier.

No committed report is touched: each sitting's quartet is written to pytest scratch.
The verifier must read the committed per-pass inventory, not the artifact directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.analysis.sparse_passes import pass_by_name
from udv_echo_process.analysis.sparse_sa5_report import write_sa5_report
from udv_echo_process.analysis.sparse_sa5_verify import verify_sa5_artifacts


@pytest.mark.parametrize("sitting", ("sparse-mixer-live-1", "sparse-mixer-live-2"))
def test_scratch_publication_recomputes_and_reproduces_bytes(
    sitting: str, tmp_path: Path
) -> None:
    """All four products pass independent recomputation and an idempotent rerun."""
    ref = pass_by_name(sitting)
    first = write_sa5_report(ref, tmp_path)
    assert len(first.files) == 4
    assert all((tmp_path / name).read_bytes() == data for name, data in first.files)

    verified = verify_sa5_artifacts(ref, artifact_dir=tmp_path)
    assert verified.effect_count == 72
    assert verified.csv_rows == 72
    assert all(verified.checks.values())

    second = write_sa5_report(ref, tmp_path)
    assert second.files == first.files
    assert all((tmp_path / name).read_bytes() == data for name, data in first.files)
