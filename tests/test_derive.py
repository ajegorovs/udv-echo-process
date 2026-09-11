"""Phase 3 derive tests: the single constructor for transformed artifacts.

Plan §8.3, §13, §14 and the Phase 3 acceptance bullet. Covers deterministic
ids, acquisition preservation, owned/unshared output arrays, resolved-default
``params_json``, warning round-trips, id sensitivity, descriptor/config
replacement, invalid-input rejection, the operation-spec registry reader path
and the forbidden-``model_copy(update=...)`` source scan.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.models import (
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    SignalData,
    SignalDescriptor,
    SignalQuantity,
    ValueModel,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.process import (
    OPERATION_SCHEMA_VERSION,
    OPERATION_SPEC_REGISTRY,
    derive,
    register_operation,
    resolve_operation_spec,
    revalidate_params,
    schema_version_for,
)
from udv_echo_process.provenance import (
    ArtifactDerivationLink,
    ChannelBundle,
    ImplementationRef,
    implementation_ref,
    operation_id_for,
    source_bundle,
)


class NoopSpec(ValueModel):
    """Minimal identity operation used to exercise ``derive`` end to end."""

    method: str = "identity"
    scale: float = 1.0
    note: str | None = None


class OtherSpec(ValueModel):
    """A differently-shaped spec, used to prove the registry type check."""

    tag: str = "other"


class RawSpec(ValueModel):
    """Spec with an unconstrained field, used to exercise JSON-safety guards."""

    value: Any = None


register_operation("test.noop", NoopSpec)
register_operation("test.scaled", NoopSpec)
register_operation("test.other", OtherSpec)
register_operation("test.raw", RawSpec)

_IMPL = implementation_ref("udv_echo_process.process.derive.derive")
_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ACQ = AcquisitionRef(
    recording_id=recording_id_for(_ASSET_ID),
    source_asset_id=_ASSET_ID,
    channel=ChannelKey(device_channel=2),
)
_DESCRIPTOR = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_CONFIG = ChannelConfig(n_gates=2, sound_speed_ms=1480.0)
_VALUES = [[1.0, 2.0], [3.0, 4.0]]
_ID_A = "sha256:" + "a" * 64
_ID_B = "sha256:" + "b" * 64

PROCESS_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "udv_echo_process" / "process"
)


def _data(values: object = None) -> SignalData:
    return observed_signal(
        [0.0, 1.0], [5.0, 10.0], _VALUES if values is None else values
    )


def _parent() -> ChannelBundle:
    return source_bundle(source_artifact(_ACQ, _DESCRIPTOR, _CONFIG, _data()))


def _fresh_data(parent: ChannelBundle) -> SignalData:
    source = parent.artifact.data
    return observed_signal(source.time_s, source.gate_depths_mm, source.values.copy())


def _derive(parent: ChannelBundle, **overrides: object) -> ChannelBundle:
    kwargs: dict[str, object] = {
        "kind": "test.noop",
        "spec": NoopSpec(),
        "implementation": _IMPL,
        "data": _fresh_data(parent),
    }
    kwargs.update(overrides)
    return derive(parent, **kwargs)  # type: ignore[arg-type]


def _signal_arrays(signal: SignalData) -> dict[str, np.ndarray]:
    arrays = {
        f"data.{name}": getattr(signal, name)
        for name in ("time_s", "gate_depths_mm", "values")
    }
    for name in ("kind", "valid", "quality"):
        arrays[f"data.support.{name}"] = getattr(signal.support, name)
    acquisition = signal.acquisition
    if acquisition is not None:
        for name in (
            "sample_id",
            "acquisition_time_s",
            "round_id",
            "visit_id",
            "profile_in_visit",
        ):
            arr = getattr(acquisition, name)
            if arr is not None:
                arrays[f"data.acquisition.{name}"] = arr
    return arrays


# ── determinism + closed bundle ────────────────────────────────────────


def test_derive_is_deterministic_for_equal_inputs():
    parent = _parent()
    first = _derive(parent)
    second = _derive(parent)
    assert first.artifact.artifact_id == second.artifact.artifact_id
    operations = (first.graph.operations[0], second.graph.operations[0])
    assert operations[0].operation_id == operations[1].operation_id
    assert operations[0].params_json == operations[1].params_json


def test_derive_returns_a_closed_bundle_with_one_graph_edge():
    parent = _parent()
    out = _derive(parent)
    assert out.graph.root_artifacts == (parent.artifact.artifact_id,)
    assert len(out.graph.operations) == 1
    operation = out.graph.operations[0]
    assert operation.parents == (parent.artifact.artifact_id,)
    assert operation.schema_version == OPERATION_SCHEMA_VERSION
    assert out.graph.derivations == (
        ArtifactDerivationLink(
            artifact_id=out.artifact.artifact_id, operation_id=operation.operation_id
        ),
    )
    assert out.artifact.artifact_id not in out.graph.root_artifacts


def test_derive_chains_and_parents_resolve_through_both_routes():
    parent = _parent()
    first = _derive(parent)
    second = _derive(first)
    assert len(second.graph.operations) == 2
    assert len(second.graph.derivations) == 2
    assert second.graph.operations[-1].parents == (first.artifact.artifact_id,)
    assert second.graph.operations[0].parents == (parent.artifact.artifact_id,)
    assert parent.artifact.artifact_id in second.graph.root_artifacts


def test_derive_preserves_acquisition_identity():
    parent = _parent()
    out = _derive(parent)
    assert out.artifact.acquisition == parent.artifact.acquisition
    assert out.artifact.acquisition.channel == ChannelKey(device_channel=2)


def test_derive_does_not_mutate_the_parent():
    parent = _parent()
    before = (
        parent.artifact.artifact_id,
        parent.graph.operations,
        parent.graph.derivations,
        parent.graph.root_artifacts,
    )
    _derive(parent)
    after = (
        parent.artifact.artifact_id,
        parent.graph.operations,
        parent.graph.derivations,
        parent.graph.root_artifacts,
    )
    assert before == after
    assert np.array_equal(parent.artifact.data.values, np.array(_VALUES))


# ── output array ownership ─────────────────────────────────────────────


def test_output_arrays_are_owned_read_only_and_share_no_memory_with_parent():
    parent = _parent()
    out = _derive(parent)
    parent_arrays = _signal_arrays(parent.artifact.data)
    output_arrays = _signal_arrays(out.artifact.data)
    for parent_name, parent_array in parent_arrays.items():
        for out_name, out_array in output_arrays.items():
            assert np.shares_memory(parent_array, out_array) is False, (
                f"{parent_name} shares memory with {out_name}"
            )
    for out_array in output_arrays.values():
        assert out_array.flags["OWNDATA"] is True
        assert out_array.flags["C_CONTIGUOUS"] is True
        assert out_array.flags["WRITEABLE"] is False
        with pytest.raises(ValueError):
            out_array[...] = out_array
    names = list(output_arrays)
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            assert (
                np.shares_memory(output_arrays[first], output_arrays[second]) is False
            )


# ── params_json ────────────────────────────────────────────────────────


def test_params_json_records_resolved_defaults_including_none():
    operation = _derive(_parent()).graph.operations[0]
    assert operation.params_json == '{"method":"identity","note":null,"scale":1.0}'


def test_params_json_is_stable_for_equal_specs():
    parent = _parent()
    defaulted = _derive(parent)
    explicit = _derive(parent, spec=NoopSpec(method="identity", scale=1.0, note=None))
    assert (
        defaulted.graph.operations[0].params_json
        == explicit.graph.operations[0].params_json
    )
    assert (
        defaulted.graph.operations[0].operation_id
        == explicit.graph.operations[0].operation_id
    )


def test_params_json_reflects_changed_values():
    parent = _parent()
    changed = _derive(parent, spec=NoopSpec(scale=2.5, note="x"))
    assert changed.graph.operations[0].params_json == (
        '{"method":"identity","note":"x","scale":2.5}'
    )


# ── warnings ───────────────────────────────────────────────────────────


def test_warning_tuples_round_trip():
    default = _derive(_parent())
    assert default.graph.operations[0].warnings == ()
    warned = _derive(_parent(), warnings=("edge_samples_reused", "2 gates unchanged"))
    assert warned.graph.operations[0].warnings == (
        "edge_samples_reused",
        "2 gates unchanged",
    )


# ── id sensitivity ─────────────────────────────────────────────────────


def test_kind_change_changes_the_operation_id():
    parent = _parent()
    first = _derive(parent, kind="test.noop")
    second = _derive(parent, kind="test.scaled")
    assert (
        first.graph.operations[0].operation_id
        != second.graph.operations[0].operation_id
    )


def test_param_change_changes_the_operation_id():
    parent = _parent()
    base = _derive(parent)
    changed = _derive(parent, spec=NoopSpec(scale=2.5))
    assert (
        base.graph.operations[0].operation_id
        != changed.graph.operations[0].operation_id
    )


def test_implementation_change_changes_the_operation_id():
    parent = _parent()
    other = ImplementationRef(
        package="udv-echo-process",
        version="0.1.0",
        callable="udv_echo_process.process.derive.derive",
        revision="deadbee",
    )
    base = _derive(parent)
    changed = _derive(parent, implementation=other)
    assert (
        base.graph.operations[0].operation_id
        != changed.graph.operations[0].operation_id
    )


def test_operation_id_is_sensitive_to_ordered_parents():
    base = operation_id_for("test.noop", 1, '{"a":1}', _IMPL, (_ID_A,))
    assert operation_id_for("test.noop", 2, '{"a":1}', _IMPL, (_ID_A,)) != base
    assert operation_id_for("test.noop", 1, '{"a":2}', _IMPL, (_ID_A,)) != base
    assert operation_id_for("test.noop", 1, '{"a":1}', _IMPL, (_ID_B,)) != base
    ordered = operation_id_for("test.noop", 1, '{"a":1}', _IMPL, (_ID_A, _ID_B))
    swapped = operation_id_for("test.noop", 1, '{"a":1}', _IMPL, (_ID_B, _ID_A))
    assert ordered != swapped


def test_one_changed_output_value_changes_the_artifact_id_only():
    parent = _parent()
    base = _derive(parent)
    changed = _derive(parent, data=_data([[1.0, 2.0], [3.0, 99.0]]))
    assert changed.artifact.artifact_id != base.artifact.artifact_id
    assert (
        changed.graph.operations[0].operation_id
        == base.graph.operations[0].operation_id
    )
    again = _derive(parent, data=_data([[1.0, 2.0], [3.0, 99.0]]))
    assert again.artifact.artifact_id == changed.artifact.artifact_id


# ── descriptor/config replacement ──────────────────────────────────────


def test_descriptor_and_config_replacement_is_recorded():
    parent = _parent()
    kept = _derive(parent)
    assert kept.artifact.descriptor == parent.artifact.descriptor
    assert kept.artifact.config == parent.artifact.config

    descriptor = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")
    config = ChannelConfig(n_gates=2, doppler_angle_deg=45.0)
    changed = _derive(parent, descriptor=descriptor, config=config)
    assert changed.artifact.descriptor == descriptor
    assert changed.artifact.config == config
    assert changed.artifact.artifact_id != kept.artifact.artifact_id
    assert changed.graph.operations[0].parents == kept.graph.operations[0].parents


# ── invalid input rejection ────────────────────────────────────────────


def test_derive_rejects_a_non_signal_payload():
    parent = _parent()
    with pytest.raises(ValidationError):
        _derive(parent, data={"values": 1})
    with pytest.raises(ValidationError):
        _derive(parent, data=object())


def test_derive_rejects_an_unregistered_kind():
    with pytest.raises(ValueError, match="no operation registered"):
        _derive(_parent(), kind="test.missing")


def test_derive_rejects_a_mismatched_spec_type():
    with pytest.raises(ValueError, match="expects spec"):
        _derive(_parent(), kind="test.other", spec=NoopSpec())


@pytest.mark.parametrize(
    "raw",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        np.arange(3),
        Path("params.npy"),
        (lambda: None),
    ],
    ids=["nan", "inf", "-inf", "ndarray", "path", "callable"],
)
def test_derive_rejects_non_json_params(raw):
    with pytest.raises(ValueError, match="derive: channel 2 operation 'test.raw'"):
        _derive(_parent(), kind="test.raw", spec=RawSpec(value=raw))


# ── registry reader path ───────────────────────────────────────────────


def test_registry_exposes_the_phase_three_schema_version():
    assert OPERATION_SCHEMA_VERSION == 1
    assert ("test.noop", OPERATION_SCHEMA_VERSION) in OPERATION_SPEC_REGISTRY
    assert schema_version_for("test.noop") == OPERATION_SCHEMA_VERSION
    assert resolve_operation_spec("test.noop", 1) is NoopSpec


def test_registry_rejects_duplicates_and_unknowns():
    with pytest.raises(ValueError, match="already registered"):
        register_operation("test.noop", NoopSpec)
    with pytest.raises(ValueError, match="no operation registered"):
        resolve_operation_spec("test.noop", 999)
    with pytest.raises(ValueError, match="no operation registered"):
        schema_version_for("test.missing")


def test_revalidate_params_round_trips_resolved_defaults():
    operation = _derive(_parent(), spec=NoopSpec(scale=3.0)).graph.operations[0]
    spec = revalidate_params(
        "test.noop", operation.schema_version, operation.params_json
    )
    assert spec == NoopSpec(scale=3.0)


@pytest.mark.parametrize("params_json", ["[]", "12", '"x"', "not json"])
def test_revalidate_params_requires_a_json_object(params_json):
    with pytest.raises((TypeError, ValueError)):
        revalidate_params("test.noop", 1, params_json)


def test_revalidate_params_rejects_an_unknown_operation():
    with pytest.raises(ValueError, match="no operation registered"):
        revalidate_params("test.missing", 1, "{}")


# ── §14 source scan ────────────────────────────────────────────────────


def _model_copy_update_lines(source: str) -> list[int]:
    """Return line numbers of ``.model_copy(update=...)`` calls in ``source``."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "model_copy" and any(
            keyword.arg == "update" for keyword in node.keywords
        ):
            hits.append(node.lineno)
    return hits


def test_source_scan_detects_model_copy_update():
    sample = "value = other.model_copy(update={'a': 1})\n"
    assert _model_copy_update_lines(sample) == [1]
    assert _model_copy_update_lines("value = other.model_copy(deep=True)\n") == []


def test_process_package_never_uses_model_copy_update():
    offenders: dict[str, list[int]] = {}
    for path in sorted(PROCESS_DIR.rglob("*.py")):
        hits = _model_copy_update_lines(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(PROCESS_DIR))] = hits
    assert offenders == {}
