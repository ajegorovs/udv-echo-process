"""Mechanical check of the R2/R9 terminology in the committed analysis text.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §8.3 item 3 rules that the
one same-settings repeat is named, everywhere and exactly, the **sole-pair
observed-discrepancy screening threshold**, and forbids every positive bound,
bounded or envelope claim about it: the retired phrases must be gone from live
text, and "above" / "below" are screening outcomes rather than bounds on drift or
proof of an axis effect. §8.4 adds the R9 half: the beginning/middle/end controls
are ``within-run reference controls`` for the single reference condition, and no
live text calls them or their adjacent differences independent.

This tool is that check. It reads text, never the numbers:

- the scope is ``src/**/*.py``, ``docs/**/*.md`` and ``reports/**/*.md``,
  excluding the vendored manual under ``docs/dop3000/manual-reference/``;
- a *positive* claim is a violation;
- an **explicit negation** of the claim ("not a bound on either", "does not bound
  repeatability", "not independent replicates") is not: the correction is
  allowed to say what the quantity is *not*;
- a **marked defect-history quotation** is exempt only through an exact
  :data:`ALLOWLIST` entry — a path and a snippet that must still be present in
  that file, so the exemption cannot outlive the text it exempts (a stale entry
  is itself a failure);
- bare ``envelope`` is *not* banned globally: the profile quantile envelope of
  ``models/profiles.py``, ``analysis/profiles.py`` and ``export.py`` is a
  different quantity and those files are exempt from that one rule (they are
  still checked for every other rule);
- the name-bearing units (the WP1/WP2 modules and the three review documents)
  must carry the canonical name, so a rename cannot be half-done.

Run it directly (exit 0 is a clean tree)::

    .venv/Scripts/python.exe tools/check_screening_terms.py
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Repository root, from this file's own location (``tools/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: The live name of the sole-pair quantity (§8.2 R2), spelled exactly.
CANONICAL_TERM = "sole-pair observed-discrepancy screening threshold"

#: The live name of the beginning/middle/end controls (§8.2 R9), spelled exactly.
CANONICAL_CONTROL_TERM = "within-run reference controls"

#: The retired phrases of §8.3 item 3 plus the superseded envelope/bound names.
RETIRED_PHRASES: tuple[str, ...] = (
    "is an upper bound",
    "as an upper bound",
    "inside the bound",
    "repeatability bound",
    "repeatability envelope",
    "observed discrepancy from the sole same-settings pair",
    "reference-repeat bound",
    "reference-repeatability bound",
    "drift-inclusive bound",
    "drift-inclusive envelope",
    "the committed wp1 envelope",
)

#: The text roots, suffixes and the one excluded vendor tree.
SCOPE_DIRS = ("src", "docs", "reports")
SCOPE_SUFFIXES = (".py", ".md")
EXCLUDED_PREFIXES = ("docs/dop3000/manual-reference/",)

#: A bound word — positive use of one of these near the quantity is a violation.
BOUND_WORD_RE = re.compile(r"\bbound(?:s|ed|ing)?\b", re.IGNORECASE)

#: The quantity's retired word. A letter before it makes it part of a compound
#: identifier with its own meaning (``RobustProfileEnvelopeError``), so it is not
#: a reference to this quantity.
ENVELOPE_WORD_RE = re.compile(r"(?<![A-Za-z])envelope", re.IGNORECASE)

#: The unambiguous markers of the sole-pair quantity. A bound word or a retired
#: phrase on a line carrying one of these is about the quantity, anywhere in the
#: tree — bare ``envelope`` and bare ``bound`` are deliberately *not* markers, so
#: the signal/statistical uses of those words stay legal.
QUANTITY_MARKER_RE = re.compile(
    r"sole-pair|same-settings|same-setting|repeatability|reference-repeat|"
    r"\bWP1\b|19\.37|max_gate_abs_mean_difference|screening threshold",
    re.IGNORECASE,
)

#: The markers for the *outcome* rule. ``WP1`` is deliberately absent: in these
#: documents it names a work package at least as often as the quantity, so an
#: outcome word beside it says nothing about which quantity is meant.
OUTCOME_CONTEXT_RE = re.compile(
    r"sole-pair|same-settings|same-setting|repeatability|19\.3701|"
    r"max_gate_abs_mean_difference|screening threshold|(?<![A-Za-z])envelope",
    re.IGNORECASE,
)

#: A manifest/hash binding: the plan rewords ``bound by SHA-256`` to ``pinned``,
#: so a bound word qualifying a manifest, hash or digest is a violation too.
MANIFEST_BINDING_RE = re.compile(
    r"\bbound\w*\s+(?:to|by)\b[^.;]{0,60}\b(?:manifest|hash|sha\w*|digest)\b"
    r"|\bmanifest-bound\b",
    re.IGNORECASE,
)

#: An above/below screening outcome: it must carry the non-causal interpretation.
OUTCOME_RE = re.compile(r"\b(?:above|below|clears|clearing|clear|exceeds)\b", re.IGNORECASE)

#: A sole observed discrepancy cannot support a statistical distinguishability
#: claim. These formulations are invalid even though they contain words such as
#: ``not`` or ``cannot``: those words negate distinguishability, not the inference.
INDISTINGUISHABILITY_CLAIM_RE = re.compile(
    r"smaller\s+than\s+this\s+bound\s+is\s+not\s+distinguishable"
    r"|below\s+the\s+threshold\s+cannot\s+be\s+distinguished\s+from\s+drift"
    r"|inside\s+the\s+threshold\s+means\s+indistinguishable",
    re.IGNORECASE,
)

TEMPORAL_FLOOR_CLAIM_RE = re.compile(
    r"\btemporal\s+floor\b|\brepeat\s+floor\b|"
    r"\bnot\s+separable\s+from\s+repeat(?:-plus-|\s+plus\s+)drift\b",
    re.IGNORECASE,
)

RESOLUTION_INTERPRETATION_RE = re.compile(
    r"\bshare\s+of\s+the\s+spatial\s+variance\b"
    r"|\bsamples?\s+(?:it\s+)?\d+(?:\.\d+)?\s+times\s+per\s+correlation\s+length\b",
    re.IGNORECASE,
)

R7_R8_TEXT_UNITS: tuple[str, ...] = (
    "src/udv_echo_process/analysis/resolution_ladder.py",
    "reports/mixer-sensitivity-analysis/README.md",
    "reports/mixer-sensitivity-analysis/decision-table.md",
    "docs/dop3000/sparse-parameter-set.md",
)

#: The framing that keeps an outcome non-causal rather than a proof or a bound.
NON_CAUSAL_RE = re.compile(
    r"screening|non-causal|not proof|not a proof|no proof|does not prove|do not prove|"
    r"neither proves|never proves|does not bound|do not bound|not a bound|not bounds|"
    r"cannot prove|does not establish",
    re.IGNORECASE,
)

#: A negation *of the claim itself*, within the clause that carries the match.
NEGATION_RE = re.compile(
    r"\b(?:not|never|neither|nor|without|cannot|doesn't|does not|do not|isn't|are not|"
    r"no longer)\b",
    re.IGNORECASE,
)

#: The statistical (quantile) envelope: a different quantity, and a different name.
STATISTICAL_ENVELOPE_MARKERS = re.compile(r"quantile|empty_envelope|EmptyEnvelope")

#: The modules that own the profile quantile envelope, exempt from the
#: bare-``envelope`` rule only — never from the rest of the check.
STATISTICAL_ENVELOPE_FILES = (
    "src/udv_echo_process/models/profiles.py",
    "src/udv_echo_process/analysis/profiles.py",
    "src/udv_echo_process/export.py",
)

#: R9: the beginning/middle/end controls are one correlated drift diagnostic.
INDEPENDENT_CONTROL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an independent reference", re.compile(r"independent references?\b", re.IGNORECASE)),
    (
        "an independent difference between controls",
        re.compile(r"independent (?:within-run )?differences?\b", re.IGNORECASE),
    ),
    ("independent observations of a control", re.compile(r"independent observations?\b", re.IGNORECASE)),
    (
        "independent recordings of the reference condition",
        re.compile(r"independent recordings?\b", re.IGNORECASE),
    ),
)

#: The live units that must carry the canonical quantity name.
R2_TEXT_UNITS: tuple[str, ...] = (
    "src/udv_echo_process/analysis/reference_repeat.py",
    "src/udv_echo_process/analysis/_native_grid.py",
    "src/udv_echo_process/analysis/resolution_ladder.py",
    "src/udv_echo_process/analysis/burst_ladder.py",
    "src/udv_echo_process/analysis/prf_ladder.py",
    "src/udv_echo_process/analysis/gain_power_screen.py",
    "src/udv_echo_process/cli.py",
    "docs/dop3000/existing-sweep-analysis-plan.md",
    "docs/dop3000/sparse-parameter-set.md",
    "reports/mixer-sensitivity-analysis/README.md",
    "reports/mixer-sensitivity-analysis/decision-table.md",
)

#: The live units that must name the controls ``within-run reference controls``.
R9_TEXT_UNITS: tuple[str, ...] = (
    "docs/dop3000/sparse-parameter-set.md",
    "reports/mixer-sensitivity-analysis/decision-table.md",
    "docs/dop3000/existing-sweep-analysis-plan.md",
)


@dataclass(frozen=True)
class AllowlistEntry:
    """One marked defect-history/historical quotation, exempt from the bans.

    ``path`` is repository-relative POSIX and ``snippet`` must be a substring of
    the exempting line. Both are checked: an entry whose snippet has gone is a
    stale exemption and fails the check, so this list can only ever shrink to the
    quotations that are still in the tree.
    """

    path: str
    snippet: str


#: The exact, marked quotations the plan exempts: §8.2's defect record, §5's
#: labelled historical commit subject, and §8.3/§8.4's own statement of the
#: retired phrases. Nothing else in the tree may use those words.
ALLOWLIST: tuple[AllowlistEntry, ...] = (
    AllowlistEntry(
        path="docs/dop3000/existing-sweep-analysis-plan.md",
        snippet="marked defect-history quotation",
    ),
    AllowlistEntry(
        path="docs/dop3000/existing-sweep-analysis-plan.md",
        snippet="matching the retired phrases",
    ),
    AllowlistEntry(
        path="docs/dop3000/existing-sweep-analysis-plan.md",
        snippet="no positive assertion uses",
    ),
    AllowlistEntry(
        path="docs/dop3000/existing-sweep-analysis-plan.md",
        snippet="historical commit subject, not a live term",
    ),
    AllowlistEntry(
        path="docs/dop3000/existing-sweep-analysis-plan.md",
        snippet="preserved here only as commit",
    ),
    AllowlistEntry(
        path="docs/dop3000/existing-sweep-analysis-plan.md",
        snippet="the retired phrases are quoted here, not used",
    ),
)


@dataclass(frozen=True)
class Violation:
    """One line that still carries a retired or positive R2/R9 claim."""

    path: str
    line: int
    rule: str
    message: str
    excerpt: str


# --------------------------------------------------------------------------- #
# scope
# --------------------------------------------------------------------------- #


def in_scope(relative: str) -> bool:
    """Is this repository-relative POSIX path inside the checked text scope?"""
    text = relative.replace("\\", "/")
    if text.startswith(EXCLUDED_PREFIXES):
        return False
    if not text.endswith(SCOPE_SUFFIXES):
        return False
    return text.split("/", 1)[0] in SCOPE_DIRS


def scope_files(root: Path = REPO) -> tuple[Path, ...]:
    """Every in-scope file under ``root``, sorted, as root-relative paths."""
    found: list[Path] = []
    for directory in SCOPE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if in_scope(relative):
                found.append(Path(relative))
    return tuple(sorted(found))


# --------------------------------------------------------------------------- #
# the rule engine
# --------------------------------------------------------------------------- #


def _negated(line: str, start: int, end: int) -> bool:
    """Is the match at ``[start, end)`` inside a clause that negates *this* claim?

    The window is the clause carrying the match (never the whole line), so a bare
    "no" elsewhere in the sentence cannot excuse a positive claim.
    """
    window_start = max(
        (line.rfind(separator, 0, start) for separator in (".", ";", ",", ":")), default=-1
    )
    window_end = min(
        (index for index in (line.find(s, end) for s in (".", ";")) if index != -1),
        default=len(line),
    )
    clause = line[window_start + 1 : window_end]
    return NEGATION_RE.search(clause) is not None


def _exempt_snippets(path: str, allowlist: tuple[AllowlistEntry, ...]) -> tuple[str, ...]:
    return tuple(entry.snippet for entry in allowlist if entry.path == path)


def scan_text(
    text: str,
    path: str,
    *,
    allowlist: tuple[AllowlistEntry, ...] = ALLOWLIST,
) -> list[Violation]:
    """Every R2/R9 violation in ``text``, read as the text of ``path``.

    ``path`` matters: the name-bearing units and the statistical-envelope files
    are treated differently from the rest, and an allowlist entry only ever
    exempts a line of its own file.
    """
    snippets = _exempt_snippets(path, allowlist)
    violations: list[Violation] = []
    lowered = text.lower()
    has_canonical = CANONICAL_TERM in lowered
    has_control_name = CANONICAL_CONTROL_TERM in lowered

    for number, line in enumerate(text.splitlines(), start=1):
        marked = any(snippet in line for snippet in snippets)
        if not marked:
            violations.extend(_scan_line(path, number, line))
        violations.extend(_scan_above_below(path, number, line))

    if path in R2_TEXT_UNITS and not has_canonical:
        violations.append(
            Violation(
                path=path,
                line=0,
                rule="r2-canonical-name",
                message=f"the quantity must be named {CANONICAL_TERM!r} in this unit",
                excerpt="",
            )
        )
    if path in R9_TEXT_UNITS and not has_control_name:
        violations.append(
            Violation(
                path=path,
                line=0,
                rule="r9-canonical-control-name",
                message=(
                    "the beginning/middle/end controls must be named "
                    f"{CANONICAL_CONTROL_TERM!r} in this unit"
                ),
                excerpt="",
            )
        )
    return violations


def _scan_line(path: str, number: int, line: str) -> list[Violation]:
    """The line rules: retired phrases, bare envelope, positive bound words, R9."""
    violations: list[Violation] = []
    lowered = line.lower()
    statistical = STATISTICAL_ENVELOPE_MARKERS.search(line) is not None
    strict = QUANTITY_MARKER_RE.search(line) is not None
    owns_quantity = path in R2_TEXT_UNITS

    if INDISTINGUISHABILITY_CLAIM_RE.search(line) is not None:
        violations.append(
            Violation(
                path=path,
                line=number,
                rule="r2-indistinguishability-claim",
                message=(
                    "one observed discrepancy is a screening reference, not evidence that an "
                    "effect is statistically indistinguishable from drift"
                ),
                excerpt=line.strip(),
            )
        )

    if TEMPORAL_FLOOR_CLAIM_RE.search(line) is not None:
        violations.append(
            Violation(
                path=path,
                line=number,
                rule="r2-temporal-floor-claim",
                message=(
                    "the sole pair supplies an observed same-settings temporal discrepancy, not "
                    "a statistical floor or separability criterion"
                ),
                excerpt=line.strip(),
            )
        )

    if path in R7_R8_TEXT_UNITS and RESOLUTION_INTERPRETATION_RE.search(line) is not None:
        violations.append(
            Violation(
                path=path,
                line=number,
                rule="r7-r8-resolution-interpretation",
                message=(
                    "name the ratio normalized reconstruction-residual variance and keep the "
                    "profile autocorrelation scale descriptive, not an adequacy criterion"
                ),
                excerpt=line.strip(),
            )
        )

    for phrase in RETIRED_PHRASES:
        start = lowered.find(phrase)
        if start == -1:
            continue
        if _negated(line, start, start + len(phrase)):
            continue
        violations.append(
            Violation(
                path=path,
                line=number,
                rule="r2-retired-phrase",
                message=f"retired phrase {phrase!r}: name the quantity {CANONICAL_TERM!r}",
                excerpt=line.strip(),
            )
        )

    # Bare ``envelope`` is the retired name of the quantity *inside the units that
    # own it*; elsewhere it keeps its signal/statistical meaning (the profile
    # quantile envelope above all), which is why it is not banned globally.
    if owns_quantity and not statistical:
        for _match in ENVELOPE_WORD_RE.finditer(line):
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r2-bare-envelope",
                    message=(
                        f"'envelope' names the quantity: use {CANONICAL_TERM!r}, unless the line "
                        "is about the profile quantile envelope"
                    ),
                    excerpt=line.strip(),
                )
            )
            break

    if (strict or MANIFEST_BINDING_RE.search(line)) and not statistical:
        for match in BOUND_WORD_RE.finditer(line):
            if _negated(line, match.start(), match.end()):
                continue
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r2-positive-bound-word",
                    message=(
                        f"positive {match.group(0)!r} claim around the quantity: it screens, it "
                        "does not bound drift (an explicit negation is the only way to keep the word)"
                    ),
                    excerpt=line.strip(),
                )
            )
            break

    for name, pattern in INDEPENDENT_CONTROL_PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        if _negated(line, match.start(), match.end()):
            continue
        if not any(
            marker in lowered
            for marker in ("control", "reference condition", "within-run", "beginning, middle")
        ):
            continue
        violations.append(
            Violation(
                path=path,
                line=number,
                rule="r9-independent-control",
                message=(
                    f"{name}: the controls are {CANONICAL_CONTROL_TERM} and their adjacent "
                    "differences are correlated"
                ),
                excerpt=line.strip(),
            )
        )
    return violations


def _scan_above_below(path: str, number: int, line: str) -> list[Violation]:
    """An above/below statement must state the non-causal screening interpretation.

    The unit of the rule is the line (a paragraph or a table row), not the clause:
    a row of numbers that says "0 of 141 knots above the threshold" carries the
    screening framing once, in the same statement, rather than in every clause.
    """
    if STATISTICAL_ENVELOPE_MARKERS.search(line) is not None:
        return []
    owns_quantity = path in R2_TEXT_UNITS and ENVELOPE_WORD_RE.search(line) is not None
    if not (owns_quantity or OUTCOME_CONTEXT_RE.search(line) is not None):
        return []
    if OUTCOME_RE.search(line) is None or NON_CAUSAL_RE.search(line) is not None:
        return []
    return [
        Violation(
            path=path,
            line=number,
            rule="r2-above-below",
            message=(
                "an above/below statement must carry the non-causal screening interpretation: "
                "it neither proves an axis effect nor bounds drift"
            ),
            excerpt=line.strip()[:200],
        )
    ]


# --------------------------------------------------------------------------- #
# the tree
# --------------------------------------------------------------------------- #


def stale_allowlist(
    root: Path = REPO, *, allowlist: tuple[AllowlistEntry, ...] = ALLOWLIST
) -> list[str]:
    """Every allowlist entry whose snippet is no longer in its file (a failure)."""
    problems: list[str] = []
    for entry in allowlist:
        path = root / entry.path
        if not path.is_file():
            problems.append(f"stale exemption: {entry.path} is missing, so {entry.snippet!r} is gone")
            continue
        if entry.snippet not in path.read_text(encoding="utf-8"):
            problems.append(
                f"stale exemption: {entry.snippet!r} is no longer in {entry.path}"
            )
    return problems


def missing_units(root: Path = REPO) -> list[str]:
    """Every declared name-bearing unit or exempt file that is not in the tree."""
    problems = []
    for relative in R2_TEXT_UNITS + R9_TEXT_UNITS + STATISTICAL_ENVELOPE_FILES:
        if not (root / relative).is_file():
            problems.append(f"missing checked unit: {relative}")
    return problems


def check_repository(root: Path = REPO) -> list[Violation]:
    """Every violation in the in-scope text of the tree, plus the stale exemptions."""
    violations: list[Violation] = []
    for path in scope_files(root):
        relative = path.as_posix()
        violations.extend(scan_text((root / path).read_text(encoding="utf-8"), relative))
    for problem in stale_allowlist(root) + missing_units(root):
        violations.append(
            Violation(path=".", line=0, rule="checker-integrity", message=problem, excerpt="")
        )
    return violations


def main(argv: list[str] | None = None) -> int:
    """Check the tree; return the exit code (0 is a clean tree)."""
    parser = argparse.ArgumentParser(
        prog="udv-check-screening-terms",
        description=(
            "Check the R2/R9 terminology of the mixer-sweep text "
            "(plan docs/dop3000/existing-sweep-analysis-plan.md §8.3 item 3, §8.4)"
        ),
    )
    parser.add_argument("--root", default=str(REPO), help="repository root to check")
    args = parser.parse_args(argv)

    root = Path(args.root)
    violations = check_repository(root)
    print(f"scope    : {', '.join(SCOPE_DIRS)} ({', '.join(SCOPE_SUFFIXES)}), excluding {EXCLUDED_PREFIXES[0]}")
    print(f"canonical: {CANONICAL_TERM}")
    print(f"controls : {CANONICAL_CONTROL_TERM}")
    print(f"exemptions: {len(ALLOWLIST)} marked quotation(s), all required to be live")
    if not violations:
        print("udv-check-screening-terms: the text names the quantity and no live claim survives")
        return 0
    for violation in violations:
        where = f"{violation.path}:{violation.line}" if violation.line else violation.path
        print(f"udv-check-screening-terms: {where}: {violation.rule}: {violation.message}", file=sys.stderr)
        if violation.excerpt:
            print(f"    {violation.excerpt}", file=sys.stderr)
    print(f"udv-check-screening-terms: {len(violations)} violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
