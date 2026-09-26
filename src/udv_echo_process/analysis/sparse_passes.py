"""The committed sparse passes, typed — the one place a selection control reads them from.

``notebooks/signal_explorer.py`` selects between the committed sparse passes, and it has
carried that list as a dict of bare strings beside a free-text ``sitting`` label. That does
not scale *and* it is already wrong about one dataset: the next analysis stage reads more
dataset roots than the two mixer-enabled sittings, and one of the committed datasets is a
**campaign**, not a sitting
([`docs/dop3000/sparse-signal-analysis-plan.md`](../../../docs/dop3000/sparse-signal-analysis-plan.md)
§"Question and unit of evidence", which puts the Stage-2 design *outside* the
sitting → job → recording hierarchy; and
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../../docs/dop3000/sparse-pass-analysis-plan.md)
§4b, which calls it one campaign block). A third dictionary key labelling it a "sitting"
would state a falsehood in the one line a reader trusts.

**The committed passes, in the repository's own vocabulary.** Each entry below is a dataset
root that carries its own run plan, its own pass record and its own committed recordings,
and each was discovered from those files rather than declared here:

- ``sparse-mixer-first-pass`` — the first sparse pass, a realization of the frozen nine-job
  design whose 26 recordings are **all zero** (the rig was not moving yet). Its role is the
  design's own, a sitting-shaped nine-job block — one record, one design, paused after the
  trial's two jobs and resumed the next morning; it is acquisition evidence, not a third
  live replicate, and it has no report artefacts;
- ``sparse-mixer-live-1`` — the first **mixer-enabled** sitting, the realization the frozen
  WP0–WP5 artefacts are built from;
- ``sparse-mixer-live-2`` — the second mixer-enabled sitting, the SA0 default;
- ``stage2-e20-e64`` — the **Stage-2 campaign**: eight ``run-level`` jobs in four
  counterbalanced E20/E64 pairs, one campaign block, a separate and explicitly identified
  design (``analysis_orientation: E64 - E20``). It is not another interchangeable sitting.

**The role is what the pass's own plan and record state, and nothing here re-derives it.**
A *sitting* is the nine-job design: jobs of kind ``scientific`` / ``common-reference``, a
declared reference condition, and no per-job pair, role or orientation. A *campaign* is a
plan whose jobs are ``run-level`` and whose run record names each job's counterbalanced
pair and its acquisition orientation. The tests read both off the committed plan and
record, so a role cannot be changed here without the dataset contradicting it.

**Identity is delegated, never re-implemented.** "Is this pass what it claims to be" has
exactly one authority — :func:`udv_echo_process.analysis.sparse_inventory.identify_pass`,
which establishes that the plan file names the pass asked for, that the pass record is for
that plan and that the record answers the plan's own fingerprint. :meth:`PassRef.identify`
calls it with this ref's own root, plan path and name and returns the resolved name; it
adds no check of its own, so the catalog cannot accept a pass the frozen ingest would
refuse and a duplicated check cannot drift away from it.

**The period-law metadata has one source, and it is this catalog's.** The planning law a
pass's own logs record is the WP0 table
(:data:`~udv_echo_process.analysis.sparse_inventory.PERIOD_LAW_BY_PASS`), which
:func:`period_law_by_pass` *derives* from these refs: a ref carries the law the table names
for it, and a pass the table does not classify carries ``""``, keeping the behaviour it had
before the table existed (screened against both planning forms rather than refused). The
two law strings themselves are defined here, so a pass is classified by naming its law on
its ref instead of by editing a second table — and the table's existing values and
consumers are unchanged.

**What is deliberately not here.** No registry, no plugin seam, no loader: a frozen tuple
and one lookup by name, which is all a selection control needs. The bounded trial,
``data/sparse-mixer-first-pass-trial``, is **not** a pass of its own and has no ref here:
it is the first pass's own record at the trial's first two jobs, so it shares that pass's
plan name (a second ref would make the name ambiguous) and its record names jobs whose logs
are not committed there, so it cannot be read as a pass at all — ``identify_pass`` resolves
it and the binding refuses it.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from udv_echo_process.models.base import ValueModel

#: The retired profile-period expectation the first mixer-enabled sitting's logs record,
#: ``emissions x PRF + 1 ms``: the form the planner used on the day (it dropped the
#: manual's fixed 16-emission term). It is provenance and never the achieved period, and
#: the logs that carry it are not rewritten.
#: (:data:`udv_echo_process.analysis.sparse_inventory.RETIRED_PERIOD_LAW` is this same
#: string, imported from here; ``RETIRED_PERIOD_TRANSFER_S`` stays in the ingest, which is
#: where the retired form is reproduced as a number.)
RETIRED_PERIOD_LAW = "emissions_per_profile x prf_us + 1 ms"

#: The planner's *corrected* law, ``acquire/plan.py::profile_period_s`` — the manual's
#: ``T_tran + T_prf x (16 + N_PRF)``. The second sitting's logs record this form, so
#: ``require_retired_target`` accepts it too: both are planning expectations for a point's
#: own decoded emissions and PRF, and neither is the achieved period.
PLANNER_PERIOD_LAW = "T_tran + T_prf x (16 + N_PRF) (acquire/plan.py::profile_period_s)"


class PassRole(str, Enum):
    """What kind of committed dataset a pass is — the label a selection control shows."""

    SITTING = "sitting"
    """One live sitting at the instrument: the nine-job design, run as one pass."""

    CAMPAIGN = "campaign"
    """A campaign of its own: run-level jobs in counterbalanced pairs, not one sitting."""


class PassRef(ValueModel):
    """One committed pass: where its bytes are, and what the repository says it is.

    Frozen and ``extra="forbid"`` like every other model here. Every path is relative to
    the repository root, so a ref moves between clones unchanged and is compared as data;
    nothing resolves it here, and no ref is validated against the filesystem at import.
    """

    #: The plan name recorded inside the pass's own ``<name>.run.json``, which is also the
    #: name ``identify_pass`` resolves.
    name: str
    #: The dataset root: the committed recordings plus the pass record, logs and manifests.
    root: Path
    #: The run-plan file the pass is a realization of.
    plan_path: Path
    #: Sitting or campaign, as the pass's own plan and record state it.
    role: PassRole
    #: The one-line human description of the dataset this pass is.
    note: str
    #: The planning law this pass's own logs record, or ``""`` when the WP0 table does not
    #: classify it. See :func:`period_law_by_pass`.
    period_law: str
    #: Whether the pass belongs to the frozen nine-job sparse design whose WP0-WP5
    #: artefacts are frozen. The Stage-2 campaign is a separate design and is ``False``.
    in_frozen_design: bool
    #: Where this pass's frozen report artefacts live, or ``None`` when it has none.
    report_dir: Path | None = None

    @property
    def presentable_as_sitting(self) -> bool:
        """True only for a sitting: a campaign may never carry a sitting's label."""
        return self.role is PassRole.SITTING

    def identify(self) -> str:
        """Resolve this ref through WP0's identity authority, or refuse with its message.

        The import sits inside the method because
        :mod:`udv_echo_process.analysis.sparse_inventory` derives its period-law table from
        this module: a module-level import here would close that cycle, and the delegation
        must not be traded for import convenience.

        Returns:
            The resolved pass name — this ref's ``name``, once the plan file, the pass
            record and the record's plan fingerprint all agree.

        Raises:
            SparseIngestError: naming the disagreement, before any recording is read.
        """
        from udv_echo_process.analysis.sparse_inventory import identify_pass

        _, _, resolved = identify_pass(
            self.root, plan_path=self.plan_path, plan_name=self.name
        )
        return resolved


#: Every committed pass, in the order the repository acquired them. A tuple, so the set is
#: frozen: a new pass is a new dataset with its own plan and record, and its ref is added
#: here rather than assembled at run time.
COMMITTED_PASSES: tuple[PassRef, ...] = (
    PassRef(
        name="sparse-mixer-first-pass",
        root=Path("data/sparse-mixer-first-pass"),
        plan_path=Path("examples/sparse-mixer-first-pass/run-plan.json"),
        role=PassRole.SITTING,
        note=(
            "the zero-signal first pass — the nine-job design's first realization; all 26 "
            "recordings are zero, so it is acquisition evidence, not a third live "
            "replicate, and it has no report artefacts"
        ),
        # The WP0 table does not classify this pass: its logs predate the two-form split,
        # and naming a form for it would be a tightening of its screening that a display
        # catalog may not make silently.
        period_law="",
        in_frozen_design=True,
        report_dir=None,
    ),
    PassRef(
        name="sparse-mixer-live-1",
        root=Path("data/sparse-mixer-live-1"),
        plan_path=Path("examples/sparse-mixer-live-1/run-plan.json"),
        role=PassRole.SITTING,
        note=(
            "first mixer-enabled sitting — its WP0-WP5 artefacts are frozen; opening it "
            "displays stored recordings and regenerates nothing"
        ),
        period_law=RETIRED_PERIOD_LAW,
        in_frozen_design=True,
        report_dir=Path("reports/sparse-mixer-live-1"),
    ),
    PassRef(
        name="sparse-mixer-live-2",
        root=Path("data/sparse-mixer-live-2"),
        plan_path=Path("examples/sparse-mixer-live-2/run-plan.json"),
        role=PassRole.SITTING,
        note="second mixer-enabled sitting — SA0 default",
        period_law=PLANNER_PERIOD_LAW,
        in_frozen_design=True,
        report_dir=Path("reports/sparse-mixer-live-2"),
    ),
    PassRef(
        name="stage2-e20-e64",
        root=Path("data/stage2-e20-e64"),
        plan_path=Path("examples/stage2-e20-e64/run-plan.json"),
        role=PassRole.CAMPAIGN,
        note=(
            "the Stage-2 campaign — eight run-level jobs in four counterbalanced E20/E64 "
            "pairs (E64 - E20), a separate design and not another interchangeable sitting"
        ),
        # An older campaign: screened against both planning forms, exactly as it was
        # before the WP0 table existed, so this catalog must not name a form for it.
        period_law="",
        in_frozen_design=False,
        report_dir=Path("reports/stage2-e20-e64"),
    ),
)


def period_law_by_pass() -> dict[str, str]:
    """The planning law each committed pass's logs record, by pass name.

    The single source of the WP0 period-law table
    (:data:`udv_echo_process.analysis.sparse_inventory.PERIOD_LAW_BY_PASS`), which derives
    itself from this function: each pass names its own law on its ref rather than in a
    second table. Only a ref that carries a law contributes an entry — a pass the table
    does not classify must keep the behaviour it had before the table existed, which is to
    be screened against *both* planning forms rather than refused.
    """
    return {ref.name: ref.period_law for ref in COMMITTED_PASSES if ref.period_law}


def pass_by_name(name: str) -> PassRef:
    """The one committed ref whose plan name is ``name``.

    Raises:
        KeyError: for a name no committed pass carries, with the committed names in the
            message, so a selection mistake is a stated absence rather than a ``None``.
    """
    for ref in COMMITTED_PASSES:
        if ref.name == name:
            return ref
    raise KeyError(
        f"no committed pass is named {name!r}; the committed passes are "
        f"{[ref.name for ref in COMMITTED_PASSES]}"
    )
