"""WP5 of the sparse-pass analysis: the Stage-2 decision synthesis.

**What this is, and what it is not.** WP5 measures nothing. Every number in its table is
**read from a frozen slice's own artefact** — WP0's ingest, WP1's per-job anchor floors,
WP2's between-run reference floor, WP3's interaction, WP4's ladder — and the synthesis
refuses to publish if a slice is missing, if a slice's own gate did not hold, or if two
slices disagree about a floor they both report. It is a *decision* layer: the four
measurement slices answer what was observed, and this one answers what may be concluded
about the next acquisition.

**The seven columns, and why those.** The table carries the same seven columns the
historical sweep's decision table uses — the evidence, the floor it was screened against
(and the observed effect against it), the information gained, the automation needed, the
verdict, and the measurement that would overturn the verdict — so the two tables are
comparable row for row. Two machine fields are added on top: ``decision_class`` and
``scope``.

**The distinction the table exists to keep.** Every row says whether its question is
*measured and resolved*, *not detected at this design's floors*, *not resolvable with this
design*, or *not measured* — four different things that a single "no effect" would
flatten. WP3 is the case that matters most: it does **not** show that a pitch x burst
interaction is absent, it shows a scalar interaction-shaped difference larger than the
between-run floor and smaller than the burst jobs' own anchor movement. That is a
limitation of *separability*, not evidence of zero interaction, and the row says so in
those words.

**The vocabulary is the plan's, not this module's.** A verdict is one of ``keep``,
``defer``, ``replace`` or ``requires diagnostic`` — the four words the historical table
uses — and no row may be retained merely because the instrument accepts the setting. A
row is ``keep`` only when the pass measured what the question asked; otherwise it is
``defer`` (unresolved now, with the condition that would reopen it named), ``replace``
(a cost rationale for a level no measurement prefers) or ``requires diagnostic`` (cannot
be measured on this surface at all).

**What it recommends, if anything.** A small **targeted** campaign, or nothing. A dense
second pass is refused on the pass's own evidence: the binding constraint on the pitch x
burst interaction is the burst jobs' own anchor movement (9.646 and 11.980 mm/s), and more
points of the same design do not shrink it, so a broad sweep would reproduce the same
floor. The one unresolved distinction that additional run-level realizations *can*
resolve is E20 versus E64, whose difference straddles the between-run floor depending on
which of the four E20 runs it is compared with; the recommendation is therefore a handful
of additional **run-level** realizations of the E64 condition, with an acceptance
criterion stated in advance, and nothing else.

D1 (the higher-sensitivity condition) is **outside this decision, as the plan requires**:
the committed files carry one axial-velocity channel each, so a sensitivity/SNR question
cannot be asked of them at all. Its row is present for the reader and marked as outside
the Stage-2 scope - it is a capability project, not a Stage-2 acquisition.

Import-safe, offline, stdlib + the frozen slices' own modules only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from udv_echo_process.analysis.sparse_inventory import (
    DATASET_ROOT,
    REPORT_DIR,
    SparseIngestError,
)

#: The plan this synthesis decides against, as the repository paths it.
PLAN_DOC = Path("docs/dop3000/sparse-pass-analysis-plan.md")
from udv_echo_process.models.base import ValueModel

# ── constants ──────────────────────────────────────────────────────────

#: The frozen slices this synthesis reads, by the key its own document uses.
SLICES: tuple[tuple[str, str, str], ...] = (
    (
        "WP0",
        "qc-summary.json",
        "the ingest: the pass's points, its window and its checks",
    ),
    ("WP1", "anchor-floor.json", "each scientific job's own block-local anchor floor"),
    ("WP2", "reference-floor.json", "the between-run reference floor, both endpoints"),
    ("WP3", "pitch-burst.json", "the pitch x burst interaction on the common knots"),
    (
        "WP4",
        "emissions-ladder.json",
        "the emissions ladder's stability and temporal cost",
    ),
)

#: The plan's own four decision words, unchanged so the two tables compare.
VERDICTS: tuple[str, ...] = ("keep", "defer", "replace", "requires diagnostic")

#: How a question stands after this pass. The first is a measurement; the second is a
#: measurement that found nothing at the floors it screened against; the third is a
#: question the design cannot separate; the fourth has no measurement at all.
DECISION_CLASSES: tuple[str, ...] = (
    "measured and resolved",
    "not detected at this design's floors",
    "not resolvable with this design",
    "not measured",
)

#: A row is either part of the Stage-2 decision or explicitly outside it.
#: The Stage-2 acquisition order, counterbalanced so that neither level always leads a pair.
#: One definition for the campaign and for the answer that quotes it: when the two were written
#: out separately the answer kept the pre-counterbalancing order, which is exactly the
#: divergence a second copy invites.
STAGE2_SEQUENCE: tuple[str, ...] = (
    "E20-A",
    "E64-A",
    "E64-B",
    "E20-B",
    "E20-C",
    "E64-C",
    "E64-D",
    "E20-D",
)

STAGE_SCOPE = "stage-2 decision"
OUTSIDE_SCOPE = "outside the stage-2 decision: its own capability project"

CSV_NAME = "decision-table.csv"
DOC_NAME = "decision-table.json"
MD_NAME = "decision-table.md"
FLOOR_TOLERANCE_MM_S = 1e-3


class DecisionSynthesisError(SparseIngestError):
    """The synthesis cannot be built, or a caller asked for one it cannot justify."""


# ── models ─────────────────────────────────────────────────────────────


class SliceRef(ValueModel):
    """One frozen slice, as the synthesis cites it."""

    name: str
    path: str
    sha256: str
    recorded_revision: str
    what_it_is: str
    checks_passed: int
    checks_total: int
    ok: bool


class FloorRef(ValueModel):
    """One floor, read from the slice that measured it - never declared here."""

    name: str
    value_mm_s: float
    endpoint: str
    source_slice: str
    applies_to: str


class DecisionRow(ValueModel):
    """One outstanding acquisition question and its disposition."""

    key: str
    question: str
    evidence: str
    evidence_refs: tuple[str, ...]
    applicable_floor: str
    floor_mm_s: float | None
    observed_effect: str
    observed_effect_mm_s: float | None
    interpretation: str
    decision_class: str
    automation: str
    verdict: str
    scope: str
    overturning_measurement: str


class OrderedAnswer(ValueModel):
    """One of the five questions the plan's gate requires, answered in its order."""

    order: int
    question: str
    answer: str
    evidence_refs: tuple[str, ...]


class Stage2Campaign(ValueModel):
    """What, if anything, is worth acquiring next - and what is refused."""

    recommended: bool
    justification: str
    pair_design: str
    sequence: tuple[str, ...]
    conditions: tuple[str, ...]
    recordings: int
    buys: tuple[str, ...]
    acceptance: str
    refused: tuple[str, ...]


class DecisionSynthesis(ValueModel):
    """WP5's whole result: the slices it read, the floors, the rows and the campaign."""

    dataset_root: str
    plan: str
    plan_path: str
    plan_fingerprint: str
    plan_doc: str
    analysis_commit: str
    slices: tuple[SliceRef, ...]
    floors: tuple[FloorRef, ...]
    rows: tuple[DecisionRow, ...]
    answers: tuple[OrderedAnswer, ...]
    campaign: Stage2Campaign
    story: dict[str, object]
    checks: dict[str, bool]

    @property
    def ok(self) -> bool:
        """Every structural check holds."""
        return all(self.checks.values())

    def row(self, key: str) -> DecisionRow:
        """One row by key."""
        for row in self.rows:
            if row.key == key:
                return row
        raise DecisionSynthesisError(f"no decision row keyed {key!r}")


# ── reading the frozen slices ──────────────────────────────────────────


def _load(report_dir: Path, name: str, slice_name: str) -> tuple[dict, str, str]:
    """One slice's document, its content digest and its path as the document names it."""
    path = Path(report_dir) / name
    if not path.is_file():
        raise DecisionSynthesisError(
            f"{slice_name}: {name} is missing under {report_dir.as_posix()!r} - this "
            "synthesis reads the frozen slices' artefacts and cannot recompute them"
        )
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionSynthesisError(
            f"{slice_name}: {name} is not a readable JSON document ({exc})"
        ) from exc
    if not isinstance(document, dict):
        raise DecisionSynthesisError(f"{slice_name}: {name} is not a JSON object")
    return document, hashlib.sha256(raw).hexdigest(), f"{Path(report_dir).name}/{name}"


def _at(document: dict, path: str, slice_name: str):
    """A value by dotted path, refused by name rather than defaulted."""
    node: object = document
    for step in path.split("."):
        if isinstance(node, dict) and step in node:
            node = node[step]
        else:
            raise DecisionSynthesisError(
                f"{slice_name}: the document has no {path!r} - this synthesis reads "
                "published values only and will not substitute its own"
            )
    return node


def _number(document: dict, path: str, slice_name: str) -> float:
    value = _at(document, path, slice_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionSynthesisError(
            f"{slice_name}: {path!r} is {type(value).__name__}, not a number"
        )
    return float(value)


def _slice_ref(
    name: str, path: str, what: str, document: dict, digest: str
) -> SliceRef:
    checks = document.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise DecisionSynthesisError(
            f"{name}: {path} carries no named checks - a slice whose gate is absent "
            "cannot be cited as evidence"
        )
    ok = document.get("ok") is True and all(checks.values())
    if not ok:
        failed = sorted(key for key, value in checks.items() if not value)
        raise DecisionSynthesisError(
            f"{name}: {path} did not hold its own gate ({failed!r}) - the synthesis "
            "will not build on a slice that failed"
        )
    revision = str(document.get("analysis_commit") or "")
    if not revision:
        raise DecisionSynthesisError(
            f"{name}: {path} records no generator revision, so the numbers it carries "
            "cannot be traced"
        )
    return SliceRef(
        name=name,
        path=path,
        sha256=digest,
        recorded_revision=revision,
        what_it_is=what,
        checks_passed=sum(1 for value in checks.values() if value),
        checks_total=len(checks),
        ok=True,
    )


def read_slices(
    report_dir: Path = REPORT_DIR,
) -> tuple[dict[str, dict], tuple[SliceRef, ...]]:
    """Read the five slices, refusing anything that is missing or failed."""
    documents: dict[str, dict] = {}
    refs: list[SliceRef] = []
    for name, filename, what in SLICES:
        document, digest, _ = _load(report_dir, filename, name)
        refs.append(_slice_ref(name, filename, what, document, digest))
        documents[name] = document
    return documents, tuple(refs)


# ── the floors, read rather than declared ──────────────────────────────


def read_floors(documents: dict[str, dict]) -> tuple[FloorRef, ...]:
    """Every floor this decision uses, taken from the slice that measured it.

    Three slices report floors - WP1 the per-job anchor spreads, WP2 the two endpoints,
    WP3 and WP4 their copies of both - so the synthesis reads them all and **refuses if
    the copies disagree**: a decision that quotes a floor two slices disagree about is
    worse than no decision.
    """
    wp2, wp3, wp4 = documents["WP2"], documents["WP3"], documents["WP4"]
    w2_resolved = _number(wp2, "floor.depth_resolved.value_mm_s", "WP2")
    w2_averaged = _number(wp2, "floor.depth_averaged.value_mm_s", "WP2")
    w3_resolved = _number(wp3, "floors.depth_resolved.value_mm_s", "WP3")
    w3_averaged = _number(wp3, "floors.depth_averaged.value_mm_s", "WP3")
    w3_anchors = _at(wp3, "floors.anchor_guards.value_mm_s", "WP3")
    w4_anchors = {}
    for binding in _at(wp4, "floors.bindings", "WP4"):
        name = str(binding.get("name", ""))
        value = binding.get("recomputed_mm_s", binding.get("published_mm_s"))
        if name.startswith("job_anchors_") and value is not None:
            w4_anchors[name.removeprefix("job_anchors_").upper()] = float(value)

    disagreements: list[str] = []
    for name, left, right in (
        ("WP2's depth-resolved endpoint", w2_resolved, w3_resolved),
        ("WP2's depth-averaged endpoint", w2_averaged, w3_averaged),
    ):
        if abs(left - right) > FLOOR_TOLERANCE_MM_S:
            disagreements.append(f"{name}: WP2 {left!r} against WP3 {right!r}")
    jobs = {str(job["job"]): job for job in _at(documents["WP1"], "jobs", "WP1")}
    wp1_spreads = {
        job: float(jobs[job]["spread"]["mean"])
        for job in jobs
        if job in ("burst-4", "burst-18")
    }
    for job, value in wp1_spreads.items():
        other = w3_anchors.get(job)
        if other is not None and abs(value - float(other)) > FLOOR_TOLERANCE_MM_S:
            disagreements.append(
                f"{job}'s anchor spread: WP1 {value!r} against WP3 {other!r}"
            )
    for level, key in (("E8", "e8"), ("E64", "e64"), ("E128", "e128")):
        value = float(
            jobs[
                f"emissions-{'8' if level == 'E8' else '64' if level == 'E64' else '128'}"
            ]["spread"]["mean"]
        )
        other = w4_anchors.get(key.upper())
        if other is not None and abs(value - other) > FLOOR_TOLERANCE_MM_S:
            disagreements.append(
                f"{level}'s anchor spread: WP1 {value!r} against WP4 {other!r}"
            )
    if disagreements:
        raise DecisionSynthesisError(
            "the slices disagree about a floor, so no decision is published: "
            + "; ".join(disagreements)
        )

    return (
        FloorRef(
            name="between-run reference, depth-resolved",
            value_mm_s=w2_resolved,
            endpoint="depth-resolved: one per-depth difference array, or its extreme",
            source_slice="WP2",
            applies_to="every per-gate comparison in WP3 and WP4",
        ),
        FloorRef(
            name="between-run reference, depth-averaged",
            value_mm_s=w2_averaged,
            endpoint="depth-averaged: one unweighted mean over the supported gates",
            source_slice="WP2",
            applies_to="every scalar comparison, and the only endpoint like for like with WP1",
        ),
        FloorRef(
            name="burst-4 job's own anchor spread",
            value_mm_s=float(wp1_spreads["burst-4"]),
            endpoint="block-local anchor spread inside one job",
            source_slice="WP1",
            applies_to="the conservative guard on the burst-4 job's contrasts",
        ),
        FloorRef(
            name="burst-18 job's own anchor spread",
            value_mm_s=float(wp1_spreads["burst-18"]),
            endpoint="block-local anchor spread inside one job",
            source_slice="WP1",
            applies_to="the conservative guard on the burst-18 job's contrasts",
        ),
        FloorRef(
            name="emissions-8 / 64 / 128 jobs' own anchor spreads",
            value_mm_s=float(jobs["emissions-64"]["spread"]["mean"]),
            endpoint="block-local anchor spread inside one job",
            source_slice="WP1",
            applies_to="the E8, E64 and E128 rows' within-job bracketing",
        ),
    )


# ── what the slices measured, as the rows quote it ─────────────────────


def read_story(documents: dict[str, dict]) -> dict[str, object]:
    """Every number the rows quote, read from the slice that published it."""
    wp1, wp2, wp3, wp4 = (documents[key] for key in ("WP1", "WP2", "WP3", "WP4"))
    jobs = {str(job["job"]): job for job in _at(wp1, "jobs", "WP1")}
    levels = {str(level["level"]): level for level in _at(wp4, "levels", "WP4")}
    steps = _at(wp4, "steps", "WP4")
    temporal = {str(row["label"]): row for row in _at(wp4, "temporal", "WP4")}
    predictions = _at(wp4, "predictions", "WP4")
    e128 = _at(wp4, "e128_observation", "WP4")
    reading = _at(wp3, "conservative_reading", "WP3")
    runs = _at(wp2, "runs", "WP2")
    return {
        "points": int(_number(documents["WP0"], "points_rows", "WP0")),
        "window_s": _number(documents["WP0"], "views.common_window.window_s", "WP0"),
        "job_anchor_spreads": {job: float(jobs[job]["spread"]["mean"]) for job in jobs},
        "reference_runs": len(runs),
        "reference_spread": float(_at(wp2, "floor.depth_averaged.value_mm_s", "WP2")),
        "interaction_scalar": float(
            _at(wp3, "interaction.scalar_reduction_mm_s", "WP3")
        ),
        "interaction_min": float(_at(wp3, "interaction.min_mm_s", "WP3")),
        "interaction_min_depth": float(_at(wp3, "interaction.min_depth_mm", "WP3")),
        "interaction_max": float(_at(wp3, "interaction.max_mm_s", "WP3")),
        "interaction_max_depth": float(_at(wp3, "interaction.max_depth_mm", "WP3")),
        "knots": int(_at(reading, "knot_count", "WP3")),
        "knots_above_depth_resolved": int(
            _at(reading, "knots_above_depth_resolved_floor", "WP3")
        ),
        "knots_above_anchors": {
            job: int(value)
            for job, value in _at(reading, "knots_above_anchor_floor", "WP3").items()
        },
        "step_e8_e20": (
            float(steps[0]["mean_difference_min_mm_s"]),
            float(steps[0]["mean_difference_max_mm_s"]),
        ),
        "step_e20_e64": (
            float(steps[1]["mean_difference_min_mm_s"]),
            float(steps[1]["mean_difference_max_mm_s"]),
        ),
        "step_e64_e128": float(steps[2]["mean_difference_min_mm_s"]),
        "step_e20_e64_extreme": float(steps[1]["extreme_abs_mm_s"]),
        "step_e20_e64_extreme_depth": float(steps[1]["extreme_depth_mm"]),
        "stated_variation": {
            level: float(levels[level]["stated_variation_mm_s"]) for level in levels
        },
        "level_evidence": {level: str(levels[level]["evidence"]) for level in levels},
        "periods_ms": {
            level: float(temporal[label]["achieved_period_s"]) * 1e3
            for level, label in (
                ("E8", "e8"),
                ("E20", "cr1"),
                ("E64", "e64"),
                ("E128", "e128"),
            )
        },
        "rates_hz": {
            level: float(temporal[label]["profile_rate_hz"])
            for level, label in (
                ("E8", "e8"),
                ("E20", "cr1"),
                ("E64", "e64"),
                ("E128", "e128"),
            )
        },
        "nyquist_hz": {
            level: float(temporal[label]["nyquist_hz"])
            for level, label in (
                ("E8", "e8"),
                ("E20", "cr1"),
                ("E64", "e64"),
                ("E128", "e128"),
            )
        },
        "profiles_per_block": {
            level: int(temporal[label]["profiles_per_block_median"])
            for level, label in (
                ("E8", "e8"),
                ("E20", "cr1"),
                ("E64", "e64"),
                ("E128", "e128"),
            )
        },
        "block_s": float(temporal["e8"]["block_duration_s"]),
        "predicted_periods_ms": [
            float(row["expected_period_s"]) * 1e3 for row in predictions
        ],
        "measured_periods_ms": [
            float(row["measured_period_s"]) * 1e3 for row in predictions
        ],
        "intercept_ms": float(temporal["e8"]["fixed_overhead_s"]) * 1e3,
        "internal_ms": float(temporal["e8"]["internal_emission_s"]) * 1e3,
        "transfer_ms": float(temporal["e8"]["transfer_term_s"]) * 1e3,
        "e128_residual_begin": float(e128["residual_mean_vs_begin_mm_s"]),
        "e128_residual_mid": float(e128["residual_mean_vs_mid_mm_s"]),
        "e128_ratio_begin": float(e128["ratio_to_job_anchor_floor_vs_begin"]),
        "e128_ratio_mid": float(e128["ratio_to_job_anchor_floor_vs_mid"]),
        "e128_positive_vs_begin": int(e128["knots_positive_vs_begin"]),
        "e128_gates": int(e128["gates"]),
    }


def _rows(
    story: dict[str, object], floors: tuple[FloorRef, ...]
) -> tuple[DecisionRow, ...]:
    """The seven questions, each with its evidence, floor, effect, reading and verdict."""
    by_name = {floor.name: floor for floor in floors}
    averaged = by_name["between-run reference, depth-averaged"].value_mm_s
    resolved = by_name["between-run reference, depth-resolved"].value_mm_s
    b4 = by_name["burst-4 job's own anchor spread"].value_mm_s
    b18 = by_name["burst-18 job's own anchor spread"].value_mm_s
    interaction = float(story["interaction_scalar"])
    knots = int(story["knots"])
    knot_above_resolved = int(story["knots_above_depth_resolved"])
    above_anchors = story["knots_above_anchors"]
    e8_low, e8_high = story["step_e8_e20"]
    e64_low, e64_high = story["step_e20_e64"]
    e128_step = float(story["step_e64_e128"])
    spreads = story["stated_variation"]
    rates = story["rates_hz"]
    profiles = story["profiles_per_block"]

    return (
        DecisionRow(
            key="pitch_x_burst_interaction",
            question=(
                "the pitch x burst interaction (0.617 against 2.960 mm, burst 4 against 18): "
                "may its magnitude be stated, and is a denser pitch sweep justified by this pass?"
            ),
            evidence=(
                f"WP3's crossed 2x2 on {knots} common knots no finer than 2.960 mm, with each "
                f"corner sampled at its nearest native gate; WP1's per-job anchor spreads as the "
                f"within-job guard; WP2's two endpoints."
            ),
            evidence_refs=(
                "pitch-burst.json#interaction",
                "pitch-burst.json#conservative_reading",
                "anchor-floor.json#jobs",
                "reference-floor.json#floor",
            ),
            applicable_floor=(
                f"the scalar reads against WP2's depth-averaged endpoint, {averaged:.3f} mm/s, and "
                f"the conservative guard is each burst job's own anchor spread, {b4:.3f} mm/s "
                f"(burst-4) and {b18:.3f} mm/s (burst-18); the per-knot magnitudes read against the "
                f"depth-resolved endpoint, {resolved:.3f} mm/s"
            ),
            floor_mm_s=averaged,
            observed_effect=(
                f"the scalar interaction is {interaction:+.3f} mm/s, i.e. "
                f"{abs(interaction) / averaged:.2f}x the depth-averaged floor, and it stays below "
                f"both anchor guards ({b4:.3f} and {b18:.3f} mm/s); depth-resolved it reaches "
                f"{story['interaction_min']:+.3f} mm/s at {story['interaction_min_depth']:.3f} mm and "
                f"{story['interaction_max']:+.3f} mm/s at {story['interaction_max_depth']:.3f} mm, with "
                f"{knot_above_resolved} of {knots} knots above the depth-resolved floor, "
                f"{above_anchors['burst-4']} above the burst-4 guard and {above_anchors['burst-18']} "
                "above burst-18's"
            ),
            observed_effect_mm_s=interaction,
            interpretation=(
                "an interaction-shaped difference is present and is *larger* than the campaign's own "
                "between-run reference variation, but it is *smaller* than the movement of the anchors "
                "inside the two jobs it came from: the pass cannot separate its scalar magnitude from "
                "that movement, so this is a limitation of separability and NOT evidence that the "
                "interaction is absent. Locally the effect is real-shaped and changes sign across the "
                "profile, but every local extreme sits inside a job whose own anchors move by 10-12 mm/s."
            ),
            decision_class="not resolvable with this design",
            automation=(
                "none for the pitch axis as measured: the corners write only resolution and gates, and "
                "no new dialog value is needed. Shrinking the guard would need something other than an "
                "acquisition change - the anchors' movement inside a burst job is itself unexplained."
            ),
            verdict="defer",
            scope=STAGE_SCOPE,
            overturning_measurement=(
                "burst-job realizations whose own anchor spread is materially smaller than 10-12 mm/s "
                "(which is a diagnostic question about what moves inside those jobs, not a denser "
                "sweep), or a replicated interaction whose scalar magnitude exceeds the anchor guards "
                "at every realization"
            ),
        ),
        DecisionRow(
            key="e8_versus_e20",
            question="does emissions 8 lose useful estimator stability against emissions 20?",
            evidence=(
                "WP4's ladder: E8 is one scientific recording inside its job's three block-local "
                "anchors, E20 is the four common-reference runs; both are reduced on the same 12 s "
                f"window and the same {49}-gate support."
            ),
            evidence_refs=(
                "emissions-ladder.json#levels",
                "emissions-ladder.json#steps",
                "reference-floor.json#runs",
            ),
            applicable_floor=(
                f"WP2's depth-averaged endpoint, {averaged:.3f} mm/s, for the E8-to-E20 step, with E8's "
                f"own anchor spread, {spreads['E8']:.3f} mm/s, as its within-job context"
            ),
            floor_mm_s=averaged,
            observed_effect=(
                f"the E8-to-E20 depth-averaged differences span {e8_low:+.3f} to {e8_high:+.3f} mm/s "
                f"across the four E20 runs, a spread of {e8_high - e8_low:.3f} mm/s, which is the E20 "
                f"level's own run-to-run spread; E8's own anchors move by {spreads['E8']:.3f} mm/s and "
                f"its profile rate is the ladder's highest at {rates['E8']:.3f} Hz"
            ),
            observed_effect_mm_s=e8_low,
            interpretation=(
                "no stability loss is detected at the floors this pass has: every E8-to-E20 difference "
                "lies inside the E20 runs' own spread, E8's own anchors are the quietest of the three "
                "single-recording levels, and E8 carries the ladder's strongest temporal-bandwidth "
                "advantage. Not detected is not the same as absent, but nothing measured here points "
                "the other way."
            ),
            decision_class="not detected at this design's floors",
            automation="none: E8 is already writable and was written in this pass",
            verdict="keep",
            scope=STAGE_SCOPE,
            overturning_measurement=(
                "an E8-to-E20 difference outside the four-run spread at replicated realizations, or an "
                "E8 residual against its own anchors exceeding that job's own anchor spread"
            ),
        ),
        DecisionRow(
            key="e64_versus_e20",
            question="does emissions 64 improve the velocity estimate over emissions 20?",
            evidence=(
                "WP4's ladder: E64 is one scientific recording inside its job's three block-local "
                "anchors; E20 is the four common-reference runs, so the step is four run-resolved "
                "differences and no averaged E20 profile exists to take it from."
            ),
            evidence_refs=(
                "emissions-ladder.json#steps",
                "emissions-ladder.json#brackets",
                "emissions-ladder.json#levels",
            ),
            applicable_floor=(
                f"WP2's depth-averaged endpoint, {averaged:.3f} mm/s, as the between-run reference; E64's "
                f"own anchor spread, {spreads['E64']:.3f} mm/s, as its within-job context"
            ),
            floor_mm_s=averaged,
            observed_effect=(
                f"the E64-to-E20 depth-averaged differences span {e64_low:+.3f} to {e64_high:+.3f} mm/s "
                f"depending on which E20 run E64 is compared with, with a per-gate extreme of "
                f"{story['step_e20_e64_extreme']:.3f} mm/s at "
                f"{story['step_e20_e64_extreme_depth']:.3f} mm; the span straddles the "
                f"{averaged:.3f} mm/s floor"
            ),
            observed_effect_mm_s=e64_low,
            interpretation=(
                "the comparison changes classification with the reference realization: against one of the "
                "four E20 runs the difference exceeds the between-run floor and against others it does "
                "not. E64 is therefore suggestive against E20 and unresolved by this pass - it is neither "
                "shown better nor shown the same, and one realization per level is what makes that "
                "undecidable."
            ),
            decision_class="not resolvable with this design",
            automation="none: E64 is already writable and was written in this pass",
            verdict="defer",
            scope=STAGE_SCOPE,
            overturning_measurement=(
                "run-level realizations of *both* levels inside one campaign - the paired alternating "
                "set recommended below - so that the step becomes a contemporaneous four-against-four "
                "comparison carrying its own measured between-run floor, rather than new emissions-64 "
                "runs screened against an older reference"
            ),
        ),
        DecisionRow(
            key="e128_versus_e64",
            question="does emissions 128 improve the estimate enough over emissions 64 to pay its cost?",
            evidence=(
                "WP4's ladder and its temporal view measured from the stored per-profile timestamps, at "
                "the same 12 s window and support for the velocity side."
            ),
            evidence_refs=(
                "emissions-ladder.json#steps",
                "emissions-ladder.json#temporal",
                "emissions-ladder.json#predictions",
            ),
            applicable_floor=(
                f"WP2's depth-averaged endpoint, {averaged:.3f} mm/s; E128's own anchor spread, "
                f"{spreads['E128']:.3f} mm/s, as its within-job context"
            ),
            floor_mm_s=averaged,
            observed_effect=(
                f"the E64-to-E128 depth-averaged difference is {e128_step:+.3f} mm/s, inside the "
                f"{averaged:.3f} mm/s floor; meanwhile the achieved period rises from "
                f"{story['periods_ms']['E64']:.3f} to {story['periods_ms']['E128']:.3f} ms and the rate "
                f"falls from {rates['E64']:.3f} to {rates['E128']:.3f} Hz, so a fixed "
                f"{story['block_s']:g} s physical block holds {profiles['E64']} profiles at E64 against "
                f"{profiles['E128']} at E128, and the Nyquist frequency halves from "
                f"{story['nyquist_hz']['E64']:.3f} to {story['nyquist_hz']['E128']:.3f} Hz"
            ),
            observed_effect_mm_s=e128_step,
            interpretation=(
                "no depth-averaged improvement of E128 over E64 is detected - the observed difference is "
                "inside the between-run floor - while the bandwidth cost is a factor of "
                f"{story['periods_ms']['E128'] / story['periods_ms']['E64']:.2f} in period and a halving "
                "of Nyquist. The information rationale is therefore cost, not effect: no measured "
                "quantity prefers 128 over 64, so the shorter period is taken. **`replace` here means "
                "do not spend further acquisition effort on emissions 128 in this design** - it is not "
                "a claim that emissions 64 is scientifically proven superior, and a future measurement "
                "that needs the extra profiles, such as a slower flow, a noisier one or a longer "
                "coherent window, could reopen it."
            ),
            decision_class="not detected at this design's floors",
            automation="none: both levels are already writable",
            verdict="replace",
            scope=STAGE_SCOPE,
            overturning_measurement=(
                "a replicated E64-to-E128 difference outside the between-run floor, or a measurement "
                "that needs the extra profiles more than it needs the bandwidth (nothing in this pass "
                "shows such a quantity)"
            ),
        ),
        DecisionRow(
            key="prf",
            question="is there any reason from this pass to reopen the pulse repetition frequency?",
            evidence=(
                "the pass's own achieved grid: every recording's period is the emissions block at the "
                "fixed 600 us PRF plus a fixed intercept, measured at all four emissions levels"
            ),
            evidence_refs=(
                "emissions-ladder.json#temporal",
                "emissions-ladder.json#predictions",
                "qc-summary.json#observed_words",
            ),
            applicable_floor="not applicable: this row tests an identity, not an effect against a floor",
            floor_mm_s=None,
            observed_effect=(
                f"the four measured periods, {story['measured_periods_ms'][0] / 1e3:.3f} / "
                f"{story['measured_periods_ms'][1] / 1e3:.3f} / {story['measured_periods_ms'][2] / 1e3:.3f} / "
                f"{story['measured_periods_ms'][3] / 1e3:.3f} s, are predicted to within "
                f"{max(abs(a - b) for a, b in zip(story['measured_periods_ms'], story['predicted_periods_ms'])):.3f} ms "
                f"by emissions x 600 us + {story['intercept_ms']:.3f} ms, and the intercept decomposes as "
                f"{story['internal_ms']:.3f} ms of internal emission (16 PRF terms) plus "
                f"{story['transfer_ms']:.3f} ms of transfer term"
            ),
            observed_effect_mm_s=None,
            interpretation=(
                "the fixed 600 us PRF explains every achieved period in the pass, at every emissions "
                "level, with one constant intercept and no residual that varies with the level. Nothing "
                "measured here departs from it, so nothing here argues for reopening it."
            ),
            decision_class="measured and resolved",
            automation="none",
            verdict="keep",
            scope=STAGE_SCOPE,
            overturning_measurement=(
                "an achieved period that departs from the law at some level, or a measurement that needs "
                "a bandwidth the current PRF cannot deliver while keeping the emissions levels where "
                "they are"
            ),
        ),
        DecisionRow(
            key="dense_second_pass",
            question=(
                "is a dense second acquisition across the sparse matrix justified by this pass?"
            ),
            evidence=(
                "WP1 through WP4 together: the four floors this pass measured, and what each unresolved "
                "question is limited by."
            ),
            evidence_refs=(
                "anchor-floor.json#jobs",
                "reference-floor.json#floor",
                "pitch-burst.json#conservative_reading",
                "emissions-ladder.json#steps",
                "decision-table.json#campaign",
            ),
            applicable_floor=(
                f"not a single floor: the binding constraints are the burst jobs' own anchor movement "
                f"({b4:.3f} and {b18:.3f} mm/s) and the between-run floor ({averaged:.3f} mm/s "
                f"depth-averaged, {resolved:.3f} mm/s depth-resolved)"
            ),
            floor_mm_s=None,
            observed_effect=(
                f"the largest unresolved effect this pass can see is the scalar pitch x burst interaction "
                f"at {abs(interaction):.3f} mm/s, which is inside the burst jobs' own anchor movement; the "
                f"only unresolved *distinction* that additional run-level realizations can settle is "
                f"E20 against E64, whose span ({e64_low:+.3f} to {e64_high:+.3f} mm/s) straddles the "
                f"{averaged:.3f} mm/s floor"
            ),
            observed_effect_mm_s=None,
            interpretation=(
                "a dense second pass would reproduce these floors: the pitch x burst interaction is "
                "limited by movement *inside* the burst jobs, and adding more pitch or burst conditions "
                "of the same design does not shrink that. Only the E20/E64 realization dependence is "
                "bounded by the number of runs rather than by the rig, and only it is worth measuring "
                "again - as a bounded paired block inside one campaign, not a matrix."
            ),
            decision_class="not resolvable with this design",
            automation=(
                "none, and for a different reason than the pointwise surface's: the recommended block "
                "changes neither resolution nor gates - it is eight run-level jobs at the reference "
                "window's own settings - and its one varying run-wide setting is emissions per profile, "
                "which the operator sets before each job and the compile's read-back verifies. No "
                "acquisition-layer change is needed to run it."
            ),
            verdict="defer",
            scope=STAGE_SCOPE,
            overturning_measurement=(
                "a diagnostic that shows the within-job anchor movement is an artefact of the schedule "
                "rather than the rig, or a named question that the recommended targeted set does not "
                "answer"
            ),
        ),
        DecisionRow(
            key="sensitivity_d1",
            question=(
                "does the higher-sensitivity condition change the measured velocity distribution "
                "(the SNR / saturation question)?"
            ),
            evidence=(
                "not measured, and not measurable here: every committed recording carries one "
                "axial-velocity channel in mm/s, with no echo or energy profile, so no file in this pass "
                "can distinguish SNR or saturation from the flow."
            ),
            evidence_refs=("qc-summary.json#checks",),
            applicable_floor="none: there is no measurement to screen",
            floor_mm_s=None,
            observed_effect="no committed recording varies the sensitivity axis",
            observed_effect_mm_s=None,
            interpretation=(
                "this is a capability question rather than a Stage-2 acquisition: answering it needs the "
                "recording surface to carry a second (echo/energy) channel first, and until that exists "
                "no acquisition of this condition produces evidence."
            ),
            decision_class="not measured",
            automation=(
                "two gaps, and only one of them is a writer: the dialog carries sensitivity as a combo "
                "row but the acquisition bindings do not name it, and the stored file has no echo/energy "
                "channel at all"
            ),
            verdict="requires diagnostic",
            scope=OUTSIDE_SCOPE,
            overturning_measurement=(
                "the manual's own criterion: if changing sensitivity changes the measured velocity "
                "distribution, Doppler energy is insufficient - which reopens transmitted power, TGC, "
                "seeding and coupling rather than the sensitivity value"
            ),
        ),
    )


def _answers(
    story: dict[str, object], rows: tuple[DecisionRow, ...]
) -> tuple[OrderedAnswer, ...]:
    """The five questions the plan's gate requires, in its order."""
    by_key = {row.key: row for row in rows}
    averaged = float(by_key["e64_versus_e20"].floor_mm_s or 0.0)
    profiles = story["profiles_per_block"]
    return (
        OrderedAnswer(
            order=1,
            question="which axes can be collapsed or fixed?",
            answer=(
                "the emissions axis partly: E128 is replaced by E64 on cost, since no measured quantity "
                "prefers it and its period is a factor of "
                f"{story['periods_ms']['E128'] / story['periods_ms']['E64']:.2f} longer; E8 and E20 are "
                "kept, E8 having shown no stability loss and E20 being the pass's own reference. The "
                "pitch axis is not collapsed: its interaction is unresolved at this design's floors, "
                "which is a statement about separability rather than about the axis being irrelevant. "
                "The burst axis stays at the two levels the historical table already fixed (4 and 18 "
                "cycles at the reference pitch), and the new information here is that the burst jobs' "
                "own anchors move by 10-12 mm/s, which is what makes finer burst contrasts unresolvable "
                "rather than unnecessary."
            ),
            evidence_refs=(
                "pitch-burst.json#conservative_reading",
                "emissions-ladder.json#steps",
            ),
        ),
        OrderedAnswer(
            order=2,
            question="which interactions matter?",
            answer=(
                "one is estimable in this pass and it is the one the design crossed: pitch x burst. Its "
                "scalar magnitude is larger than the between-run reference variation and smaller than "
                "the movement of the anchors inside its own two jobs, so it matters as a *shape* "
                "(locally up to "
                f"{abs(float(story['interaction_max'])):.3f} mm/s and changing sign) and not as a "
                "statement of magnitude. No other interaction is estimable: the emissions ladder is one "
                "axis at one set of conditions, and the pass varies nothing else in a crossed way."
            ),
            evidence_refs=(
                "pitch-burst.json#interaction",
                "emissions-ladder.json#levels",
            ),
        ),
        OrderedAnswer(
            order=3,
            question="which levels are redundant?",
            answer=(
                f"E128 is not a level worth acquiring further: no depth-averaged improvement over E64 is "
                f"detected, and a fixed {story['block_s']:g} s block holds {profiles['E128']} profiles "
                f"against {profiles['E64']} at E64. E8 and E20 are not redundant - E8 carries the "
                "ladder's bandwidth advantage with no measured stability cost, and E20 is the only "
                "condition observed in more than one run, so it is what makes any between-run statement "
                "possible at all. The emissions levels' three block-local anchor sets are not redundant "
                "either: they are each job's own drift diagnostic and the reason every E-level "
                "comparison has a within-job context."
            ),
            evidence_refs=("emissions-ladder.json#temporal", "anchor-floor.json#jobs"),
        ),
        OrderedAnswer(
            order=4,
            question="is a denser second acquisition justified at all?",
            answer=(
                "not as a dense pass. The pitch x burst interaction is limited by the burst jobs' own "
                "anchor movement, which more points of the same design do not shrink; the emissions "
                "ladder's one unresolved distinction (E20 against E64) is limited by how many runs each "
                f"level has, and the observed difference straddles the {averaged:.3f} mm/s floor "
                "depending on which E20 run is used. Only that second limitation is worth spending "
                "recordings on, and not by acquiring emissions 64 alone: runs made in a later campaign "
                "and screened against this pass's emissions-20 runs would be separated by a campaign "
                "as well as by an emission level, and the pass has measured that between-run variation "
                "is large enough for that to enter the comparison. It takes realizations of both "
                "levels inside one campaign."
            ),
            evidence_refs=(
                "pitch-burst.json#conservative_reading",
                "emissions-ladder.json#steps",
            ),
        ),
        OrderedAnswer(
            order=5,
            question="if it is, which small set of new conditions, and what does each buy?",
            answer=(
                "eight run-level jobs in one campaign, and this is their acquisition order: "
                f"{', '.join(STAGE2_SEQUENCE)}. They are four counterbalanced pairs, so each level "
                "leads two pairs and follows in two and slow drift is sampled by both. Emissions per "
                "profile is the only setting that differs - 1.850 mm, 50 gates, burst 10, PRF 600 us, "
                "and the same power, sensitivity, TGC, first gate, sound speed and duration. They buy "
                "the one thing the ladder cannot supply: four emissions-64 and four emissions-20 "
                "observations made contemporaneously, a between-run floor measured inside that same "
                "campaign, and four adjacent paired contrasts oriented E64 minus E20. This pass's four "
                "emissions-20 runs and its existing emissions-64 recording stay as prior context; only "
                "the decisive comparison moves. Nothing else is recommended, and the acceptance "
                "criterion is stated in advance below."
            ),
            evidence_refs=(
                "emissions-ladder.json#levels",
                "decision-table.json#campaign",
            ),
        ),
    )


def _campaign(
    story: dict[str, object], rows: tuple[DecisionRow, ...]
) -> Stage2Campaign:
    averaged = float(
        next(row for row in rows if row.key == "e64_versus_e20").floor_mm_s or 0.0
    )
    low, high = story["step_e20_e64"]
    return Stage2Campaign(
        recommended=True,
        justification=(
            "the pass's floors are adequate for everything it measured except one distinction, and that "
            "one is limited by how many runs a level has rather than by the rig: the E64-to-E20 "
            f"difference spans {low:+.3f} to {high:+.3f} mm/s depending on which of the four E20 runs it "
            f"is compared with, so it straddles the {averaged:.3f} mm/s between-run floor. Acquiring "
            "emissions 64 alone would not settle it: those runs would be made in a later campaign and "
            "compared against emissions-20 runs from this one, and the between-run variation this pass "
            "measured is large enough that campaign-level drift would enter the emissions comparison. "
            "The two levels therefore have to be sampled alternately inside one campaign, so that slow "
            "drift is shared by both levels and the decisive comparison carries a floor measured in its "
            "own campaign. The existing four emissions-20 runs and the existing emissions-64 recording "
            "stay as prior context; only the decisive comparison moves to the new block."
        ),
        pair_design=(
            "The four pairs are **acquired in the order below**, and that assignment is part of the "
            "design rather than an implementation detail. Alternating the levels keeps slow drift "
            "shared, but always acquiring emissions 20 before emissions 64 would leave a "
            "short-timescale order effect - handling time, thermal or mixer evolution, settling after "
            "an emissions change, or a directional drift across adjacent jobs - confounded with the "
            "emissions contrast. The order is therefore counterbalanced: the pair is acquired "
            "E20-then-E64 in two pairs and E64-then-E20 in the other two, so each level is first twice "
            "and second twice, and an order effect of that kind shows up as pair-to-pair scatter "
            "rather than as a difference between the levels. It is one campaign block, not two "
            "interleaved campaigns: one run-plan, one manifest, one ordered sequence and one "
            "failure/resume state. The analysis publishes the four paired contrasts **individually**, "
            "each oriented as E64 minus E20 whatever order its pair was acquired in, and records that "
            "pair's acquisition orientation beside it - the orientation is retained, not discarded. "
            "The run-wide emissions value is set by the operator before each job, exactly as every "
            "job's run-wide values were set in this pass, and the compile's own fact table verifies "
            "the setting from the read-back, so no acquisition-layer change is needed."
        ),
        sequence=STAGE2_SEQUENCE,
        conditions=(
            (
                "emissions 20 at the reference spatial window: 1.850 mm, 50 gates, burst 10, PRF 600 us, "
                "and every other setting identical to this pass's reference condition - power, "
                "sensitivity, TGC, first gate, sound speed, duration - as four run-level jobs, one per "
                "block letter"
            ),
            (
                "emissions 64 at those same fixed settings - 1.850 mm, 50 gates, burst 10, PRF "
                "600 us, and the same power, sensitivity, TGC, first gate, sound speed and duration - "
                "differing from the emissions-20 jobs in emissions per profile only, as four "
                "run-level jobs alternating with them"
            ),
        ),
        recordings=8,
        buys=(
            (
                "four emissions-64 and four emissions-20 run-level observations acquired inside one "
                "campaign, which is what lets the E64-to-E20 step be compared without campaign drift "
                "entering it"
            ),
            (
                "a between-run floor measured in that same campaign, so the comparison is screened "
                "against contemporaneous run-to-run variation instead of against a floor this pass "
                "measured in an earlier session"
            ),
            (
                "four adjacent paired E64-to-E20 contrasts published individually, one per pair, each "
                "oriented E64 minus E20 with its pair's acquisition orientation recorded beside it, "
                "which makes the distinction a paired comparison rather than a difference of two group "
                "means and keeps every contrast checkable against the two jobs that produced it"
            ),
            (
                "each level's own run-to-run spread on the same footing, so a later emissions decision "
                "has two replicated levels rather than one"
            ),
        ),
        acceptance=(
            "the new campaign reports, separately: the four emissions-20 observations and the four "
            "emissions-64 observations; each level's own run-to-run spread; the four adjacent paired "
            "E64-to-E20 contrasts individually and oriented E64 minus E20, with each pair's "
            "acquisition orientation retained; the full cross-run range as context; and the "
            "depth-resolved "
            "differences against the between-run floor measured inside that campaign. The decision is "
            "then stated in one of two ways and no other. **Resolved difference:** the E64-to-E20 "
            "contrasts are consistently larger than the contemporaneous between-run variation and have "
            "a consistent direction. **Unresolved overlap:** the separation remains comparable to or "
            "smaller than the contemporaneous run-to-run variation, in which case that overlap is the "
            "answer and no further recording is indicated."
        ),
        refused=(
            (
                "an emissions-64-only acquisition screened against this pass's emissions-20 runs: the "
                "later campaign's drift would enter the comparison, which the paired design exists to "
                "prevent"
            ),
            (
                "screening the new block against this pass's 4.235 mm/s floor: the Stage-2 comparison "
                "uses the floor measured in the campaign that produced it, with this pass's floor kept "
                "as context"
            ),
            (
                "a dense second pass over the sparse matrix: the pitch x burst interaction is limited "
                "by movement inside the burst jobs, which the same design reproduces"
            ),
            (
                "any new pitch or burst condition: nothing this pass measured suggests a third level "
                "on either axis"
            ),
            (
                "the sensitivity condition (D1): the recording surface carries no echo/energy channel, "
                "so it is a capability project rather than a Stage-2 acquisition"
            ),
            (
                "reopening the pulse repetition frequency: the pass's own achieved grid matches the "
                "fixed 600 us law at every emissions level"
            ),
        ),
    )


def _checks(
    *,
    rows: tuple[DecisionRow, ...],
    floors: tuple[FloorRef, ...],
    slices: tuple[SliceRef, ...],
    answers: tuple[OrderedAnswer, ...],
    campaign: Stage2Campaign,
    story: dict[str, object],
    analysis_commit: str,
) -> dict[str, bool]:
    """The WP5 gate: what has to hold before a decision is published."""
    keys = {row.key for row in rows}
    by_key = {row.key: row for row in rows}
    return {
        "every_frozen_slice_is_cited_and_held_its_gate": all(
            ref.ok and ref.checks_passed == ref.checks_total and ref.recorded_revision
            for ref in slices
        )
        and len(slices) == len(SLICES),
        "the_floors_are_read_not_declared": all(
            floor.source_slice in {ref.name for ref in slices} for floor in floors
        )
        and all(
            any(
                abs(floor.value_mm_s - other.value_mm_s) <= FLOOR_TOLERANCE_MM_S
                for other in floors
            )
            for floor in floors
        ),
        "the_two_endpoints_are_kept_apart": (
            abs(
                next(
                    f for f in floors if f.endpoint.startswith("depth-resolved")
                ).value_mm_s
                - next(
                    f for f in floors if f.endpoint.startswith("depth-averaged")
                ).value_mm_s
            )
            > 1.0
        )
        and by_key["pitch_x_burst_interaction"].floor_mm_s
        == next(
            f for f in floors if f.endpoint.startswith("depth-averaged")
        ).value_mm_s,
        "every_verdict_is_one_of_the_plans_four": all(
            row.verdict in VERDICTS for row in rows
        ),
        "every_question_carries_its_class": all(
            row.decision_class in DECISION_CLASSES for row in rows
        ),
        "every_question_cites_a_resolvable_artefact": all(
            row.evidence_refs
            and all(
                ref.split(".json")[0] + ".json" in {Path(s.path).name for s in slices}
                or ref.startswith(DOC_NAME)
                for ref in row.evidence_refs
            )
            for row in rows
        ),
        "the_seven_questions_are_the_reviews_own": keys
        == {
            "pitch_x_burst_interaction",
            "e8_versus_e20",
            "e64_versus_e20",
            "e128_versus_e64",
            "prf",
            "dense_second_pass",
            "sensitivity_d1",
        },
        "not_detected_is_not_read_as_absent": (
            "NOT evidence that the interaction is absent"
            in by_key["pitch_x_burst_interaction"].interpretation
        )
        and any(row.decision_class == "not resolvable with this design" for row in rows)
        and any(
            row.decision_class == "not detected at this design's floors" for row in rows
        ),
        "d1_is_outside_the_stage_2_scope": (
            by_key["sensitivity_d1"].scope == OUTSIDE_SCOPE
            and by_key["sensitivity_d1"].verdict == "requires diagnostic"
        ),
        "no_dense_sweep_is_kept": by_key["dense_second_pass"].verdict != "keep",
        "both_levels_are_sampled_in_one_campaign": (
            campaign.recommended
            and campaign.recordings == 8
            and len(campaign.conditions) == 2
            and len(campaign.sequence) == campaign.recordings
            and len([name for name in campaign.sequence if name.startswith("E20")]) == 4
            and len([name for name in campaign.sequence if name.startswith("E64")]) == 4
            and all(
                {campaign.sequence[index][:3], campaign.sequence[index + 1][:3]}
                == {"E20", "E64"}
                for index in range(0, len(campaign.sequence), 2)
            )
        ),
        "the_pair_order_is_counterbalanced_and_part_of_the_design": (
            [
                campaign.sequence[index][:3]
                for index in range(0, len(campaign.sequence), 2)
            ]
            == ["E20", "E64", "E20", "E64"]
            and all(
                {campaign.sequence[index][:3], campaign.sequence[index + 1][:3]}
                == {"E20", "E64"}
                for index in range(0, len(campaign.sequence), 2)
            )
            and len(
                {
                    pair
                    for pair in zip(
                        campaign.sequence[::2], campaign.sequence[1::2], strict=True
                    )
                }
            )
            == 4
            and "counterbalanced" in campaign.pair_design
            and "part of the design" in campaign.pair_design
            and "oriented as E64 minus E20" in campaign.pair_design
            and "one campaign block, not two" in campaign.pair_design
            and "no acquisition-layer change" in campaign.pair_design
        ),
        "the_stage2_comparison_carries_its_own_floor": (
            "measured inside that campaign" in campaign.acceptance
            and "individually and oriented E64 minus E20" in campaign.acceptance
            and "consistently larger than the contemporaneous between-run variation"
            in campaign.acceptance
            and any("emissions-64-only" in text for text in campaign.refused)
            and any("4.235" in text for text in campaign.refused)
            and any("dense second pass" in text for text in campaign.refused)
        ),
        "the_fifth_answer_quotes_the_campaigns_own_sequence": (
            ", ".join(campaign.sequence) in answers[4].answer
            and [name for name in campaign.sequence if name in answers[4].answer]
            == list(campaign.sequence)
        ),
        "the_five_gate_questions_are_answered_in_order": [
            answer.order for answer in answers
        ]
        == [1, 2, 3, 4, 5],
        "the_numbers_are_the_slices_own": (
            abs(
                by_key["pitch_x_burst_interaction"].observed_effect_mm_s
                - float(story["interaction_scalar"])
            )
            < 1e-12
            and abs(
                by_key["e64_versus_e20"].observed_effect_mm_s
                - float(story["step_e20_e64"][0])
            )
            < 1e-12
            and abs(
                by_key["e128_versus_e64"].observed_effect_mm_s
                - float(story["step_e64_e128"])
            )
            < 1e-12
        ),
        "the_engine_revision_is_recorded": bool(analysis_commit),
        "the_first_answer_names_the_unresolved_axis_as_unresolved": (
            "not collapsed" in answers[0].answer and "separability" in answers[0].answer
        ),
    }


def build_decision_synthesis(
    *,
    report_dir: Path = REPORT_DIR,
    plan_path: Path | None = None,
    analysis_commit: str = "",
) -> DecisionSynthesis:
    """Read the frozen slices and synthesize the Stage-2 decision."""
    documents, refs = read_slices(Path(report_dir))
    floors = read_floors(documents)
    story = read_story(documents)
    rows = _rows(story, floors)
    plan = documents["WP0"]
    answers = _answers(story, rows)
    campaign = _campaign(story, rows)
    checks = _checks(
        rows=rows,
        floors=floors,
        slices=refs,
        answers=answers,
        campaign=campaign,
        story=story,
        analysis_commit=analysis_commit,
    )
    return DecisionSynthesis(
        dataset_root=str(plan.get("dataset_root") or DATASET_ROOT.as_posix()),
        plan=str(plan.get("plan") or ""),
        plan_path=str(plan.get("plan_path") or (plan_path or "")),
        plan_fingerprint=str(plan.get("plan_fingerprint") or ""),
        plan_doc=str(PLAN_DOC.as_posix()),
        analysis_commit=analysis_commit,
        slices=refs,
        floors=floors,
        rows=rows,
        answers=answers,
        campaign=campaign,
        story=story,
        checks=checks,
    )


# ── artefacts ──────────────────────────────────────────────────────────

CSV_COLUMNS: tuple[str, ...] = (
    "question",
    "key",
    "evidence",
    "evidence_refs",
    "applicable_floor",
    "floor_mm_s",
    "observed_effect",
    "observed_effect_mm_s",
    "interpretation",
    "decision_class",
    "automation",
    "verdict",
    "scope",
    "overturning_measurement",
)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def csv_text(model: DecisionSynthesis) -> str:
    """The machine-readable decision table."""
    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in model.rows:
        writer.writerow(_cell(getattr(row, column)) for column in CSV_COLUMNS)
    return buffer.getvalue()


def def_document(model: DecisionSynthesis) -> dict[str, object]:
    """The document beside the table: the slices, the floors, the rows and the campaign."""
    return {
        "dataset_root": model.dataset_root,
        "plan": model.plan,
        "plan_path": model.plan_path,
        "plan_fingerprint": model.plan_fingerprint,
        "plan_doc": model.plan_doc,
        "analysis_commit": model.analysis_commit,
        "table": CSV_NAME,
        "table_rows": len(model.rows),
        "slices": {
            ref.name: {
                "path": ref.path,
                "sha256": f"sha256:{ref.sha256}",
                "recorded_revision": ref.recorded_revision,
                "what_it_is": ref.what_it_is,
                "checks_passed": ref.checks_passed,
                "checks_total": ref.checks_total,
            }
            for ref in model.slices
        },
        "floors": {
            floor.name: {
                "value_mm_s": floor.value_mm_s,
                "endpoint": floor.endpoint,
                "source_slice": floor.source_slice,
                "applies_to": floor.applies_to,
            }
            for floor in model.floors
        },
        "rows": [
            {column: getattr(row, column) for column in CSV_COLUMNS}
            for row in model.rows
        ],
        "answers": [
            {
                "order": answer.order,
                "question": answer.question,
                "answer": answer.answer,
                "evidence_refs": list(answer.evidence_refs),
            }
            for answer in model.answers
        ],
        "campaign": {
            "recommended": model.campaign.recommended,
            "justification": model.campaign.justification,
            "pair_design": model.campaign.pair_design,
            "sequence": list(model.campaign.sequence),
            "conditions": list(model.campaign.conditions),
            "recordings": model.campaign.recordings,
            "buys": list(model.campaign.buys),
            "acceptance": model.campaign.acceptance,
            "refused": list(model.campaign.refused),
        },
        "definitions": {
            "decision_class": (
                "how the question stands after this pass: measured and resolved; not detected at this "
                "design's floors (a measurement was made and no effect at or above the floor was seen); "
                "not resolvable with this design (the design cannot separate the effect from the floors "
                "it is screened against, which is a limitation of the design and NOT evidence of "
                "absence); or not measured"
            ),
            "verdict": (
                "the plan's four words: keep (the pass measured what the question asked), defer "
                "(unresolved now, with the condition that would reopen it named), replace (a cost "
                "rationale for a level no measurement prefers, following the historical table's own "
                "precedent for the burst-length choice), requires diagnostic (not measurable on this "
                "surface)"
            ),
            "scope": "whether the row is part of the Stage-2 decision or outside it as its own project",
            "decision_table": (
                "seven columns comparable with the historical sweep's decision table - evidence, the "
                "floor screened against, the observed effect, the interpretation, the automation needed, "
                "the verdict and the measurement that would overturn it - plus machine fields (key, "
                "decision_class, scope, and the two numeric effect columns)"
            ),
            "no_measurement_here": (
                "this table measures nothing: every number in it is read from a frozen slice's artefact, "
                "and the synthesis refuses to publish if a slice is missing, failed its own gate or "
                "disagrees with another slice about a floor"
            ),
        },
        "checks": dict(sorted(model.checks.items())),
        "ok": model.ok,
    }


def markdown_text(model: DecisionSynthesis) -> str:
    """The decision document: the answers in the gate's order, the table and the campaign."""
    rows = []
    rows.append("# WP5 - the Stage-2 decision")
    rows.append("")
    rows.append(
        "The five measurement slices are frozen; this document decides nothing about what was "
        "measured, and everything about what may be concluded for the next acquisition. Every "
        "number below is read from a slice's own artefact (the revision and digest of each are in "
        f"`{DOC_NAME}`), and a slice that is missing, failed its own gate, or disagrees with "
        "another about a floor stops this document from being written at all."
    )
    rows.append("")
    rows.append("## The floors this decision stands on")
    rows.append("")
    rows.append("| floor | value [mm/s] | endpoint | from | applies to |")
    rows.append("|---|---|---|---|---|")
    for floor in model.floors:
        rows.append(
            f"| {floor.name} | {floor.value_mm_s:.3f} | {floor.endpoint} | {floor.source_slice} | "
            f"{floor.applies_to} |"
        )
    rows.append("")
    rows.append("## The five questions the plan's gate asks, in its order")
    rows.append("")
    for answer in model.answers:
        rows.append(f"**{answer.order}. {answer.question}**")
        rows.append("")
        rows.append(answer.answer)
        rows.append("")
    rows.append("## The decision table")
    rows.append("")
    rows.append(
        "The seven columns are the historical sweep's, so the two tables compare: the evidence, the "
        "floor the effect was screened against, the observed effect, the interpretation, the "
        "automation needed, the verdict and the measurement that would overturn it. "
        f"`{CSV_NAME}` carries the same rows plus the machine fields "
        "(`key`, `decision_class`, `scope`, and both numeric effect columns)."
    )
    rows.append("")
    for row in model.rows:
        rows.append(f"### {row.question}")
        rows.append("")
        rows.append(f"- **verdict:** `{row.verdict}` - {row.scope}")
        rows.append(f"- **decision class:** `{row.decision_class}`")
        rows.append(f"- **evidence:** {row.evidence}")
        rows.append(f"- **floor:** {row.applicable_floor}")
        rows.append(f"- **observed effect:** {row.observed_effect}")
        rows.append(f"- **interpretation:** {row.interpretation}")
        rows.append(f"- **automation needed:** {row.automation}")
        rows.append(f"- **would be overturned by:** {row.overturning_measurement}")
        rows.append("")
    rows.append("## What is recommended next, and what is refused")
    rows.append("")
    rows.append(model.campaign.justification)
    rows.append("")
    rows.append(
        "**The pairs, and why the order alternates:** " + model.campaign.pair_design
    )
    rows.append("")
    rows.append(
        "**The set, in acquisition order:** "
        + " -> ".join(f"`{name}`" for name in model.campaign.sequence)
        + f" - {model.campaign.recordings} run-level jobs, reported here as a set rather "
        "than as a schedule (the acquisition layer owns ordering, and nothing in it changes)."
    )
    rows.append("")
    rows.append("| condition | what it buys |")
    rows.append("|---|---|")
    for condition in model.campaign.conditions:
        rows.append(f"| {condition} | " + "; ".join(model.campaign.buys) + " |")
    rows.append("")
    rows.append(
        f"**Acceptance criterion, stated in advance:** {model.campaign.acceptance}"
    )
    rows.append("")
    rows.append("**Refused, on this pass's own evidence:**")
    rows.append("")
    for refusal in model.campaign.refused:
        rows.append(f"- {refusal}")
    rows.append("")
    rows.append("## What is checked before this decision is published")
    rows.append("")
    rows.append("| check | holds |")
    rows.append("|---|---|")
    for name, value in sorted(model.checks.items()):
        rows.append(f"| `{name}` | {'yes' if value else 'no'} |")
    rows.append("")
    rows.append("## Artefacts")
    rows.append("")
    rows.append("| file | what it is |")
    rows.append("|---|---|")
    rows.append(
        f"| [`{CSV_NAME}`]({CSV_NAME}) | the decision table, one row per question |"
    )
    rows.append(
        f"| [`{DOC_NAME}`]({DOC_NAME}) | the slices with their digests and revisions, the floors, the rows, the five answers, the campaign and the gate |"
    )
    rows.append("| this document | the same decision for a reader |")
    rows.append("")
    rows.append("## What is deliberately not here")
    rows.append("")
    rows.append(
        "- **No new measurement.** Nothing in this document is computed from a recording; a number that is not in a frozen slice's artefact is not in the table."
    )
    rows.append(
        "- **No statistical certainty.** The floors are observed differences over a handful of recordings, so a verdict is a decision about the next acquisition and not a test outcome."
    )
    rows.append(
        "- **No second capability project.** D1 is listed and marked outside the Stage-2 scope: the surface cannot answer it yet."
    )
    rows.append(
        "- **No broad sweep.** A dense second pass is refused here on the pass's own evidence rather than deferred for lack of time."
    )
    return "\n".join(rows) + "\n"


def write_decision_synthesis(
    report_dir: Path = REPORT_DIR,
    *,
    output_dir: Path | None = None,
    plan_path: Path | None = None,
    analysis_commit: str = "",
) -> DecisionSynthesis:
    """Build the synthesis and write its three artefacts. Refusals write nothing.

    The slices are read from ``report_dir`` and the artefacts are written to
    ``output_dir``, which defaults to the same directory - the decision table belongs
    beside the tables it reads - but may be pointed elsewhere so a synthesis can be
    published without touching the frozen report.
    """
    model = build_decision_synthesis(
        report_dir=Path(report_dir),
        plan_path=plan_path,
        analysis_commit=analysis_commit,
    )
    directory = Path(output_dir) if output_dir is not None else Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CSV_NAME).write_text(csv_text(model), encoding="utf-8", newline="")
    (directory / DOC_NAME).write_text(
        json.dumps(def_document(model), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    (directory / MD_NAME).write_text(markdown_text(model), encoding="utf-8", newline="")
    return model


def decision_main(argv: list[str] | None = None) -> int:
    """The ``sparse-decision`` command."""
    parser = argparse.ArgumentParser(
        prog="udv-sparse-decision",
        description="Synthesize the Stage-2 decision from the frozen sparse-pass slices.",
    )
    parser.add_argument("--report-dir", default=REPORT_DIR.as_posix())
    parser.add_argument(
        "--output-dir",
        default=None,
        help="where to publish; defaults to --report-dir (the artefacts belong beside "
        "the tables they read). A caller that must not touch the frozen report passes "
        "this, which is what the tests do.",
    )
    parser.add_argument("--plan-path", default=None)
    parser.add_argument("--analysis-commit", default="")
    args = parser.parse_args(argv)
    try:
        model = write_decision_synthesis(
            Path(args.report_dir),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            plan_path=Path(args.plan_path) if args.plan_path else None,
            analysis_commit=args.analysis_commit,
        )
    except DecisionSynthesisError as error:
        print(f"udv-sparse-decision: refused: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"table   : {(Path(args.report_dir) / CSV_NAME).as_posix()}")
    print(f"document: {(Path(args.report_dir) / DOC_NAME).as_posix()}")
    print(f"prose   : {(Path(args.report_dir) / MD_NAME).as_posix()}")
    verdicts = {row.verdict for row in model.rows}
    print(f"rows    : {len(model.rows)} questions, verdicts {sorted(verdicts)}")
    print(
        "next    : "
        + (
            f"{model.campaign.recordings} recordings in one campaign, both emissions levels, "
            "counterbalanced pairs"
            if model.campaign.recommended
            else "nothing recommended"
        )
    )
    print("checks  : " + ("all pass" if model.ok else "FAILED"))
    raise SystemExit(0 if model.ok else 1)
