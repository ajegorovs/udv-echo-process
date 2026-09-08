"""Enums and source descriptors for UDV measurements.

Fixed sets as ``Enum`` (per `docs/pipeline-conventions.md`):

- ``MeasType`` — what each channel measures.
- ``SourceFormat`` / ``SourceSpec`` — where the file came from. Kept as a
  first-class model so the IO layer can dispatch readers by (vendor, device,
  format) without sniffing content twice.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from udv_echo_process.models.base import Model


class MeasType(str, Enum):
    """What a channel measures: echo (amplitude) or velocity (mm/s)."""

    ECHO = "echo"
    VELOCITY = "velocity"


class SourceFormat(str, Enum):
    """File container/encoding of a source.

    ``.ADD`` (ASCII) and ``.BDD`` (binary) are both emitted by DOP-series
    instruments; a future vendor may add its own.
    """

    ADD = ".ADD"
    BDD = ".BDD"


class SourceSpec(Model):
    """Identity of where a measurement came from (value object).

    Complements, does not pretend, the raw file magic: the magic line encodes
    vendor + format (e.g. ``BINUDOPV4.03.4``), while this model stores the
    human-facing, dispatch-ready attributes.

    ``frozen=True`` makes instances hashable so ``SourceSpec`` can key the
    reader registry in ``io.base``.
    """

    model_config: ClassVar[dict[str, bool]] = {"frozen": True}

    vendor: str = "Signal Processing SA"
    device: str = "DOP 3010"
    format: SourceFormat

    def __str__(self) -> str:  # e.g. "Signal Processing SA · DOP 3010 (.BDD)"
        return f"{self.vendor} · {self.device} ({self.format.value})"
