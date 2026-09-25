"""Shared pass loader must apply the ingest's provenance refusals."""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.analysis import _sparse_pass
from udv_echo_process.analysis.sparse_inventory import SparseIngestError

ROOT = Path(__file__).resolve().parent.parent


def test_live_two_loader_refuses_rewritten_old_law(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _sparse_pass.decode_point
    corrupted = False

    def decode_with_wrong_target(path, binding):
        nonlocal corrupted
        point = original(path, binding)
        if isinstance(point, str) or corrupted:
            return point
        corrupted = True
        old_target = (
            binding.job.emissions_per_profile * binding.job.prf_us * 1e-6 + 0.001
        )
        entry = {
            **point.binding.entry,
            "timing": {**point.binding.entry["timing"], "target_s": old_target},
        }
        return point._replace(binding=point.binding._replace(entry=entry))

    monkeypatch.setattr(_sparse_pass, "decode_point", decode_with_wrong_target)
    with pytest.raises(SparseIngestError, match="planning law"):
        _sparse_pass.decode_pass(
            ROOT / "data/sparse-mixer-live-2",
            plan_path=ROOT / "examples/sparse-mixer-live-2/run-plan.json",
            plan_name="sparse-mixer-live-2",
        )
    assert corrupted


def test_a_pass_the_law_table_does_not_name_is_still_loadable() -> None:
    """Naming a pass in the law table tightens that pass; it must not gate the others.

    The shared loader screens every point's planning target against a form selected by
    pass identity. A pass this repository has analysed but never classified — the
    Stage-2 E64-E20 pairs, whose campaign predates the two-form split — must keep the
    behaviour it had before the table existed, or an already-published report becomes
    unanalysable. This is the regression that made `pytest tests/test_sparse_stage2_pairs.py`
    error 26 times on the first version of the pass-identity table.
    """
    from udv_echo_process.analysis import sparse_inventory, sparse_stage2_pairs

    assert sparse_stage2_pairs.PLAN_NAME not in sparse_inventory.PERIOD_LAW_BY_PASS
    decoded = _sparse_pass.decode_pass(
        sparse_stage2_pairs.DATASET_ROOT,
        plan_path=sparse_stage2_pairs.PLAN_PATH,
        plan_name=sparse_stage2_pairs.PLAN_NAME,
    )
    assert len(decoded.points) == 8
