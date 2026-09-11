"""Source — the reader registry, content sniffing, and dispatch.

Readers register themselves for a `SourceSpec`; `load()`/`read_path()` sniff a
file's bytes and dispatch to the matching reader. Adding a new format = one
`register_reader` call, never an if/elif in dispatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from udv_echo_process.models.io import SourceFormat, SourceSpec
from udv_echo_process.provenance.models import ArtifactBundle


class Reader(Protocol):
    """A per-source parser: turns a path into an ``ArtifactBundle``."""

    def read(self, path: Path) -> ArtifactBundle: ...


# Registered readers keyed by source spec.
_REGISTRY: dict[SourceSpec, Reader] = {}


def register_reader(spec: SourceSpec, reader: Reader) -> None:
    """Register a reader for a given source spec."""
    _REGISTRY[spec] = reader


def sniff(head: bytes) -> SourceSpec | None:
    """Inspect leading bytes of a file and return its SourceSpec.

    Content-based (magic), never extension-based. Returns ``None`` when the
    bytes do not match any known source.
    """
    for spec, reader in _REGISTRY.items():
        if reader_sniff(reader, head, spec.format):
            return spec
    return None


def reader_sniff(reader: Reader, head: bytes, format_: SourceFormat) -> bool:
    """Return True if ``reader`` recognises ``head`` for ``format_``.

    Uses the reader's public ``sniff()`` if present (module-level in
    ``io.dop.bdd``), else falls back to the extension.
    """
    sniff_fn = getattr(reader, "sniff", None)
    if sniff_fn is not None:
        try:
            return bool(sniff_fn(head))
        except ValueError:
            # a reader raising on a recognised-but-unsupported format is
            # still a positive detection (e.g. DOP2000)
            return True
    if format_ == SourceFormat.BDD:
        return head.startswith(b"BIN")
    return False


def read_path(path: Path) -> ArtifactBundle:
    """Sniff ``path`` and dispatch to the matching reader.

    Raises ValueError if the bytes match no known source.
    """
    head = path.read_bytes()[:128]
    spec = sniff(head)
    if spec is None:
        raise ValueError(f"no reader for {path.name} (unrecognised bytes)")
    return _REGISTRY[spec].read(path)


def load(path: Path | str) -> ArtifactBundle:
    """Load a measurement file into a validated ``ArtifactBundle``."""
    return read_path(Path(path))
