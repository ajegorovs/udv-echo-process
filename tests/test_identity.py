"""Phase 1 identity-model tests: channels, quantities, assets, acquisition refs.

Locks in plan §6.2: stripped non-empty strings, lower-case SHA-256/opaque
``sha256:<hex>`` ids, basename-only file names, quantity/unit pairing with no
implicit conversion, and deterministic reader-issued recording ids.
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest
from pydantic import ValidationError

from udv_echo_process.models import (
    AcquisitionRef,
    ChannelKey,
    SignalDescriptor,
    SignalQuantity,
    SourceAsset,
    SourceFormat,
    SourceSpec,
)
from udv_echo_process.models.identity import recording_id_for

HEX64 = "a" * 64
OTHER_HEX64 = "b" * 64
ASSET_ID = "sha256:" + HEX64
ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


def _source() -> SourceSpec:
    return SourceSpec(
        vendor="Signal Processing SA", device="DOP 3010", format=SourceFormat.BDD
    )


def _asset(**overrides: object) -> SourceAsset:
    kwargs: dict[str, object] = {
        "asset_id": ASSET_ID,
        "content_sha256": HEX64,
        "byte_size": 1024,
        "file_name": "200.BDD",
        "source": _source(),
    }
    kwargs.update(overrides)
    return SourceAsset(**kwargs)


# ── ChannelKey ─────────────────────────────────────────────────────────


def test_channel_key_accepts_non_negative():
    assert ChannelKey(device_channel=0).device_channel == 0
    assert ChannelKey(device_channel=9).device_channel == 9


def test_channel_key_rejects_negative():
    with pytest.raises(ValidationError):
        ChannelKey(device_channel=-1)


def test_channel_key_is_hashable():
    assert len({ChannelKey(device_channel=1), ChannelKey(device_channel=1)}) == 1


# ── SignalQuantity / SignalDescriptor ──────────────────────────────────


def test_signal_quantity_values():
    assert SignalQuantity.ECHO_AMPLITUDE.value == "echo_amplitude"
    assert SignalQuantity.AXIAL_VELOCITY.value == "axial_velocity"
    assert isinstance(SignalQuantity.ECHO_AMPLITUDE, str)


def test_descriptor_echo_unit_is_module():
    d = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
    assert d.unit == "module"


def test_descriptor_velocity_unit_is_mm_per_s():
    d = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")
    assert d.unit == "mm/s"


@pytest.mark.parametrize(
    ("quantity", "unit"),
    [
        (SignalQuantity.ECHO_AMPLITUDE, "mm/s"),
        (SignalQuantity.AXIAL_VELOCITY, "module"),
    ],
)
def test_descriptor_rejects_quantity_unit_mismatch(quantity, unit):
    with pytest.raises(ValidationError) as ei:
        SignalDescriptor(quantity=quantity, unit=unit)
    assert "no implicit unit conversion" in str(ei.value)


def test_descriptor_rejects_empty_unit():
    with pytest.raises(ValidationError):
        SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="   ")


def test_descriptor_strips_unit():
    d = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="  mm/s ")
    assert d.unit == "mm/s"


def test_descriptor_json_round_trip():
    d = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
    assert d.model_dump(mode="json") == {
        "quantity": "echo_amplitude",
        "unit": "module",
    }
    assert SignalDescriptor.model_validate_json(d.model_dump_json()) == d


# ── SourceAsset ────────────────────────────────────────────────────────


def test_source_asset_valid_and_asset_id_equals_prefix():
    a = _asset()
    assert a.asset_id == "sha256:" + a.content_sha256
    assert a.asset_id == ASSET_ID


def test_source_asset_rejects_mismatched_asset_id():
    with pytest.raises(ValidationError):
        _asset(asset_id="sha256:" + OTHER_HEX64)


@pytest.mark.parametrize(
    "bad_sha",
    ["abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65],
    ids=["too-short", "upper-case", "non-hex", "63-hex", "65-hex"],
)
def test_source_asset_rejects_bad_content_sha256(bad_sha):
    with pytest.raises(ValidationError):
        _asset(asset_id="sha256:" + bad_sha, content_sha256=bad_sha)


def test_source_asset_rejects_negative_byte_size():
    with pytest.raises(ValidationError):
        _asset(byte_size=-1)


def test_source_asset_accepts_zero_byte_size():
    assert _asset(byte_size=0).byte_size == 0


@pytest.mark.parametrize(
    "bad_name",
    ["a/b.BDD", "/abs/x.BDD", "sub\\x.BDD", "..\\up.BDD", ""],
    ids=["posix-rel", "posix-abs", "windows-rel", "windows-up", "empty"],
)
def test_source_asset_rejects_non_basename(bad_name):
    with pytest.raises(ValidationError):
        _asset(file_name=bad_name)


def test_source_asset_accepts_plain_basename():
    assert _asset(file_name="350_v2.BDD").file_name == "350_v2.BDD"


def test_source_asset_strips_strings():
    a = _asset(content_sha256="  " + HEX64 + "  ", file_name=" 200.BDD ")
    assert a.content_sha256 == HEX64
    assert a.file_name == "200.BDD"


def test_source_asset_json_round_trip():
    a = _asset()
    dumped = a.model_dump(mode="json")
    assert dumped["asset_id"] == ASSET_ID
    assert dumped["source"]["format"] == ".BDD"
    assert SourceAsset.model_validate_json(a.model_dump_json()) == a


# ── AcquisitionRef + deterministic recording ids ───────────────────────


def test_recording_id_is_deterministic():
    assert recording_id_for(ASSET_ID) == recording_id_for(ASSET_ID)


def test_recording_id_changes_with_source_asset():
    assert recording_id_for(ASSET_ID) != recording_id_for("sha256:" + OTHER_HEX64)


def test_recording_id_changes_with_ordinal():
    assert recording_id_for(ASSET_ID, 0) != recording_id_for(ASSET_ID, 1)


def test_recording_id_matches_canonical_json_formula():
    payload = json.dumps(
        {"source_asset_id": ASSET_ID, "reader_recording_ordinal": 0},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    expected = "sha256:" + hashlib.sha256(payload).hexdigest()
    assert recording_id_for(ASSET_ID) == expected


def test_recording_id_is_opaque_lower_case_sha256():
    rid = recording_id_for(ASSET_ID)
    assert ID_RE.fullmatch(rid)


def test_acquisition_ref_valid():
    ref = AcquisitionRef(
        recording_id=recording_id_for(ASSET_ID),
        source_asset_id=ASSET_ID,
        channel=ChannelKey(device_channel=1),
    )
    assert ref.channel == ChannelKey(device_channel=1)
    assert ref.source_asset_id == ASSET_ID


@pytest.mark.parametrize(
    "bad_id",
    ["", "not-a-hash", "sha256:" + "A" * 64, "sha256:" + "a" * 63],
    ids=["empty", "no-prefix", "upper-case", "short"],
)
def test_acquisition_ref_rejects_bad_ids(bad_id):
    with pytest.raises(ValidationError):
        AcquisitionRef(
            recording_id=bad_id,
            source_asset_id=ASSET_ID,
            channel=ChannelKey(device_channel=1),
        )


def test_acquisition_ref_json_round_trip():
    ref = AcquisitionRef(
        recording_id=recording_id_for(ASSET_ID),
        source_asset_id=ASSET_ID,
        channel=ChannelKey(device_channel=2),
    )
    assert ref.model_dump(mode="json") == {
        "recording_id": recording_id_for(ASSET_ID),
        "source_asset_id": ASSET_ID,
        "channel": {"device_channel": 2},
    }
    assert AcquisitionRef.model_validate_json(ref.model_dump_json()) == ref
