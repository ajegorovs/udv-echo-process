"""Phase 1 base-policy tests: ``ValueModel``/``ArrayModel`` and array ownership.

Locks in plan §6.1: frozen + ``extra="forbid"`` + ``validate_default`` value
bases, strict JSON round-trips, and the single shared ndarray helper that every
array field validator must call (owned, C-contiguous, read-only copy with
field-named expected-vs-actual errors).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ConfigDict, ValidationError

from udv_echo_process.models import ChannelConfig, SourceFormat, SourceSpec
from udv_echo_process.models.base import (
    ArrayModel,
    ValueModel,
    array_field,
    owned_array,
)

# ── test-local models ──────────────────────────────────────────────────


class Sample(ValueModel):
    n: int
    label: str = "ok"


class Rank2Box(ArrayModel):
    values: array_field(np.float64, rank=2, shape=(3, 2))


class VectorBox(ArrayModel):
    v: array_field(np.float64, rank=1)


class MixedBox(ArrayModel):
    channel: int
    values: array_field(np.float64, rank=2)


class BadArrayDefault(ArrayModel):
    v: array_field(np.float64, rank=1) = np.array(["nope"])


# ── base configuration ─────────────────────────────────────────────────


def test_value_model_config_is_exact():
    assert ValueModel.model_config == ConfigDict(
        frozen=True, extra="forbid", validate_default=True
    )
    assert not ValueModel.model_config.get("arbitrary_types_allowed", False)


def test_array_model_adds_arbitrary_types_and_retains_three():
    cfg = dict(ArrayModel.model_config)
    assert cfg.pop("arbitrary_types_allowed") is True
    assert cfg == dict(ConfigDict(frozen=True, extra="forbid", validate_default=True))


def test_value_model_is_frozen():
    s = Sample(n=1)
    with pytest.raises(ValidationError):
        s.n = 2


def test_array_model_is_frozen():
    box = VectorBox(v=[1.0, 2.0])
    with pytest.raises(ValidationError):
        box.v = np.array([3.0, 4.0])


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Sample(n=1, bogus="x")


def test_validate_default_catches_bad_scalar_default():
    class BadDefault(ValueModel):
        n: int = "not-an-int"

    assert BadDefault.model_fields["n"].default == "not-an-int"
    with pytest.raises(ValidationError):
        BadDefault()


def test_validate_default_catches_bad_array_default():
    assert BadArrayDefault.model_fields["v"].default is not None
    with pytest.raises(ValidationError):
        BadArrayDefault()


# ── JSON round-trips ───────────────────────────────────────────────────


def test_value_model_json_round_trip():
    s = Sample(n=3, label="gate")
    assert s.model_dump(mode="json") == {"n": 3, "label": "gate"}
    assert Sample.model_validate_json(s.model_dump_json()) == s


def test_channel_config_json_round_trip():
    c = ChannelConfig(sound_speed_ms=1460.0, n_gates=55, emit_power="high")
    dumped = c.model_dump(mode="json")
    assert dumped["sound_speed_ms"] == 1460.0
    assert dumped["n_gates"] == 55
    assert ChannelConfig.model_validate_json(c.model_dump_json()) == c
    # default-dense instance is JSON-serializable too
    assert ChannelConfig().model_dump(mode="json")["n_gates"] is None


def test_source_spec_json_round_trip():
    spec = SourceSpec(format=SourceFormat.BDD)
    assert spec.model_dump(mode="json") == {
        "vendor": "Signal Processing SA",
        "device": "DOP 3010",
        "format": ".BDD",
    }
    assert SourceSpec.model_validate_json(spec.model_dump_json()) == spec


def test_source_spec_stays_hashable_dict_key():
    a = SourceSpec(format=SourceFormat.BDD)
    b = SourceSpec(
        vendor="Signal Processing SA", device="DOP 3010", format=SourceFormat.BDD
    )
    assert a == b
    assert hash(a) == hash(b)
    assert {a: "reader"}[b] == "reader"


def test_channel_config_preserves_reader_trigger_delay():
    """Reader fixture proves ``trigger_delay_ms`` belongs on ChannelConfig.

    ``io.dop.bdd._build_config`` has always passed ``trigger_delay_ms`` from op
    word 47; the value was silently dropped while the model had no such field.
    The migrated frozen model must keep the fixture value.
    """
    from udv_echo_process.io.dop.bdd import read

    m = read(Path("data/echo/200.BDD"))
    assert m.channels[0].config.trigger_delay_ms == pytest.approx(0.0)


# ── array ownership ────────────────────────────────────────────────────


def test_array_owns_copy_from_direct_ndarray():
    caller = np.arange(6, dtype=np.float64).reshape(3, 2)
    box = Rank2Box(values=caller)
    out = box.values
    assert out.dtype == np.float64
    assert out.shape == (3, 2)
    assert out.flags["OWNDATA"] is True
    assert out.flags["C_CONTIGUOUS"] is True
    assert out.flags["WRITEABLE"] is False
    assert np.shares_memory(caller, out) is False
    caller[:] = -1.0
    assert np.array_equal(out, np.arange(6, dtype=np.float64).reshape(3, 2))


def test_array_owns_copy_from_list_like():
    caller = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    box = Rank2Box(values=caller)
    out = box.values
    assert out.flags["OWNDATA"] is True
    assert out.flags["C_CONTIGUOUS"] is True
    assert out.flags["WRITEABLE"] is False
    assert np.shares_memory(caller, out) is False
    caller[0][0] = -99.0
    assert out[0, 0] == 1.0


def test_array_converts_to_field_dtype():
    box = VectorBox(v=[1, 2, 3])
    assert box.v.dtype == np.float64
    assert box.v.flags["OWNDATA"] is True
    assert box.v.flags["WRITEABLE"] is False


def test_array_never_shares_memory_with_a_c_contiguous_float_input():
    caller = np.ascontiguousarray(np.arange(4.0))
    out = VectorBox(v=caller).v
    assert np.shares_memory(caller, out) is False


def test_non_array_fields_pass_through():
    box = MixedBox(channel=7, values=[[1.0], [2.0]])
    assert box.channel == 7
    assert box.values.shape == (2, 1)
    assert box.values.flags["WRITEABLE"] is False


# ── unsupported dtypes ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        np.array([{"a": 1}, {"a": 2}], dtype=object),
        np.array(["a", "b"], dtype="<U1"),
        np.array([(1.0, 2.0)], dtype=[("x", "<f8"), ("y", "<f8")]),
        np.array([1 + 2j, 3 + 4j], dtype=np.complex128),
    ],
    ids=["object", "str", "structured", "complex"],
)
def test_unsupported_dtype_rejected(bad):
    with pytest.raises(ValidationError) as ei:
        VectorBox(v=bad)
    assert "'v'" in str(ei.value)


def test_list_of_strings_rejected():
    with pytest.raises(ValidationError):
        VectorBox(v=["a", "b"])


# ── error text ─────────────────────────────────────────────────────────


def test_error_names_field_and_expected_vs_actual_dtype_shape():
    with pytest.raises(ValidationError) as ei:
        Rank2Box(values=np.zeros((4, 2), dtype=np.int32))
    msg = str(ei.value)
    assert "'values'" in msg
    assert "float64" in msg  # expected dtype
    assert "int32" in msg  # actual dtype
    assert "rank 2" in msg
    assert "(3, 2)" in msg  # expected shape
    assert "(4, 2)" in msg  # actual shape


def test_error_reports_rank_mismatch():
    with pytest.raises(ValidationError) as ei:
        Rank2Box(values=np.zeros(3, dtype=np.float64))
    msg = str(ei.value)
    assert "'values'" in msg
    assert "rank 2" in msg  # expected rank
    assert "rank 1" in msg  # actual rank


def test_error_reports_shape_mismatch_for_matching_dtype_rank():
    with pytest.raises(ValidationError) as ei:
        Rank2Box(values=np.zeros((3, 3), dtype=np.float64))
    msg = str(ei.value)
    assert "(3, 2)" in msg and "(3, 3)" in msg


def test_error_never_prints_full_array_payload():
    """The helper's own message reports metadata only, never element values."""
    payload = np.full((2, 2), 424242, dtype=np.int32)
    with pytest.raises(ValueError) as ei:
        owned_array(
            payload, field_name="values", dtype=np.float64, rank=2, shape=(3, 2)
        )
    msg = str(ei.value)
    assert "424242" not in msg  # no element payload leaked
    assert len(msg) < 200  # bounded: metadata, not a dump
    assert "int32" in msg and "(2, 2)" in msg and "(3, 2)" in msg
