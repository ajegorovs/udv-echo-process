"""Real-sitting integration: the cross writer over the two committed source quartets.

No committed report is touched: the artifact set is written to pytest scratch, twice, and the
two committed source quartets are asserted byte-unchanged. The two sides are always read from
the fixed committed source root, never from the scratch output directory. No independent
verifier is imported — the writer is exercised on its own.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from udv_echo_process.analysis import sparse_sa5_cross_report as w

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "sparse-signal"


def _source_snapshot() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(REPORT_DIR.glob("sa5-live-*"))
    }


def test_scratch_publication_is_reproducible_and_idempotent(tmp_path: Path) -> None:
    """The four products are built, staged and left byte-identical on a rerun."""
    before = _source_snapshot()
    first = w.write_cross_report(
        tmp_path, source_dir=REPORT_DIR, analysis_commit="t", generator_revision="t"
    )
    assert len(first.files) == 4
    assert all((tmp_path / name).read_bytes() == data for name, data in first.files)
    assert first.document()["ok"] is True
    assert len(first.document()["comparisons"]) == 72
    assert len(first.document()["npz_members"]) == 280

    second = w.write_cross_report(
        tmp_path, source_dir=REPORT_DIR, analysis_commit="t", generator_revision="t"
    )
    assert second.files == first.files
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(first.names)

    # The two frozen source quartets are byte-unchanged, and no cross file was committed.
    assert _source_snapshot() == before
    assert not list(REPORT_DIR.glob("sa5-cross-sitting.*"))


def test_the_cli_publishes_the_fixed_comparison_into_scratch(tmp_path: Path) -> None:
    """``cross_report_main`` resolves the two fixed sides and exits 0."""
    destination = tmp_path / "cli"
    with pytest.raises(SystemExit) as raised:
        w.cross_report_main(
            [
                "--report-dir",
                str(destination),
                "--analysis-commit",
                "t",
                "--generator-revision",
                "t",
            ]
        )
    assert raised.value.code == 0
    document = (destination / f"{w.STEM}.json").read_text(encoding="utf-8")
    assert '"comparison":"live2 - live1"' in document
    assert '"ok":true' in document


def test_a_scratch_run_still_records_the_canonical_generator_command(
    tmp_path: Path,
) -> None:
    """The outputs land in scratch, but the recorded command names the committed root."""
    artifacts = w.write_cross_report(
        tmp_path, source_dir=REPORT_DIR, analysis_commit="t", generator_revision="t"
    )
    assert (tmp_path / f"{w.STEM}.json").is_file()
    document = artifacts.document()
    assert document["generator_command"] == (
        "python -m udv_echo_process.analysis.sparse_sa5_cross_report "
        "--report-dir reports/sparse-signal"
    )
    assert str(tmp_path) not in document["generator_command"]
