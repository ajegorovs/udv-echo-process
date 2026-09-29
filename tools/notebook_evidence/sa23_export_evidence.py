#!/usr/bin/env python
"""Capture executed-notebook evidence for SA2.3 as a deterministic, sanitized report.

Plan ``docs/dop3000/sa2-3-notebook-preview-plan.md`` §N and merge-gate item 4 require the
executed HTML export (or an equivalent captured execution report) to be committed at a
reviewable path **outside** the frozen ``reports/`` tree, so that a reviewer without this
machine can read what the notebook actually rendered. This tool is that capture.

What it does. For each of six selections it takes the committed notebook text, applies a
small set of *exact, counted* string substitutions (the only way to drive a marimo widget's
default without editing the committed file), writes the variant to a throwaway directory,
runs a real ``marimo export html --no-include-code`` over it with the repository root as the
working directory, and then reads the rendered result back out of the exported HTML:

* a variant whose substitution did not apply exactly the expected number of times is a
  failure, never a silent no-op;
* the export must contain zero ``marimo-error`` markers and zero ``Traceback``;
* every rendered value the report quotes is asserted against the value the export actually
  carried — the axis fields (N, span, Nyquist, Δf-derived bin reasons), the gate depth, the
  detrending, the verdict, the target-support verdicts, the exact target markers drawn, and
  the backend's target reasons **quoted verbatim**.

Nothing here invents a number. A value is only ever the one the export produced.

Sanitization and determinism. The report never carries the scratch path, a host name, a
wall-clock timestamp or any part of the exported HTML — only the extracted values, the
exact substitutions, and the version pins of the environment that produced them. Two runs
in the same environment produce byte-identical output for the same notebook bytes.

Usage::

    # write the committed report
    .venv/Scripts/python.exe tools/notebook_evidence/sa23_export_evidence.py

    # reproduce and compare against the committed report; non-zero on any drift
    .venv/Scripts/python.exe tools/notebook_evidence/sa23_export_evidence.py --check
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: The repository root, from this file's own location — never a hard-coded path.
ROOT = Path(__file__).resolve().parents[2]
#: The one notebook SA2.3 extends.
NOTEBOOK = ROOT / "notebooks" / "signal_explorer.py"
#: The committed capture this tool writes and ``--check`` verifies. Outside ``reports/``.
REPORT = ROOT / "docs" / "dop3000" / "sa2-3-notebook-preview-evidence.md"


# --------------------------------------------------------------------------------------
# the variants: exact source substitutions, and the rendered values they must reproduce
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Replacement:
    """One exact substitution applied to the committed notebook text for a variant."""

    old: str
    new: str
    occurrences: int = 1


@dataclass(frozen=True)
class Variant:
    """One executed export: how its selection is driven, and what it must render."""

    slug: str
    intent: str
    replacements: tuple[Replacement, ...]
    #: ``field name -> the exact rendered value`` the export must carry.
    fields: tuple[tuple[str, str], ...]
    #: Substrings that must appear in the *unescaped* export text (attributes included).
    present: tuple[str, ...] = ()
    #: Substrings that must **not** appear anywhere in the unescaped export text.
    absent: tuple[str, ...] = ()


#: The two committed probe targets' marker annotations, as the notebook draws them:
#: ``f"{target_label} · {target_hz:g} Hz"``. The rendered figure annotation is the only
#: place this exact string appears, so it is a precise "was this marker drawn" witness.
MARK_1HZ = "recurrence-1hz · 1 Hz"
MARK_ROTOR = "rotor-8.333hz · 8.33333 Hz"

#: The backend's own above-Nyquist band reason, verbatim, for an E128 axis. Quoted, never
#: paraphrased (plan §F): the Nyquist value is that view's own characterized Nyquist.
REFUSE_E128_PRIMARY = (
    "8.33333 Hz is at or above this axis's Nyquist frequency 5.73438 Hz: "
    "band-supported requires strictly below it"
)
REFUSE_E128_FULL = (
    "8.33333 Hz is at or above this axis's Nyquist frequency 5.73436 Hz: "
    "band-supported requires strictly below it"
)

#: Reasons quoted verbatim from the default (``sparse-mixer-live-2`` / ``cr1``) axis.
REASON_CR1_1HZ = (
    "1 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 12's cell "
    "[0.95811, 1.04142] Hz"
)
REASON_CR1_ROTOR = (
    "8.33333 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 100's cell "
    "[8.28974, 8.37305] Hz"
)
#: Reasons quoted verbatim from the same recording's full-record axis (a wider span).
REASON_CR1_FULL_1HZ = (
    "1 Hz is below this axis's Nyquist frequency 22.328 Hz and inside bin 13's cell "
    "[0.996787, 1.07653] Hz"
)
REASON_CR1_FULL_ROTOR = (
    "8.33333 Hz is below this axis's Nyquist frequency 22.328 Hz and inside bin 105's cell "
    "[8.33314, 8.41288] Hz"
)
#: Reasons quoted verbatim from the E128 primary axis.
REASON_E128_PRIMARY_1HZ = (
    "1 Hz is below this axis's Nyquist frequency 5.73438 Hz and inside bin 12's cell "
    "[0.955729, 1.03884] Hz"
)
#: Reasons quoted verbatim from the E128 full-record axis.
REASON_E128_FULL_1HZ = (
    "1 Hz is below this axis's Nyquist frequency 5.73436 Hz and inside bin 13's cell "
    "[0.988682, 1.06778] Hz"
)

#: The default selection's substitutions, reused by the single-axis variants.
_JOB_EMISSIONS_128 = Replacement(
    "record.condition == _reference", 'record.job == "emissions-128"'
)
_RECORDING_E128 = Replacement(
    "value=next(iter(_options)),",
    'value=next(label for label in _options if label.startswith("e128")),',
)
_VIEW_FULL_RECORD = Replacement(
    "if view == VIEW_PRIMARY", "if view == VIEW_FULL_RECORD"
)
#: The gate control's declared default is the middle supported gate when the reader has no
#: remembered gate of their own; driving the declared default to `0` is how this capture
#: selects the shallowest supported gate (the control's own on-change memory is empty in a
#: fresh export, so the declared default is what the export renders).
_GATE_SHALLOWEST = Replacement(
    "_default = len(_labels) // 2", "_default = 0"
)
_DETREND_MEAN_LINEAR = Replacement(
    "if kind == Detrending.MEAN", "if kind == Detrending.MEAN_AND_LINEAR"
)

VARIANTS: tuple[Variant, ...] = (
    Variant(
        slug="default",
        intent=(
            "the notebook's own defaults — `sparse-mixer-live-2`, the plan's reference-condition "
            "job, the `primary-comparison` view, the middle supported gate, `mean` detrending"
        ),
        replacements=(),
        fields=(
            ("point", "cr1"),
            ("view", "primary-comparison"),
            ("gate_depth_mm", "54.538"),
            ("n_profiles", "536"),
            ("span_s", "11.9804"),
            ("nyquist_hz", "22.3281"),
            ("detrending", "mean"),
            ("verdict", "defined"),
            ("marker_caption", "recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz"),
            ("target_1hz", "supported"),
            ("target_rotor", "supported"),
        ),
        present=(
            MARK_1HZ,
            MARK_ROTOR,
            REASON_CR1_1HZ,
            REASON_CR1_ROTOR,
            "no linear trend was removed",
        ),
    ),
    Variant(
        slug="full-record",
        intent="the same selection with the view control moved to `full-record` (plan §M)",
        replacements=(_VIEW_FULL_RECORD,),
        fields=(
            ("point", "cr1"),
            ("view", "full-record"),
            ("gate_depth_mm", "54.538"),
            ("n_profiles", "560"),
            ("span_s", "12.5179"),
            ("nyquist_hz", "22.3280"),
            ("detrending", "mean"),
            ("verdict", "defined"),
            ("marker_caption", "recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz"),
            ("target_1hz", "supported"),
            ("target_rotor", "supported"),
        ),
        present=(
            MARK_1HZ,
            MARK_ROTOR,
            REASON_CR1_FULL_1HZ,
            REASON_CR1_FULL_ROTOR,
            "no linear trend was removed",
        ),
    ),
    Variant(
        slug="e128-primary",
        intent=(
            "the committed E128 real-data case — job `emissions-128`, point `e128`, "
            "`primary-comparison` view (plan §F/§K)"
        ),
        replacements=(_JOB_EMISSIONS_128, _RECORDING_E128),
        fields=(
            ("point", "e128"),
            ("view", "primary-comparison"),
            ("gate_depth_mm", "54.538"),
            ("n_profiles", "138"),
            ("span_s", "11.9455"),
            ("nyquist_hz", "5.7344"),
            ("detrending", "mean"),
            ("verdict", "defined"),
            ("marker_caption", "recurrence-1hz at 1 Hz"),
            ("target_1hz", "supported"),
            ("target_rotor", "unsupported"),
        ),
        present=(MARK_1HZ, REASON_E128_PRIMARY_1HZ, REFUSE_E128_PRIMARY),
        # §G: no 8.333 Hz vertical line inside an axis whose band ends below it.
        absent=(MARK_ROTOR,),
    ),
    Variant(
        slug="e128-full-record",
        intent="the same E128 recording with the view control moved to `full-record`",
        replacements=(_JOB_EMISSIONS_128, _RECORDING_E128, _VIEW_FULL_RECORD),
        fields=(
            ("point", "e128"),
            ("view", "full-record"),
            ("gate_depth_mm", "54.538"),
            ("n_profiles", "145"),
            ("span_s", "12.5559"),
            ("nyquist_hz", "5.7344"),
            ("detrending", "mean"),
            ("verdict", "defined"),
            ("marker_caption", "recurrence-1hz at 1 Hz"),
            ("target_1hz", "supported"),
            ("target_rotor", "unsupported"),
        ),
        present=(MARK_1HZ, REASON_E128_FULL_1HZ, REFUSE_E128_FULL),
        absent=(MARK_ROTOR,),
    ),
    Variant(
        slug="changed-gate",
        intent=(
            "the default selection with the gate control moved to the shallowest supported "
            "gate (§C/plan §K); the spectrum must name the gate it used"
        ),
        replacements=(_GATE_SHALLOWEST,),
        fields=(
            ("point", "cr1"),
            ("view", "primary-comparison"),
            ("gate_depth_mm", "10.138"),
            ("n_profiles", "536"),
            ("span_s", "11.9804"),
            ("nyquist_hz", "22.3281"),
            ("detrending", "mean"),
            ("verdict", "defined"),
            ("marker_caption", "recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz"),
            ("target_1hz", "supported"),
            ("target_rotor", "supported"),
        ),
        present=(
            MARK_1HZ,
            MARK_ROTOR,
            REASON_CR1_1HZ,
            REASON_CR1_ROTOR,
            "no linear trend was removed",
        ),
    ),
    Variant(
        slug="changed-detrending",
        intent=(
            "the default selection with the detrending control moved to `mean+linear` (§C); "
            "the spectrum must name the detrending it used and report the removed trend"
        ),
        replacements=(_DETREND_MEAN_LINEAR,),
        fields=(
            ("point", "cr1"),
            ("view", "primary-comparison"),
            ("gate_depth_mm", "54.538"),
            ("n_profiles", "536"),
            ("span_s", "11.9804"),
            ("nyquist_hz", "22.3281"),
            ("detrending", "mean+linear"),
            ("verdict", "defined"),
            ("marker_caption", "recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz"),
            ("target_1hz", "supported"),
            ("target_rotor", "supported"),
        ),
        present=(
            MARK_1HZ,
            MARK_ROTOR,
            REASON_CR1_1HZ,
            REASON_CR1_ROTOR,
            "mm/s/s removed by the estimator",
        ),
    ),
)


# --------------------------------------------------------------------------------------
# reading an exported HTML back: unescape, then extract the rendered values
# --------------------------------------------------------------------------------------

#: A marimo static export embeds each cell's rendered output as an escaped JSON string
#: (markdown) and each figure's config inside an HTML attribute. The escapes are nested, so
#: the text is unescaped repeatedly until it stops changing.
_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.DOTALL)
_SIMPLE = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "'": "'", "\\": "\\", "/": "/"}


def _unescape_repl(match: re.Match[str]) -> str:
    lexeme = match.group(1)
    if lexeme.startswith("u"):
        return chr(int(lexeme[1:], 16))
    return _SIMPLE.get(lexeme, "")


def unescape(html: str) -> str:
    """The export's text with its (nested) JS/JSON escapes resolved."""
    text = html
    for _ in range(5):
        text = _ESCAPE.sub(_unescape_repl, text)
    return text


def flatten(text: str) -> str:
    """Rendered markdown as readable text: markup stripped, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


#: The readout header: point label, the gate depth it reports, and the view label.
_HEADER = re.compile(
    r"SA2\.3 spectrum — (?P<point>\S+) · gate depth (?P<gate_depth_mm>[\d.]+) mm · "
    r"view (?P<view>[a-z-]+)"
)
#: The PSD figure title, which states the axis quantities the estimator carried.
_TITLE = re.compile(
    r"· view `(?P<view>[a-z-]+)` · N (?P<n_profiles>\d+) · span (?P<span_s>[\d.]+) s · "
    r"Nyquist (?P<nyquist_hz>[\d.]+) Hz · detrending `(?P<detrending>[a-z+]+)` · "
    r"verdict `(?P<verdict>[a-z-]+)`"
)
#: The caption that names the target markers actually drawn inside the axes.
_CAPTION = re.compile(
    r"Target markers added \(only where the backend's own "
    r"TargetFrequencySupport\.supported is true\): (?P<markers>.*?)\. "
    r"Refused targets are surfaced"
)
#: The per-target overall verdict lines.
_TARGET_1HZ = re.compile(r"recurrence-1hz — 1 Hz\s*:\s*(?P<overall>\w+) on this axis")
_TARGET_ROTOR = re.compile(
    r"rotor-8\.333hz — 8\.33333 Hz\s*:\s*(?P<overall>\w+) on this axis"
)


class EvidenceError(RuntimeError):
    """An assertion over the exported evidence failed — never a value to paper over."""


def _first(pattern: re.Pattern[str], text: str, what: str, slug: str) -> str:
    match = pattern.search(text)
    if match is None:
        raise EvidenceError(f"[{slug}] the export carries no {what}")
    return match.group(1)


def extract(html: str, slug: str) -> dict[str, str]:
    """The rendered values the report quotes, read out of one exported HTML file."""
    text = unescape(html)
    flat = flatten(text)
    header = _HEADER.search(flat)
    if header is None:
        raise EvidenceError(f"[{slug}] the export carries no SA2.3 spectrum header")
    title = _TITLE.search(text)
    if title is None:
        raise EvidenceError(f"[{slug}] the export carries no PSD figure title")
    values = dict(header.groupdict())
    values.update(title.groupdict())
    values["marker_caption"] = _first(_CAPTION, flat, "target-marker caption", slug)
    values["target_1hz"] = _first(_TARGET_1HZ, flat, "1 Hz target row", slug)
    values["target_rotor"] = _first(_TARGET_ROTOR, flat, "8.333 Hz target row", slug)
    return values


# --------------------------------------------------------------------------------------
# running one export and holding it to its contract
# --------------------------------------------------------------------------------------


@dataclass
class Captured:
    """One variant's executed export, held as the values it rendered."""

    variant: Variant
    values: dict[str, str]
    marimo_errors: int
    tracebacks: int


def _scratch_root() -> str | None:
    """The Hermes scratch directory when this host has one, else the system temp dir."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "hermes" / "cache" / "scratch"
        if candidate.is_dir():
            return str(candidate)
    return None


def _variant_source(variant: Variant, source: str) -> str:
    """Apply the variant's substitutions to the notebook text, counting each one exactly."""
    text = source
    for replacement in variant.replacements:
        found = text.count(replacement.old)
        if found != replacement.occurrences:
            raise EvidenceError(
                f"[{variant.slug}] expected {replacement.occurrences} occurrence(s) of "
                f"{replacement.old!r}, found {found}: the notebook has moved and this variant "
                "would no longer drive the selection it claims to"
            )
        if replacement.old == replacement.new:
            raise EvidenceError(
                f"[{variant.slug}] a replacement does not change the text"
            )
        text = text.replace(replacement.old, replacement.new)
    return text


def _export(variant: Variant, source: str, workdir: Path) -> str:
    """Write the variant, run a real marimo export over it, and return the exported HTML."""
    variant_py = workdir / f"variant_{variant.slug}.py"
    variant_html = workdir / f"variant_{variant.slug}.html"
    variant_py.write_text(_variant_source(variant, source), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "marimo",
        "export",
        "html",
        "--no-include-code",
        str(variant_py),
        "-o",
        str(variant_html),
        "-f",
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, cwd=str(ROOT), check=False
    )
    if completed.returncode != 0 or not variant_html.is_file():
        raise EvidenceError(
            f"[{variant.slug}] `marimo export html --no-include-code` failed "
            f"(exit {completed.returncode}):\n{completed.stdout}\n{completed.stderr}"
        )
    return variant_html.read_text(encoding="utf-8")


def capture_variant(variant: Variant, source: str, workdir: Path) -> Captured:
    """Execute one variant and hold it to every assertion its contract states."""
    html = _export(variant, source, workdir)
    text = unescape(html)

    marimo_errors = html.count("marimo-error")
    tracebacks = html.count("Traceback")
    if marimo_errors or tracebacks:
        raise EvidenceError(
            f"[{variant.slug}] the executed export carries {marimo_errors} `marimo-error` "
            f"marker(s) and {tracebacks} `Traceback`: the notebook did not run clean"
        )

    values = extract(html, variant.slug)
    for field, expected in variant.fields:
        if field not in values:
            raise EvidenceError(f"[{variant.slug}] no rendered value named {field!r}")
        if values[field] != expected:
            raise EvidenceError(
                f"[{variant.slug}] {field} rendered as {values[field]!r}, "
                f"the contract states {expected!r}"
            )
    for needle in variant.present:
        if needle not in text:
            raise EvidenceError(
                f"[{variant.slug}] the export does not carry the required text {needle!r}"
            )
    for needle in variant.absent:
        if needle in text:
            raise EvidenceError(
                f"[{variant.slug}] the export carries {needle!r}, which it must not"
            )
    return Captured(
        variant=variant,
        values=values,
        marimo_errors=marimo_errors,
        tracebacks=tracebacks,
    )


# --------------------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------------------


def _environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "marimo": importlib.metadata.version("marimo"),
        "numpy": importlib.metadata.version("numpy"),
    }


def _fmt(value: str) -> str:
    """A value for a markdown table cell, as a code span with pipes neutralised."""
    return "`" + value.replace("|", "\\|") + "`"


def render_report(captured: list[Captured], notebook_digest: str) -> str:
    """The committed capture, assembled deterministically from the executed exports."""
    environment = _environment()
    lines: list[str] = []
    add = lines.append

    add("# SA2.3 — executed-notebook export evidence")
    add("")
    add(
        "**Generated — do not edit by hand.** Plan "
        "[`sa2-3-notebook-preview-plan.md`](sa2-3-notebook-preview-plan.md) §N and merge-gate "
        "item 4 require the executed notebook pass to be committed at a reviewable path "
        "outside the frozen `reports/` tree. This document is that captured execution report: "
        "every value in it was read out of a real `marimo export html --no-include-code` run of "
        "the committed notebook. No value is transcribed, paraphrased or invented."
    )
    add("")
    add(
        f"- **Notebook under test:** `notebooks/signal_explorer.py` · sha256 `{notebook_digest}`"
    )
    add("- **Generator:** `tools/notebook_evidence/sa23_export_evidence.py`")
    add(
        "- **Write:** `.venv/Scripts/python.exe tools/notebook_evidence/sa23_export_evidence.py`"
    )
    add(
        "- **Verify:** `.venv/Scripts/python.exe tools/notebook_evidence/sa23_export_evidence.py "
        "--check` (exit 1 the moment this file and a fresh run disagree)"
    )
    add(
        f"- **Generated with:** CPython `{environment['python']}` · "
        f"marimo `{environment['marimo']}` · numpy `{environment['numpy']}`"
    )
    add("")
    add("## How the six exports are driven")
    add("")
    add(
        "A marimo widget's default cannot be set from outside the notebook, so each variant is "
        "the committed notebook text with a small set of **exact** string substitutions applied "
        "to the widget-default expressions. Every substitution's occurrence count is asserted "
        "before it is applied — a notebook that has moved fails loudly instead of silently "
        "rendering the default selection — and the variant is written to a throwaway directory. "
        "Each variant is then actually executed by"
    )
    add("")
    add("```text")
    add(
        "python -m marimo export html --no-include-code <scratch>/variant_<slug>.py"
        " -o <scratch>/variant_<slug>.html -f"
    )
    add("```")
    add("")
    add(
        "runs with the repository root as the working directory, so the committed recordings "
        "resolve exactly as they do for a normal export. Each export must carry **zero** "
        "`marimo-error` markers and **zero** `Traceback`; each rendered value below is asserted "
        "against the value the export actually carried. The exported HTML itself is never "
        "committed and never quoted here — only the values read out of it."
    )
    add("")
    add("## Variants, and the export outcome")
    add("")
    add(
        "| variant | selection | substitutions applied | `marimo-error` | `Traceback` |"
    )
    add("| --- | --- | --- | --- | --- |")
    for item in captured:
        add(
            f"| `{item.variant.slug}` | {item.variant.intent} | "
            f"{len(item.variant.replacements)} | {item.marimo_errors} | {item.tracebacks} |"
        )
    add("")
    add("## Rendered spectrum and axis values")
    add("")
    add(
        "Every cell is a value the export rendered: the header the readout states (point label, "
        "gate depth, view) and the axis quantities the PSD figure title states. The two "
        "`primary-comparison` / `full-record` pairs show N, span and Nyquist moving with the cut "
        "(plan §M); the E128 axes show the view's own Nyquist, below the 8.333 Hz rotor reference."
    )
    add("")
    add(
        "| variant | point | view | gate depth [mm] | N | span [s] | Nyquist [Hz] | "
        "detrending | verdict |"
    )
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in captured:
        v = item.values
        add(
            f"| `{item.variant.slug}` | `{v['point']}` | `{v['view']}` | "
            f"`{v['gate_depth_mm']}` | `{v['n_profiles']}` | `{v['span_s']}` | "
            f"`{v['nyquist_hz']}` | `{v['detrending']}` | `{v['verdict']}` |"
        )
    add("")
    add("## Target support, and the markers actually drawn")
    add("")
    add(
        "The overall verdict of each probe row, and the caption's own list of the target markers "
        "the export drew inside the PSD axes (plan §G: a marker is drawn only where the backend's "
        "`TargetFrequencySupport.supported` is true). For E128 the 8.333 Hz reference is refused "
        "and its marker is absent; the export carries no vertical line for it."
    )
    add("")
    add("| variant | 1 Hz row | 8.333 Hz row | markers drawn in the axes |")
    add("| --- | --- | --- | --- |")
    for item in captured:
        v = item.values
        add(
            f"| `{item.variant.slug}` | `{v['target_1hz']}` | `{v['target_rotor']}` | "
            f"`{v['marker_caption']}` |"
        )
    add("")
    add("## Target reasons, quoted verbatim from the rendered export")
    add("")
    add(
        "The binding wording rule is that an unsupported target is a statement about the axis "
        "and the window, not about the flow (plan §F/§G). The reasons below are the export's own "
        "text, asserted character for character rather than paraphrased; the 8.333 Hz reason for "
        "E128 is the backend's `TargetFrequencySupport.band_reason`, and its Nyquist value is the "
        "view's own characterized value."
    )
    add("")
    for item in captured:
        add(f"- **`{item.variant.slug}`**")
        for needle in item.variant.present:
            if "Nyquist" in needle:
                add(f"  - `{needle}`")
    add("")
    add("## Exact substitutions, per variant")
    add("")
    add(
        "The substitutions the generator asserts before applying them. A variant with no row "
        "list is the notebook's own unmodified default."
    )
    add("")
    for item in captured:
        if not item.variant.replacements:
            add(
                f"- **`{item.variant.slug}`** — no substitution (the committed default)."
            )
            continue
        add(f"- **`{item.variant.slug}`**")
        for replacement in item.variant.replacements:
            add(
                f"  - ×{replacement.occurrences} {_fmt(replacement.old)} → "
                f"{_fmt(replacement.new)}"
            )
    add("")
    add("## What the generator asserts")
    add("")
    for assertion in (
        (
            "Each variant's substitutions apply exactly the counted number of times, and change "
            "the text — a moved notebook is a failure, not a silent fall back to the default "
            "selection."
        ),
        (
            "`marimo export html --no-include-code` exits zero for every variant, and its exported "
            "HTML carries zero `marimo-error` markers and zero `Traceback`."
        ),
        (
            "Every rendered value in the tables above equals the value the export carried — point, "
            "view, gate depth, N, span, Nyquist, detrending, verdict, both target verdicts and the "
            "marker caption."
        ),
        "Every target reason quoted above appears in the export verbatim.",
        (
            "The 1 Hz marker is drawn in every variant; the 8.333 Hz marker is drawn only where "
            "the backend admits the target, and is **absent** from both E128 exports."
        ),
        "`--check` re-runs all six exports and compares this file; any drift exits non-zero.",
    ):
        add(f"- {assertion}")
    add("")
    add(
        "SA2.3 adds no new spectral estimator or scientific interpretation. This capture exposes "
        "already-reviewed backend results: `analysis.sparse_periodogram.periodogram_of_view` and "
        "`analysis.sparse_target_support.target_frequency_support`, both merged before this stage."
    )
    add("")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------


def build_report(workdir: Path) -> str:
    """Run every variant against the committed notebook and assemble the capture."""
    source = NOTEBOOK.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    captured = [capture_variant(variant, source, workdir) for variant in VARIANTS]
    return render_report(captured, digest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture SA2.3 executed-notebook export evidence."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-run the exports and compare against the committed report; non-zero on drift",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT,
        help="the report path to write or compare",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="keep the scratch variants for inspection",
    )
    args = parser.parse_args(argv)

    workdir = Path(
        tempfile.mkdtemp(prefix="sa23-export-evidence-", dir=_scratch_root())
    )
    try:
        generated = build_report(workdir)
    except EvidenceError as error:
        print(f"sa23_export_evidence: {error}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_temp:
            shutil.rmtree(workdir, ignore_errors=True)

    if args.check:
        committed = args.report.read_text(encoding="utf-8")
        if committed == generated:
            print(f"sa23_export_evidence: no drift — {args.report} matches a fresh run")
            return 0
        diff = difflib.unified_diff(
            committed.splitlines(),
            generated.splitlines(),
            fromfile=f"{args.report} (committed)",
            tofile="a fresh export run",
            lineterm="",
        )
        print("\n".join(diff), file=sys.stderr)
        print(
            f"sa23_export_evidence: drift — {args.report} is not what this notebook and "
            "environment produce now",
            file=sys.stderr,
        )
        return 1

    args.report.parent.mkdir(parents=True, exist_ok=True)
    changed = (
        not args.report.is_file()
        or args.report.read_text(encoding="utf-8") != generated
    )
    args.report.write_text(generated, encoding="utf-8", newline="\n")
    verb = "wrote" if changed else "re-wrote (unchanged)"
    print(f"sa23_export_evidence: {verb} {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
