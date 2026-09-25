"""Shared pass loader must apply the ingest's provenance refusals."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from udv_echo_process.analysis import _sparse_pass
from udv_echo_process.analysis.sparse_inventory import (
    SparseIngestError,
    build_sparse_ingest,
)

ROOT = Path(__file__).resolve().parent.parent

LIVE2_ROOT = ROOT / "data" / "sparse-mixer-live-2"
LIVE2_PLAN = ROOT / "examples" / "sparse-mixer-live-2" / "run-plan.json"
LIVE2_NAME = "sparse-mixer-live-2"
LIVE2_RECORD = f"{LIVE2_NAME}.run.json"

#: The two readers of one pass: the ingest that writes the frozen table, and the live loader
#: a notebook holds the recordings through. Every pass-level refusal must hold for both.
READERS: tuple[tuple[str, Callable[..., object]], ...] = (
    ("build_sparse_ingest", build_sparse_ingest),
    ("decode_pass", _sparse_pass.decode_pass),
)


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


# ── one pass identity, two readers ─────────────────────────────────────


def _refusal(reader: Callable[..., object], **kwargs: object) -> str:
    """Call one reader expecting a provenance refusal, and return its message."""
    with pytest.raises(SparseIngestError) as raised:
        reader(**kwargs)
    return str(raised.value)


def _copy_live_two(tmp_path: Path) -> Path:
    import shutil

    target = tmp_path / "dataset"
    shutil.copytree(LIVE2_ROOT, target)
    return target


def _corrupt_record(dataset: Path, **changes: object) -> None:
    """Rewrite top-level fields of the pass record, leaving the recordings themselves alone."""
    path = dataset / LIVE2_RECORD
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(changes)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_both_readers_refuse_a_pinned_name_that_is_not_the_plan() -> None:
    """A pass name that is not the plan's own is refused by both readers, with one message.

    This needs no byte surgery: the identity is established before any recording is read.
    """
    messages = {
        name: _refusal(
            reader,
            dataset_root=LIVE2_ROOT,
            plan_path=LIVE2_PLAN,
            plan_name="sparse-mixer-live-1",
        )
        for name, reader in READERS
    }
    assert "this pass is 'sparse-mixer-live-1'" in messages["build_sparse_ingest"]
    assert messages["decode_pass"] == messages["build_sparse_ingest"]


@pytest.mark.parametrize(
    "change",
    ({"plan": "sparse-mixer-live-1"}, {"plan_fingerprint": "0" * 64}),
    ids=("record-plan", "record-fingerprint"),
)
def test_both_readers_refuse_a_record_that_answers_another_plan(
    tmp_path: Path, change: dict[str, object]
) -> None:
    """A record whose plan or fingerprint disagrees with the plan file is refused by both.

    This is what the live loader was missing while it carried only the per-point refusals:
    it could decode a pass combination the frozen table refuses, so a notebook holding the
    recordings directly could display one.
    """
    dataset = _copy_live_two(tmp_path)
    _corrupt_record(dataset, **change)
    messages = {
        name: _refusal(
            reader, dataset_root=dataset, plan_path=LIVE2_PLAN, plan_name=LIVE2_NAME
        )
        for name, reader in READERS
    }
    assert "pass record" in messages["build_sparse_ingest"], messages
    assert messages["decode_pass"] == messages["build_sparse_ingest"]
