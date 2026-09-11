"""Tests for the models layer — the authoritative type contracts.

Phase 9 (compatibility retirement) re-expressed the legacy ``ChannelSeries`` /
``MultiplexedMeasurement`` contract on the landed model: the per-channel unit is
now the :class:`ChannelArtifact` (its payload an immutable :class:`SignalData`)
composed into the recording-level :class:`Recording`, and ``select_channel`` is
the bridge from a recording to one channel. The retired types were **removed**,
not adapted (plan Phase 9, §5). Per-component invariants live in their focused
suites (``test_signal_data.py``, ``test_recording.py``, ``test_support.py``,
``test_identity.py``); this file locks the models layer's own contract — the
``__all__`` surface, the one-way import rule, the payload/artifact shape-time
contract, the source/config descriptors and the recording composition.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process import models
from udv_echo_process.models import (
    AcquisitionMode,
    AcquisitionRef,
    ChannelArtifact,
    ChannelConfig,
    ChannelKey,
    Recording,
    SignalDescriptor,
    SignalQuantity,
    SourceAsset,
    SourceFormat,
    SourceSpec,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_MODELS_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "udv_echo_process" / "models"
)


def _imported_modules(tree: ast.AST) -> list[str]:
    """Every module named by a ``import``/``from ... import`` in ``tree``."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
    return modules


def make_artifact(
    channel: int = 4, t: np.ndarray | None = None, gates: int = 2
) -> ChannelArtifact:
    """Build a small, valid source ``ChannelArtifact`` for reuse (3 × gates)."""
    t = np.array([0.0, 0.1, 0.2]) if t is None else t
    data = observed_signal(
        t, np.arange(gates, dtype=float), np.full((len(t), gates), 1.0)
    )
    ref = AcquisitionRef(
        recording_id=recording_id_for(_ASSET_ID),
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    return source_artifact(ref, _ECHO, ChannelConfig(), data)


def _asset() -> SourceAsset:
    return SourceAsset(
        asset_id=_ASSET_ID,
        content_sha256=_HEX,
        byte_size=10,
        file_name="200.BDD",
        source=SourceSpec(format=SourceFormat.BDD),
    )


# ── models-layer surface & dependency rule ──────────────────────────────


class TestModelsSurface:
    def test_models_all_resolves(self):
        for name in models.__all__:
            assert hasattr(models, name), f"missing models export: {name}"

    def test_models_layer_imports_nothing_from_upper_layers(self):
        # models/ is the bottom of the import graph (plan §12.8): it must import
        # only from udv_echo_process.models, never io/process/analysis/viz/
        # provenance/storage. Docstring references to those packages are fine;
        # this inspects the real import statements.
        for path in sorted(_MODELS_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module in _imported_modules(tree):
                if not module.startswith("udv_echo_process."):
                    continue
                parts = module.split(".")
                assert parts[1] == "models", (
                    f"{path.name} imports {module!r}; models/ must depend on "
                    "nothing above it (plan §12.8)"
                )


# ── SignalData / ChannelArtifact contracts ──────────────────────────────


class TestArtifactContracts:
    def test_valid_source_artifact_round_trips(self):
        art = make_artifact()
        assert art.acquisition.channel.device_channel == 4
        assert art.descriptor == _ECHO
        assert art.data.time_s.shape == (3,)
        assert art.data.values.shape == (3, 2)
        assert art.data.values.flags["WRITEABLE"] is False

    def test_values_shape_mismatch_rejected(self):
        # values (3, 1) but two gate depths
        with pytest.raises(ValidationError, match="shape"):
            observed_signal(
                np.array([0.0, 0.1, 0.2]),
                np.array([1.0, 2.0]),
                np.zeros((3, 1)),
            )

    def test_non_increasing_time_rejected(self):
        with pytest.raises(ValidationError, match="strictly increasing"):
            observed_signal(
                np.array([0.0, 0.3, 0.1]),
                np.array([1.0, 2.0]),
                np.ones((3, 2)),
            )

    def test_non_finite_time_rejected(self):
        with pytest.raises(ValidationError, match="finite"):
            observed_signal(
                np.array([0.0, np.nan, 0.2]),
                np.array([1.0, 2.0]),
                np.ones((3, 2)),
            )

    def test_channel_artifact_rejects_a_malformed_artifact_id(self):
        art = make_artifact()
        with pytest.raises(ValidationError, match="artifact_id"):
            ChannelArtifact(
                artifact_id="not-an-opaque-id",
                acquisition=art.acquisition,
                descriptor=art.descriptor,
                config=art.config,
                data=art.data,
            )

    def test_channel_config_defaults_dense_and_broad(self):
        c = ChannelConfig()
        assert c.sound_speed_ms is None
        assert c.n_gates is None
        assert len(ChannelConfig.model_fields) > 5  # acous/gate/physics/tgc charset


# ── source descriptors ──────────────────────────────────────────────────


class TestDescriptors:
    def test_source_spec_defaults_and_str(self):
        spec = SourceSpec(format=SourceFormat.BDD)
        assert spec.format == SourceFormat.BDD
        assert "DOP 3010" in str(spec)

    def test_source_asset_is_a_basename_with_a_content_id(self):
        assert _asset().file_name == "200.BDD"
        assert _asset().asset_id == "sha256:" + _asset().content_sha256


# ── recording composition ───────────────────────────────────────────────


class TestRecordingComposition:
    def test_recording_preserves_stream_order(self):
        recording = Recording(
            recording_id=recording_id_for(_ASSET_ID),
            source_asset=_asset(),
            acquisition_mode=AcquisitionMode.UNKNOWN,
            streams=tuple(make_artifact(channel=c) for c in (6, 7, 8)),
        )
        assert [s.acquisition.channel.device_channel for s in recording.streams] == [
            6,
            7,
            8,
        ]

    def test_recording_requires_at_least_one_stream(self):
        with pytest.raises(ValidationError, match="at least one"):
            Recording(
                recording_id=recording_id_for(_ASSET_ID),
                source_asset=_asset(),
                acquisition_mode=AcquisitionMode.UNKNOWN,
                streams=(),
            )
