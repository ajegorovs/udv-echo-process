"""Data-source (IO) layer — where measurements come from.

The IO layer owns source *discovery* and *per-source parsing*; each reader ends
in the same canonical model (`provenance.ArtifactBundle` — a `Recording` plus
the provenance graph that resolves every one of its channel artifacts).
Discovery and dispatch **sniff content** (magic bytes), not extensions — a
misnamed file is rejected by its bytes, and a `.BDD` that is really a PNG (a
documented trap in this repo's fixtures) is caught here.
"""

from __future__ import annotations

from pathlib import Path

from udv_echo_process.io.base import Reader, load, read_path, register_reader, sniff
from udv_echo_process.io.dop import bdd as _dop_bdd  # noqa: F401 (registers reader)
from udv_echo_process.provenance.models import ArtifactBundle

__all__ = [
    "ArtifactBundle",
    "Reader",
    "discover_data_files",
    "load",
    "read_path",
    "register_reader",
    "sniff",
]


def discover_data_files(data_root: str | Path = "data") -> list[Path]:
    """Find valid measurement files under ``data_root`` (recursive).

    A file is "valid" when ``sniff()`` recognises its content (magic, not
    extension), so misnamed images and unknown formats are skipped. Scans
    every file under each immediate subdirectory of ``data_root`` (the
    per-experiment layout). Best-effort: unreadable files are skipped.
    """
    root = Path(data_root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            try:
                head = p.read_bytes()[:128]
                if sniff(head) is not None:
                    found.append(p)
            except OSError:
                pass
    return found
