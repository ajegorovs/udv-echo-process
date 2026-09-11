"""Stable identities: channel, quantity, source-asset and acquisition keys.

Plan §6.2. All strings are stripped and non-empty; hashes are lower-case
64-character SHA-256 hex; ids are opaque lower-case ``sha256:<hex>`` strings.
Source file names are basenames only — never machine-specific absolute paths.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import Field, ValidationInfo, field_validator, model_validator

from udv_echo_process.models._canonical import stable_id
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.io import SourceSpec

_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_SHA256_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


class ChannelKey(ValueModel):
    """Stable identity of one measurement channel (device channel number)."""

    device_channel: int = Field(ge=0)


class SignalQuantity(str, Enum):
    """What a signal measures: echo amplitude or axial velocity."""

    ECHO_AMPLITUDE = "echo_amplitude"
    AXIAL_VELOCITY = "axial_velocity"


#: Unit each signal quantity is expressed in. No implicit conversion: a
#: transform that changes units must emit a new descriptor (plan §6.2).
_QUANTITY_UNITS: dict[SignalQuantity, str] = {
    SignalQuantity.ECHO_AMPLITUDE: "module",
    SignalQuantity.AXIAL_VELOCITY: "mm/s",
}


def _strip_non_empty(value: str, *, field_name: str) -> str:
    """Strip ``value`` and reject an empty result, naming ``field_name``."""
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


class SignalDescriptor(ValueModel):
    """What a signal measures plus its unit (quantity/unit pairs are fixed)."""

    quantity: SignalQuantity
    unit: str

    @field_validator("unit")
    @classmethod
    def _strip_unit(cls, value: str, info: ValidationInfo) -> str:
        return _strip_non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _check_quantity_unit(self) -> SignalDescriptor:
        expected = _QUANTITY_UNITS[self.quantity]
        if self.unit != expected:
            raise ValueError(
                f"quantity {self.quantity.value!r} requires unit {expected!r}, "
                f"got {self.unit!r} (no implicit unit conversion)"
            )
        return self


class SourceAsset(ValueModel):
    """Identity of one source file, addressed by content, not by path."""

    asset_id: str  # "sha256:" + content_sha256
    content_sha256: str  # 64 lower-case hex
    byte_size: int = Field(ge=0)
    file_name: str  # basename only, no separators
    source: SourceSpec

    @field_validator("content_sha256")
    @classmethod
    def _check_content_sha256(cls, value: str, info: ValidationInfo) -> str:
        text = _strip_non_empty(value, field_name=info.field_name)
        if not _HEX64_RE.fullmatch(text):
            raise ValueError(
                f"{info.field_name} must be 64 lower-case hex characters, got {text!r}"
            )
        return text

    @field_validator("file_name")
    @classmethod
    def _check_basename(cls, value: str, info: ValidationInfo) -> str:
        text = _strip_non_empty(value, field_name=info.field_name)
        if "/" in text or "\\" in text:
            raise ValueError(
                f"{info.field_name} must be a basename with no path separators, "
                f"got {text!r}"
            )
        return text

    @field_validator("asset_id")
    @classmethod
    def _strip_asset_id(cls, value: str, info: ValidationInfo) -> str:
        return _strip_non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _check_asset_id_matches_content(self) -> SourceAsset:
        expected = f"sha256:{self.content_sha256}"
        if self.asset_id != expected:
            raise ValueError(
                f"asset_id must equal 'sha256:' + content_sha256 ({expected!r}), "
                f"got {self.asset_id!r}"
            )
        return self


class AcquisitionRef(ValueModel):
    """Reference to one recorded acquisition; identity survives processing."""

    recording_id: str  # stable reader-issued opaque id
    source_asset_id: str  # equals SourceAsset.asset_id in a bundle
    channel: ChannelKey

    @field_validator("recording_id", "source_asset_id")
    @classmethod
    def _check_opaque_id(cls, value: str, info: ValidationInfo) -> str:
        text = _strip_non_empty(value, field_name=info.field_name)
        if not _SHA256_ID_RE.fullmatch(text):
            raise ValueError(
                f"{info.field_name} must be an opaque lower-case "
                f"'sha256:<64 hex>' id, got {text!r}"
            )
        return text


def recording_id_for(source_asset_id: str, reader_recording_ordinal: int = 0) -> str:
    """Return the deterministic reader-issued recording id (plan §6.2).

    ``sha256(canonical_json({"source_asset_id": ..., "reader_recording_ordinal": 0}))``
    prefixed with ``sha256:``. The ordinal is reserved for future
    multi-recording containers and is ``0`` for the current DOP BDD reader.

    Args:
        source_asset_id: the owning ``SourceAsset.asset_id``.
        reader_recording_ordinal: recording index within a container, ``>= 0``.

    Returns:
        An opaque lower-case ``sha256:<hex>`` id.
    """
    if reader_recording_ordinal < 0:
        raise ValueError("reader_recording_ordinal must be >= 0")
    return stable_id(
        {
            "source_asset_id": source_asset_id,
            "reader_recording_ordinal": reader_recording_ordinal,
        }
    )
