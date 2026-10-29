"""Address-free finite orchestration over an explicitly supplied machine backend.

The backend owns fresh target admission and each guarded phase, not this module.
Its phase methods may reuse the proven native implementation unchanged. This
coordinator owns order, terminal failures, independent BDD verification and close
before restoration. A backend is trusted executable code, not a security sandbox.
No backend is bundled or selected implicitly, and no frequency-equality rule is
imposed. Offline verification of this layer is not live acceptance of a provider.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field, model_validator

from udv_echo_process.acquire.cycle import _name_problem
from udv_echo_process.acquire.finite import (
    RUN_COMMAND,
    FiniteRunReceipt,
    FiniteRunRequest,
)
from udv_echo_process.io.dop.bdd import read
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.identity import SignalQuantity


class FiniteChannel(ValueModel):
    """One requested stream; frequency is per channel, never a pair-wide rule."""

    channel: int = Field(strict=True, ge=1, le=10)
    quantity: SignalQuantity = SignalQuantity.AXIAL_VELOCITY
    frequency_khz: int = Field(strict=True, gt=0)
    profiles: int = Field(strict=True, gt=0)
    gates: int = Field(strict=True, gt=0)
    prf_us: int = Field(strict=True, gt=0)
    emissions: int = Field(strict=True, gt=0)


class FiniteInvocation(ValueModel):
    """Declared finite request, validated before any backend is constructed.

    This promotion is one sequence only. Provider capability/admission may be
    narrower still. The deadlines retain the reviewed bounded prototype limits;
    expiry is never a hardware abort.
    """

    name: str
    store_directory: Path
    expect_mode: str = Field(pattern="^(instrument|simulation)$")
    channels: tuple[FiniteChannel, ...] = Field(min_length=1)
    sequences: int = Field(default=1, strict=True, ge=1, le=1)
    observe_timeout_s: float = Field(
        default=25.0, strict=True, gt=0, le=60, allow_inf_nan=False
    )
    poll_s: float = Field(default=0.2, strict=True, gt=0, le=1, allow_inf_nan=False)
    attachment_window_s: float = Field(
        default=4.0, strict=True, ge=2, le=30, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def _declared(self) -> FiniteInvocation:
        problem = _name_problem(self.name)
        if problem:
            raise ValueError(problem)
        keys = [(c.channel, c.quantity.value) for c in self.channels]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate channel/quantity request")
        if self.poll_s > self.observe_timeout_s:
            raise ValueError("poll_s exceeds observation deadline")
        return self


class FiniteBackend(Protocol):
    """Private phase engine, with no Record, Stop, Clear or retry operation.

    Construction and static preflight must not attach or mutate the target.
    prepare reads the actual process mode and baseline, resolves every forward
    and restore operation; each subsequent phase rechecks identity/state before
    its own effects. observe uses classify_finite_run on fresh observations and
    owns its bounded wait. close is idempotent and retains actual receipts.
    The backend attributes run tokens/identity; matching claims are consistency
    checks, not independent proof that a token belongs to this hardware run.
    """

    def prepare(self) -> dict: ...
    def configure(self) -> list[dict]: ...
    def enable(self) -> tuple[FiniteRunRequest, FiniteRunReceipt, dict]: ...
    def observe(self, request: FiniteRunRequest, receipt: FiniteRunReceipt) -> dict: ...
    def store(self) -> dict: ...
    def close(self) -> dict: ...
    def restore(self) -> list[dict]: ...
    def verify(self) -> dict: ...
    def residual(self) -> dict: ...
    def source_evidence(self) -> dict: ...


VERIFICATION_KEYS = frozenset(
    {
        "controls_restored",
        "multiplexing_disabled",
        "participants_restored",
        "trigger_unchanged",
        "same_identity",
        "ready_pending_zero_no_error",
        "all_ten_tgc_unchanged",
        "only_cached_words_differ",
    }
)


def invocation_problem(request: FiniteInvocation) -> str | None:
    """Static file admission; no provider import, directory creation or target read."""
    if not request.store_directory.is_dir():
        return "finite_store_directory_missing"
    if (request.store_directory / (request.name + ".BDD")).exists():
        return "finite_name_taken"
    for path in request.store_directory.iterdir():
        if path.is_file() and path.name.lower().startswith(request.name.lower()):
            return "finite_name_taken"
    return None


def _clean_close(value: dict) -> bool:
    sessions = value.get("sessions")
    count = value.get("sessions_opened")
    return (
        value.get("ok") is True
        and type(count) is int
        and count > 0
        and isinstance(sessions, list)
        and len(sessions) == count
        and all(
            isinstance(s, dict)
            and s.get("closed") is True
            and s.get("close_problem") is None
            and s.get("receipt_ok") is True
            and type(s.get("helper_exit")) is int
            and s["helper_exit"] == 0
            and type(s.get("attach_exit")) is int
            and s["attach_exit"] == 0
            for s in sessions
        )
    )


def _close(backend: FiniteBackend) -> dict:
    try:
        value = backend.close()
        return (
            value
            if isinstance(value, dict)
            else {"ok": False, "reason": "finite_close_malformed"}
        )
    except Exception as exc:  # noqa: BLE001 - preserve partial outcomes at backend boundaries
        return {
            "ok": False,
            "reason": f"finite_close_failed:{type(exc).__name__}:{exc}",
        }


def _artifact(request: FiniteInvocation, stored: dict) -> dict:
    path = Path(stored["path"])
    target = request.store_directory / (request.name + ".BDD")
    if path.resolve() != target.resolve() or not path.is_file():
        raise ValueError("finite_stored_path_mismatch")
    bundle = read(path)
    digest = bundle.recording.source_asset.content_sha256
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("finite_stored_digest_changed_after_decode")
    if "sha256" in stored and stored["sha256"] != digest:
        raise ValueError("finite_store_digest_claim_mismatch")
    streams = bundle.recording.streams
    expected = {(c.channel, c.quantity.value): c for c in request.channels}
    observed = {
        (s.acquisition.channel.device_channel, s.descriptor.quantity.value): s
        for s in streams
    }
    if set(observed) != set(expected) or len(streams) != len(expected):
        raise ValueError("finite_stored_streams_mismatch")
    facts = []
    for key, specification in expected.items():
        stream = observed[key]
        if stream.data.values.shape != (specification.profiles, specification.gates):
            raise ValueError(f"finite_stored_shape_mismatch:{key}")
        config = stream.config
        if (
            config.source_freq_khz != specification.frequency_khz
            or config.emissions_per_profile != specification.emissions
            or not math.isclose(
                config.pulse_repetition_freq_hz,
                1_000_000 / specification.prf_us,
                rel_tol=1e-12,
            )
            or not stream.data.support.valid.all()
        ):
            raise ValueError(f"finite_stored_configuration_mismatch:{key}")
        facts.append(
            {
                "channel": key[0],
                "quantity": key[1],
                "shape": list(stream.data.values.shape),
            }
        )
    return {
        "path": str(path),
        "sha256": digest,
        "recording_id": bundle.recording.recording_id,
        "streams": len(streams),
        "facts": facts,
    }


def run_finite(request: FiniteInvocation, backend: FiniteBackend) -> dict[str, Any]:
    """Execute one terminal phase chain; never apply a speculative recovery tail.

    Backend observations are trusted claims, independently checked against the
    declaration and decoded file where possible. A failed close blocks further
    mutation. Every post-configuration failure carries fresh residual state or
    an explicit failed read; a timeout is reported, never treated as an abort.
    """
    report: dict[str, Any] = {
        "ok": False,
        "outcome": "refused",
        "request": request.model_dump(mode="json"),
        "restoration_owed": False,
    }
    mutated = restored = False
    try:
        problem = invocation_problem(request)
        if problem:
            raise ValueError(problem)
        report["baseline"] = backend.prepare()
        if report["baseline"].get("process_mode") != request.expect_mode:
            raise ValueError("finite_process_mode_mismatch_or_missing")
        mutated = True  # attempted, not a claim that any particular write completed
        report["configuration_attempted"] = True
        report["configure"] = backend.configure()
        report["run_attempted"] = True
        declared, receipt, evidence = backend.enable()
        declared = FiniteRunRequest.model_validate(declared)
        receipt = FiniteRunReceipt.model_validate(receipt)
        if (
            declared.channels != tuple(sorted({c.channel for c in request.channels}))
            or declared.sequences != request.sequences
            or receipt.run_token != declared.run_token
            or receipt.invocations != 1
            or receipt.pending_after_run != RUN_COMMAND
            or not receipt.identity
            or receipt.record_dispatches != 0
            or receipt.stop_dispatches != 0
        ):
            raise ValueError("finite_run_receipt_or_request_mismatch")
        report.update(run_evidence=evidence, receipt=receipt.model_dump(mode="json"))
        observation = backend.observe(declared, receipt)
        report["observe"] = {k: v for k, v in observation.items() if k != "snapshot"}
        if observation.get("outcome") != "completed":
            report["outcome"] = str(
                observation.get("outcome") or "finite_observation_refused"
            )
        else:
            report["store_attempted"] = True
            report["store"] = backend.store()
            if report["store"].get("ok") is not True:
                raise ValueError("finite_store_refused")
            report["artifact"] = _artifact(request, report["store"])
            report["store_closeout"] = _close(backend)
            if not _clean_close(report["store_closeout"]):
                raise ValueError("finite_store_closeout_failed")
            report["restore"] = backend.restore()
            report["verification"] = backend.verify()
            checks = report["verification"].get("checks") or {}
            if not VERIFICATION_KEYS.issubset(checks) or not all(
                v is True for v in checks.values()
            ):
                raise ValueError("finite_verification_missing_or_failed")
            restored = True
            report.update(ok=True, outcome="stored_and_restored")
    except Exception as exc:  # noqa: BLE001 - preserve partial outcomes at backend boundaries
        report.update(ok=False, outcome="refused", reason=f"{type(exc).__name__}:{exc}")
    finally:
        report["closeout"] = _close(backend)
        if report["ok"] and not _clean_close(report["closeout"]):
            report.update(ok=False, outcome="closeout_failed")
        report["restoration_owed"] = mutated and not restored
        if report["restoration_owed"]:
            try:
                report["residual"] = backend.residual()
            except Exception as exc:  # noqa: BLE001 - preserve partial outcomes at backend boundaries
                report["residual"] = {
                    "read": "failed",
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            report["operator_fallback"] = (
                "Stop here; deadline/refusal is not a hardware abort. Preserve held data; no automatic retry or recovery."
            )
        try:
            report["source"] = backend.source_evidence()
        except Exception as exc:  # noqa: BLE001 - preserve partial outcomes at backend boundaries
            report["source_problem"] = f"{type(exc).__name__}:{exc}"
            report.update(ok=False, outcome="source_evidence_failed")
    return report
