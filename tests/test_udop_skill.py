from __future__ import annotations

from pathlib import Path

from udv_echo_process.acquire.log import SizeSignature

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "udop-acquisition"


def _skill_text() -> str:
    files = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_udop_skill_states_current_bdd_size_law() -> None:
    text = _skill_text()
    signature = SizeSignature()

    assert signature.container_bytes == 31_268
    assert signature.block_overhead_bytes == 19
    assert signature.depth_bytes_per_gate == 2.0
    assert signature.bytes_per_gate_profile == 1.0
    assert signature.factor == 2.0
    assert "31,268 + (19 + 2 × gates) + profiles ×" in text
    assert "Profile period is computable, not measured" not in text
    assert "~1.7 bytes per" not in text


def test_udop_skill_records_completed_sparse_pass() -> None:
    text = _skill_text()

    assert "emissions × PRF + 10.369 ms" in text
    assert "Nine jobs, 26/26 points stored" in text
    assert "12.4651-12.5713 s" in text
    assert "the files were not short" in text


def test_udop_skill_is_the_instrument_overlay() -> None:
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    live_readme = (ROOT / "tools" / "live" / "README.md").read_text(encoding="utf-8")

    assert "description: Drive and verify DOP3010/UDOP acquisition runs." in skill
    assert "version: 1.2.0" in skill
    assert "related_skills: [windows-gui-automation, udv-live-gui-probe]" in skill
    assert "100,831 characters against a 100,000 cap" not in skill
    assert "Do not assume every agent shell is session 0" in live_readme
    assert "This is a runtime precondition, not a fact about Hermes" in live_readme


def test_udop_skill_support_files_resolve() -> None:
    required = [
        "references/app-lifecycle-and-state.md",
        "references/artefact-decoding.md",
        "references/control-id-mapping.md",
        "references/custom-menus-clipcursor-and-real-input.md",
        "references/dop3010-measurement-screen-surface.md",
        "references/dop3010-sweep-automation.md",
        "references/evidence-discipline.md",
        "references/live-acceptance-rehearsal.md",
        "references/live-run-bringup.md",
        "references/parameter-probing.md",
        "references/pitfalls.md",
        "references/screen-vs-api-reading.md",
        "references/win32-control-recipes.md",
        "scripts/win_attach.py",
        "scripts/win_click_probe.py",
        "scripts/win_control_io.py",
        "scripts/win_find_overlay.py",
        "scripts/win_param_scan.py",
        "scripts/win_ui_probe.py",
    ]

    missing = [path for path in required if not (SKILL / path).is_file()]
    assert not missing
