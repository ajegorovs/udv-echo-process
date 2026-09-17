"""Contract tests for the sweep runner — ``acquire/runner.py``.

``test_acquire_actuator.py`` pins the binding tables and the ported recipes;
``test_acquire_driver.py`` pins the cycle those tables drive. This module pins
the layer above both: :class:`SweepRunner`, which turns one *planned* point into
one *logged* point — reset the application, apply the window, check what the
application kept, record and store, size the stored file against the signature,
decode it, and append exactly one record either way.

Everything here is written to the specification, not to an implementation that
may still be landing:

- the runner module is imported with ``pytest.importorskip``, so this file stays
  collectible (and skips) while ``acquire/runner.py`` does not exist yet;
- the actuator is a self-contained in-memory fake that records the exact call
  sequence, and is scripted per test for the stored file's size, the decode
  result and the parameter read-back;
- the runner's module-local decoder is monkeypatched, so no real ``.BDD`` file is
  needed — with one exception, the last test, which decodes the committed
  fixture in ``data/dop3010-velocity/`` through the real reader.

No test posts input to the application running on the operator's desktop, nothing
imports a sibling test module, and nothing here touches ``pywinauto``.

The load-bearing case is
:func:`test_a_size_far_off_the_signature_is_never_logged_as_valid`: a leftover
recording stored under the next point's name is 10x the signature and still
decodes as a valid point (docs/16 §15b), so a size off the signature must fail
the point *and* must never be appended as valid.

Two rules that were added to the module after this file's first cut are pinned in
the last two sections. A point that leaves the **application's** state unverified or
unstartable ends the run instead of burning the rest of the plan, and a panel nobody
recognises is refused rather than pressed (:func:`…stops_the_run`,
:func:`…instead_of_pressing`). Both are driven through a fake, never through the
application on the operator's desktop. Verification is scripted the way the decoder
is: the fake's "stored files" are sized buffers, not real ``.BDD`` files, so every
assertion is about what the runner does with a verdict — and the shared helper
installs a verifier that agrees, so the cases above the new sections keep asserting
the size guard and nothing else.
"""

from __future__ import annotations

import inspect
import math
import re
import types
from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from pathlib import Path

import pytest

runner_module = pytest.importorskip(
    "udv_echo_process.acquire.runner",
    reason="acquire/runner.py lands separately; there is nothing to drive yet",
)

from udv_echo_process.acquire import log as sweep_log
from udv_echo_process.acquire import plan as sweep_plan
from udv_echo_process.acquire.actuator import (
    STORE_TIMEOUT_S,
    VIEW_TIMEOUT_S,
    Actuator,
    OverlayKind,
    ParamRole,
    StripControl,
    StripState,
    StripView,
    ordered_writes,
)
from udv_echo_process.acquire.config import ParameterSet, RecordSettings
from udv_echo_process.acquire.log import (
    DecodedBlock,
    PointStatus,
    SizeSignature,
    point_records,
    read_entries,
)
from udv_echo_process.acquire.plan import (
    SweepDefinition,
    SweepPoint,
    plan_point,
    plan_sweep,
    profiles_for_duration,
)

if not hasattr(runner_module, "SweepRunner") or not hasattr(
    runner_module, "PointOutcome"
):
    pytest.skip(
        "udv_echo_process.acquire.runner defines no SweepRunner/PointOutcome yet",
        allow_module_level=True,
    )

SweepRunner = runner_module.SweepRunner
PointOutcome = runner_module.PointOutcome

# ----------------------------------------------------------------- the fixture data

#: The tested channel (docs/13 §1, the committed fixture in ``data/``).
SOUND_SPEED_MS = 1460.0
FIRST_GATE_MM = 2.0
TARGET_DEPTH_MM = 100.0
PRF_US = 169.0
BURST_LENGTH = 4

#: ``T``: the observation window in seconds — what defines a point.
DURATION_S = 1.0

#: The gate count of 98 mm of window at the finest rung of the 1460 m/s ladder,
#: and of the committed fixture's own channel 1 (``gate_n``).
GATES = 805

#: The measured profile-period law: a profile of ``emissions_per_profile``
#: emissions lasts ``emissions × PRF + ~1 ms`` (docs/16 §15). ``emissions`` is
#: chosen so the law reproduces the committed recording's own profile count —
#: ~0.0098 s per profile, i.e. ~102 profiles in a 1 s window.
EMISSIONS_PER_PROFILE = 52
PERIOD_OVERHEAD_S = 1e-3

#: The period the fake's own covariates imply — what a real recording of this
#: window would last, and therefore what its stored file's size would be.
PROFILE_PERIOD_S = EMISSIONS_PER_PROFILE * PRF_US * 1e-6 + PERIOD_OVERHEAD_S

#: The documented leftover-recording size: a wedged cycle's block stored under the
#: *next* point's name, 10x a normal point (docs/16 §15b).
BIG_SIZE = 1_039_825

#: The other way a file fails the signature: truncated, so nothing is revealed.
TINY_SIZE = 128

#: The two shapes of the composed store cycle an implementation may call.
STORE_CALLS = ("record_and_store", "try_record_and_store")

CLEAR = StripControl.CLEAR_AND_RESTART.value


def period_law_s(parameters: ParameterSet) -> float | None:
    """The profile period a point's own covariates imply; ``None`` without them."""
    if parameters.emissions_per_profile is None or parameters.prf_us is None:
        return None
    return (
        parameters.emissions_per_profile * parameters.prf_us * 1e-6 + PERIOD_OVERHEAD_S
    )


class PointStoreFailed(RuntimeError):
    """The composed cycle could not produce a stored file."""


class ScriptedBlock(DecodedBlock):
    """A decoded block that is **also** a mapping.

    The specification pins the runner's *result* (a ``DecodedBlock``) but not the
    shape its module-local decoder returns: a ``DecodedBlock``, or the decoded-word
    mapping that ``DecodedBlock.from_mapping`` documents itself as accepting. This
    object answers to both, so the tests assert the outcome instead of the
    adapter's private signature.
    """

    def items(self):  # type: ignore[override]
        """The block as decoded words — the ``from_mapping`` path."""
        return self.model_dump().items()

    def keys(self):
        return self.model_dump().keys()

    def get(self, key: str, default: object = None) -> object:
        return self.model_dump().get(key, default)

    def __getitem__(self, key: str) -> object:
        return self.model_dump()[key]

    def __len__(self) -> int:
        return len(self.model_fields)

    def __iter__(self):
        return iter(self.model_dump())


Mapping.register(ScriptedBlock)


def _block_for(path: Path | None, *, fake: FakeActuator | None = None) -> ScriptedBlock:
    """The block a real decode of ``path`` would produce.

    The stored file's size is inverted through the signature to recover the gate
    count the fake stored it with, so a multi-point run decodes each point into a
    block that agrees with that point's own request — the way a real file would.
    """
    signature = SizeSignature() if fake is None else fake.signature
    size = path.stat().st_size if path is not None and path.is_file() else None
    profiles = None if fake is None else fake.profiles_for(DURATION_S)
    gates = GATES
    if size is not None and profiles:
        gates = max(1, round(size / (signature.bytes_per_gate_profile * profiles)))
    return ScriptedBlock(
        channel=1,
        n_gates=gates,
        depth_mm=int(TARGET_DEPTH_MM),
        resolution_index=0,
        resolution_mm=sweep_plan.resolution_for_rung(0, SOUND_SPEED_MS),
        sound_speed_ms=SOUND_SPEED_MS,
        prf_us=PRF_US,
        burst_length=BURST_LENGTH,
        emissions_per_profile=EMISSIONS_PER_PROFILE,
        source_freq_khz=4000.0,
        size_bytes=size,
    )


# ------------------------------------------------------------------------ the fake


class FakeActuator:
    """A self-contained in-memory :class:`Actuator`, with the exact call order.

    Every method the :class:`Actuator` Protocol requires is implemented, plus both
    shapes of the composed cycle: ``record_and_store`` (the Protocol's — return the
    stored path, raise when it cannot) and ``try_record_and_store`` (the
    specification's tuple form, ``(ok, value_or_reason)``). A test scripts

    - :attr:`size_queue` — the size of each point's stored file, consumed per store
      (``None`` means "the size the signature predicts");
    - :attr:`gates_readback` — the gate count the parameter column reads back;
    - :attr:`store_failure` — the cycle's own failure text;
    - :attr:`payload` — real bytes to store instead of a sized buffer.

    :attr:`calls` is the observable contract: no assertion here looks at the
    runner's internals.
    """

    def __init__(
        self,
        directory: Path,
        *,
        profile_period_s: float = PROFILE_PERIOD_S,
        signature: SizeSignature | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.profile_period_s = profile_period_s
        self.signature = SizeSignature() if signature is None else signature
        self.calls: list[tuple] = []
        self.parameters: dict[str, str] = {}
        self.timeouts: list[float] = []
        self.gates_readback: str | None = None
        self.store_failure: str | None = None
        self.size_queue: list[int | None] = []
        self.payload: Path | None = None
        self.layout_note_value: str | None = None
        self.view = StripView.READY
        self.name: str | None = None
        self.stored: list[Path] = []
        self.sizes: list[int] = []
        self.duration_hint = DURATION_S
        self.extra: list[tuple] = []
        self.unknown: list[str] = []
        self.applied: ParameterSet | None = None

    # ---------------------------------------------------------------- scripting

    def script_size(self, *sizes: int | None) -> None:
        """Queue the stored file's size per point; ``None`` means "as expected"."""
        self.size_queue.extend(sizes)

    def profiles_for(self, duration_s: float) -> int | None:
        """The profile count the applied point's own covariates imply."""
        period = None if self.applied is None else period_law_s(self.applied)
        return None if period is None else profiles_for_duration(duration_s, period)

    def expected_size(self, duration_s: float) -> int | None:
        """The size a real recording of this window would be stored as.

        The fake stores what the application would: ``bytes_per_gate_profile``
        times the applied gate count times the profiles the period law derives
        from the point's own covariates.
        """
        profiles = self.profiles_for(duration_s)
        if profiles is None:
            return None
        gates = int(self.parameters.get(ParamRole.GATES.value) or GATES)
        return self.signature.expected_bytes(gates, profiles)

    def _state(self) -> StripState:
        if self.view is StripView.RECORDING:
            return StripState(button_count=1)
        return StripState(button_count=3, has_slider=self.view is StripView.STORE)

    # --------------------------------------------------------------- the Protocol

    def layout_note(self) -> str | None:
        return self.layout_note_value

    def read_parameter(self, role: ParamRole) -> str:
        self.calls.append(("read_parameter", role.value))
        return self.parameters.get(role.value, "")

    def write_parameter(self, role: ParamRole, value: str) -> None:
        self.parameters[role.value] = value
        self.calls.append(("write_parameter", role.value, value))

    def apply_point(self, parameters: ParameterSet) -> Mapping[ParamRole | str, str]:
        """The point's window, written in the committed order, and its read-back.

        The read-back is what a real actuator returns: the application's own text
        for the fields the runner checks, which :attr:`gates_readback` can script
        to a clamped value.
        """
        self.calls.append(("apply_point", parameters.gates))
        self.applied = parameters
        for role, value in ordered_writes(parameters):
            self.write_parameter(role, value)
        readbacks: dict[ParamRole | str, str] = {
            ParamRole.GATES: (
                self.gates_readback
                if self.gates_readback is not None
                else self.parameters.get(ParamRole.GATES.value, "")
            ),
            ParamRole.RESOLUTION: self.parameters.get(ParamRole.RESOLUTION.value, ""),
        }
        self.calls.append(
            ("readback", {role.value: value for role, value in readbacks.items()})
        )
        return readbacks

    def strip_state(self) -> StripState:
        self.calls.append(("strip_state",))
        return self._state()

    def wait_for_view(
        self,
        views: Iterable[StripView],
        *,
        timeout_s: float = VIEW_TIMEOUT_S,
        **extra: object,
    ) -> StripState:
        wanted = tuple(views)
        self.timeouts.append(float(timeout_s))
        self.calls.append(
            ("wait_for_view", tuple(v.value for v in wanted), float(timeout_s))
        )
        if extra:
            self.extra.append(("wait_for_view", extra))
        return self._state()

    def press(self, control: StripControl) -> None:
        self.calls.append(("press", control.value))
        if control is StripControl.CLEAR_AND_RESTART:
            self.view, self.name = StripView.READY, None
        elif control is StripControl.RECORD:
            self.view = StripView.RECORDING
        elif control in (StripControl.STOP, StripControl.DO_STORE):
            self.view = StripView.STORE
        elif control is StripControl.NEW_ACQUISITION:
            self.view = StripView.READY

    def answer_overlay(self) -> OverlayKind | None:
        self.calls.append(("answer_overlay", None))
        return None

    def set_store_name(self, name: str) -> None:
        self.name = name
        self.calls.append(("set_store_name", name))

    def commit_store(self) -> None:
        self.calls.append(("commit_store",))
        if self.name is None:
            raise PointStoreFailed("the Store dialog has no name")
        self._store(self.name, self.duration_hint, self.directory)

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = STORE_TIMEOUT_S,
        **extra: object,
    ) -> Path:
        self.calls.append(("wait_for_stored_file", float(timeout_s)))
        if extra:
            self.extra.append(("wait_for_stored_file", extra))
        if not self.stored:
            raise PointStoreFailed(f"no file appeared in {directory}")
        return self.stored[-1]

    # ---------------------------------------------------------- the composed cycle

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = STORE_TIMEOUT_S,
        **extra: object,
    ) -> Path:
        """The Protocol's cycle: the stored path, or a raise."""
        self.calls.append(("record_and_store", name, float(duration_s)))
        if extra:
            self.extra.append(("record_and_store", extra))
        if self.store_failure is not None:
            raise PointStoreFailed(self.store_failure)
        return self._store(name, duration_s, directory)

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = STORE_TIMEOUT_S,
        **extra: object,
    ) -> tuple[bool, object]:
        """The specification's cycle: ``(ok, path)`` or ``(False, reason)``."""
        self.calls.append(("try_record_and_store", name, float(duration_s)))
        if extra:
            self.extra.append(("try_record_and_store", extra))
        if self.store_failure is not None:
            return (False, self.store_failure)
        return (True, self._store(name, duration_s, directory))

    def _store(
        self, name: str, duration_s: float, directory: Path | None = None
    ) -> Path:
        target_dir = Path(directory) if directory is not None else self.directory
        target_dir.mkdir(parents=True, exist_ok=True)
        size = self.size_queue.pop(0) if self.size_queue else None
        target = target_dir / f"{name}.BDD"
        if self.payload is not None:
            target.write_bytes(self.payload.read_bytes())
        else:
            if size is None:
                size = self.expected_size(duration_s)
            if size is None:
                size = self.signature.expected_bytes(
                    GATES, max(1, math.ceil(duration_s / self.profile_period_s))
                )
            target.write_bytes(b"\x00" * size)
        self.sizes.append(target.stat().st_size)
        self.stored.append(target)
        self.view = StripView.READY
        return target

    def __getattr__(self, name: str) -> object:
        """Answer the one hook the specification leaves open.

        The runner needs the *achieved* profile period, which the ``Actuator``
        Protocol does not expose. Rather than guess the hook's name, the fake
        answers any *period-shaped* attribute with a plausible period and records
        the call; anything else is a genuine gap and raises, so a mistyped method
        can never be silently answered with ``None``.
        """
        if "period" in name or "timing" in name:

            def hook(*args: object, **kwargs: object) -> object:
                self.unknown.append(name)
                self.calls.append((name, args, kwargs))
                if name.endswith("_ms"):
                    return self.profile_period_s * 1000.0
                return self.profile_period_s

            return hook
        raise AttributeError(name)


class ExplodingActuator:
    """Every call fails: a point must still come back as an outcome."""

    def layout_note(self) -> str | None:
        raise RuntimeError("the screen cannot be read")

    def read_parameter(self, role: ParamRole) -> str:
        raise RuntimeError(f"cannot read {role.value}")

    def write_parameter(self, role: ParamRole, value: str) -> None:
        raise RuntimeError(f"cannot write {role.value}")

    def apply_point(self, parameters: ParameterSet) -> Mapping[ParamRole | str, str]:
        raise RuntimeError("the window cannot be applied")

    def strip_state(self) -> StripState:
        raise RuntimeError("the strip cannot be resolved")

    def wait_for_view(
        self, views: Iterable[StripView], *, timeout_s: float = VIEW_TIMEOUT_S
    ) -> StripState:
        raise RuntimeError("the view never changes")

    def press(self, control: StripControl) -> None:
        raise RuntimeError(f"cannot press {control.value}")

    def answer_overlay(self) -> OverlayKind | None:
        raise RuntimeError("cannot answer the overlay")

    def set_store_name(self, name: str) -> None:
        raise RuntimeError("the Store dialog has no name field")

    def commit_store(self) -> None:
        raise RuntimeError("the Store dialog never commits")

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        raise RuntimeError("no file appeared")

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        raise RuntimeError("the cycle failed")

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> tuple[bool, object]:
        raise RuntimeError("the cycle failed")

    def __getattr__(self, name: str) -> object:
        raise AttributeError(name)


# --------------------------------------------------------- the module-local decoder

#: A module-level callable whose name says "reader", or one whose owner is the
#: ``io`` layer, is the runner's decode adapter. Sibling ``acquire`` helpers
#: (``read_entries``, ``append_entry``, ``plan_sweep``, ...) are left alone.
READER_HINT = re.compile(r"read|load|decod|block|sniff|adapt|extract", re.IGNORECASE)
_OWNERS_NOT_READERS = {"log", "plan", "config", "actuator"}


def _is_io_owned(owner: str) -> bool:
    return owner.startswith("udv_echo_process.io")


def _replace_reader_adapters(
    monkeypatch: pytest.MonkeyPatch, reader: object
) -> list[str]:
    """Point the runner's decoder at ``reader``; return what was replaced."""
    patched: list[str] = []
    for name, value in list(vars(runner_module).items()):
        if name.startswith("__") or not callable(value) or isinstance(value, type):
            continue
        owner = getattr(value, "__module__", "") or ""
        if owner.rsplit(".", 1)[-1] in _OWNERS_NOT_READERS and not _is_io_owned(owner):
            continue
        if not (READER_HINT.search(name) or _is_io_owned(owner)):
            continue
        monkeypatch.setattr(runner_module, name, reader)
        patched.append(name)
    # ...and a decoder reached through an imported module (``bdd.read``, ``io.load``).
    for name, value in list(vars(runner_module).items()):
        if not isinstance(value, types.ModuleType):
            continue
        for reader_name in ("read", "_read_op", "read_path", "load"):
            if hasattr(value, reader_name):
                monkeypatch.setattr(value, reader_name, reader)
                patched.append(f"{name}.{reader_name}")
    return patched


class ScriptedReader:
    """The stand-in for the runner's decoder."""

    def __init__(
        self, block: DecodedBlock | None = None, *, fake: FakeActuator | None = None
    ) -> None:
        self.block = block
        self.fake = fake
        self.patched: list[str] = []
        self.paths: list[Path | None] = []
        self.calls = 0

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        self.paths.append(
            next((Path(arg) for arg in args if isinstance(arg, (str, Path))), None)
        )
        if self.block is not None:
            return self.block
        return _block_for(self.paths[-1], fake=self.fake)

    @property
    def count(self) -> int:
        return self.calls


def patch_reader(
    monkeypatch: pytest.MonkeyPatch,
    block: DecodedBlock | None = None,
    *,
    fake: FakeActuator | None = None,
) -> ScriptedReader:
    """Patch the runner's decoder and hand back the scripted one."""
    reader = ScriptedReader(block, fake=fake)
    names = _replace_reader_adapters(monkeypatch, reader)
    assert names, (
        "no module-local reader adapter found to patch in "
        f"{runner_module.__name__}; module-level callables are "
        f"{sorted(n for n, v in vars(runner_module).items() if callable(v))}"
    )
    reader.patched = names
    return reader


# ------------------------------------------------------ the module-local verifier

#: The runner's verification hook: ``acquire/verify.py``'s ``verify_stored_point``,
#: imported defensively by the runner so a checkout without that module still runs.
VERIFY_HOOK = "verify_stored_point"

#: "The caller did not script a verifier" — distinct from ``None``, which is the
#: runner's own "that module is not importable" state.
UNSCRIPTED = object()


class FakeVerification:
    """The shape of a ``VerificationResult``, built without importing ``verify``.

    The interface is pinned by the runner's contract (``ok``, ``mismatches``,
    ``facts``); this object answers to it so the tests do not depend on the sibling
    module being in the checkout.
    """

    def __init__(self, ok: bool, mismatches: Iterable[str] = ()) -> None:
        self.ok = bool(ok)
        self.mismatches = tuple(str(mismatch) for mismatch in mismatches)
        self.facts = None


class ScriptedVerifier:
    """The stand-in for ``verify_stored_point``: a verdict, or a raise."""

    def __init__(
        self,
        *,
        ok: bool = True,
        mismatches: Iterable[str] = (),
        error: BaseException | None = None,
    ) -> None:
        self.result = FakeVerification(ok, mismatches)
        self.error = error
        self.calls: list[tuple[Path, object]] = []

    def __call__(
        self, path: object, requested: object, *args: object, **kwargs: object
    ) -> FakeVerification:
        self.calls.append((Path(str(path)), requested))
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def paths(self) -> list[Path]:
        """Every file the runner asked about, in order."""
        return [path for path, _requested in self.calls]


def patch_verifier(monkeypatch: pytest.MonkeyPatch, verifier: object) -> object:
    """Point the runner's verification hook at ``verifier``; ``None`` = unimportable.

    ``None`` is not a cop-out: it is exactly the state the runner is in when
    ``acquire/verify.py`` is missing from the checkout, so the unavailable case is
    tested the way it happens rather than through a flag.
    """
    assert hasattr(runner_module, VERIFY_HOOK), (
        f"{runner_module.__name__} exposes no {VERIFY_HOOK!r} hook, so the verification "
        "step cannot be scripted; the step must call the imported name"
    )
    monkeypatch.setattr(runner_module, VERIFY_HOOK, verifier)
    return verifier


# ------------------------------------------------------------------------ helpers


def definition_for(*rungs: int) -> SweepDefinition:
    """The sweep the tests plan against: the tested channel's own parameters."""
    return SweepDefinition(
        sound_speed_ms=SOUND_SPEED_MS,
        first_gate_mm=FIRST_GATE_MM,
        target_depth_mm=TARGET_DEPTH_MM,
        duration_s=DURATION_S,
        rungs=rungs or (1,),
        prf_us=PRF_US,
        emissions_per_profile=EMISSIONS_PER_PROFILE,
        burst_length=BURST_LENGTH,
    )


def point_for(key: int = 1) -> SweepPoint:
    """The planned point at 1-based rung index ``key``."""
    return plan_point(key, definition_for(key))


def make_runner(
    base: Path,
    monkeypatch: pytest.MonkeyPatch | None = None,
    *,
    signature: SizeSignature | None = None,
    block: DecodedBlock | None = None,
    script_reader: bool = True,
    verifier: object = UNSCRIPTED,
    fake_class: type[FakeActuator] = FakeActuator,
    **fake_kwargs: object,
) -> tuple[FakeActuator, object, Path, ScriptedReader | None]:
    """A runner over a fresh fake, a private capture directory and a private log.

    Both module-local adapters are scripted: the decoder (a real ``.BDD`` read needs a
    real file, and the fake stores buffers) and the verifier. ``verifier`` defaults to
    one that agrees with the file, so a case that is not about verification asserts
    the size guard and nothing else; pass a :class:`ScriptedVerifier` to script a
    verdict, or ``None`` for the state the runner is in without ``acquire/verify.py``.
    ``fake_class`` is the fake's own type, so a case can subclass it to make the
    *application* misbehave without touching the runner.
    """
    base = Path(base)
    directory = base / "capture"
    directory.mkdir(parents=True, exist_ok=True)
    log_path = base / "logs" / "sweep.jsonl"
    signature = SizeSignature() if signature is None else signature
    fake = fake_class(directory, signature=signature, **fake_kwargs)
    engine = SweepRunner(
        fake,
        RecordSettings(name_prefix="sw100"),
        directory,
        signature=signature,
        log_path=log_path,
    )
    reader = (
        patch_reader(monkeypatch, block, fake=fake)
        if (monkeypatch and script_reader)
        else None
    )
    if monkeypatch is not None:
        # After the reader patch on purpose: the reader scan walks the module's
        # callables, and the verification hook is not one of them.
        patch_verifier(
            monkeypatch, ScriptedVerifier() if verifier is UNSCRIPTED else verifier
        )
    return fake, engine, log_path, reader


def stored_names(directory: Path) -> list[str]:
    """The stored files in a capture directory, sorted."""
    return sorted(path.name for path in Path(directory).glob("*.BDD"))


def is_committed_point_sized(fixture: Path) -> bool:
    """The committed point is a ~100 kB recording, not a stub or a placeholder."""
    return 50_000 <= fixture.stat().st_size <= 400_000


def status_of(outcome: PointOutcome) -> PointStatus:
    """The outcome's status as ``PointStatus``, whichever form it is held in."""
    value = outcome.status
    return PointStatus(getattr(value, "value", value))


def index_of(
    calls: list[tuple], predicate: Callable[[tuple], bool], *, after: int = -1
) -> int | None:
    """Index of the first recorded call matching ``predicate`` after ``after``."""
    for index, call in enumerate(calls):
        if index > after and predicate(call):
            return index
    return None


def sizes_named_in(text: str) -> set[int]:
    """Every integer ``text`` names, group separators stripped (``1,039,825``)."""
    return {
        int(match.replace(",", "").replace("_", ""))
        for match in re.findall(r"\d[\d,_]*", text)
    }


def expectation_band(
    signature: SizeSignature, gates: int, *, profiles: range = range(1, 1001)
) -> set[int]:
    """Every size the signature considers expected for ``gates``, per profile count.

    The runner derives the stored file's expected size from the gate count and the
    profile count its period law implies — a quantity that depends on the point's
    covariates rather than on the specification's text, so the assertion is that
    the reason names a size this signature itself would compute for some profile
    count a one-second window can have (not a particular one).
    """
    return {signature.expected_bytes(gates, count) for count in profiles}


# --------------------------------------------------------------- the public surface


def test_the_runner_surface_is_the_specified_one() -> None:
    """The interface every test below is written against."""
    fields = set(getattr(PointOutcome, "model_fields", {}) or {})
    if not fields:
        fields = set(inspect.signature(PointOutcome).parameters)
    assert {"point", "ok", "file", "status", "reason", "decoded"} <= fields

    init = inspect.signature(SweepRunner).parameters
    assert {"actuator", "settings", "directory"} <= set(init)
    assert {"signature", "log_path"} <= set(init)

    run_point = inspect.signature(SweepRunner.run_point).parameters
    assert {"point", "duration_s", "reset"} <= set(run_point)
    assert run_point["reset"].kind is inspect.Parameter.KEYWORD_ONLY
    assert run_point["reset"].default is True

    assert {"definition", "duration_s"} <= set(
        inspect.signature(SweepRunner.run).parameters
    )

    fake = FakeActuator(Path("capture"))
    assert isinstance(fake, Actuator)

    # The point the fixture data pins: 98 mm of window at the finest rung is 805.
    assert point_for(1).parameters.gates == GATES
    assert point_for(1).rung_index == 0


# ------------------------------------------------------------ 1. reset comes first


def test_reset_clears_the_application_before_the_parameters_and_the_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reset=True`` restarts the application *before* the point is applied."""
    fake, engine, _, _ = make_runner(tmp_path / "reset", monkeypatch)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    clear = index_of(fake.calls, lambda call: call[:2] == ("press", CLEAR))
    applied = index_of(fake.calls, lambda call: call[0] == "write_parameter")
    recorded = index_of(fake.calls, lambda call: call[0] in STORE_CALLS)
    assert clear is not None and applied is not None and recorded is not None, (
        fake.calls
    )
    assert clear < applied < recorded, fake.calls
    # The clear was observed, not assumed: the strip is polled after the press.
    assert index_of(fake.calls, lambda call: call[0] == "wait_for_view", after=clear)

    # ``reset=False`` applies its own window and knows nothing of a clear press.
    plain, plain_engine, _, _ = make_runner(tmp_path / "no-reset", monkeypatch)
    plain_outcome = plain_engine.run_point(point_for(1), DURATION_S, reset=False)

    assert plain_outcome.ok is True, plain_outcome.reason
    assert [call for call in plain.calls if call[:2] == ("press", CLEAR)] == []


# ------------------------------------------- 2. the window is applied and read back


def test_the_window_is_applied_before_recording_and_a_clamped_readback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """805 requested read back as 474 in the wrong write order (docs/16 §14)."""
    assert abs(sweep_plan.gate_drift(GATES, 764)) > sweep_plan.GATE_DRIFT_NOTE
    assert abs(sweep_plan.gate_drift(GATES, 766)) < sweep_plan.GATE_DRIFT_NOTE

    fake, engine, _, _ = make_runner(tmp_path / "within", monkeypatch)
    fake.gates_readback = "766"  # 4.8 % off: inside the note threshold
    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    writes = [call for call in fake.calls if call[0] == "write_parameter"]
    assert [call[1] for call in writes] == [
        ParamRole.RESOLUTION.value,
        ParamRole.GATES.value,
    ]
    assert writes[-1][2] == str(GATES)
    # The window is applied before anything is recorded, and the read-back the
    # application hands back is what the runner judges — not the request.
    first_write = index_of(fake.calls, lambda call: call[0] == "write_parameter")
    read_back = index_of(
        fake.calls,
        lambda call: (
            call[0] == "readback"
            and call[1].get(ParamRole.GATES.value)
            and call[1].get(ParamRole.RESOLUTION.value)
        ),
    )
    stored_at = index_of(fake.calls, lambda call: call[0] in STORE_CALLS)
    assert first_write is not None and read_back is not None and stored_at is not None
    assert first_write < read_back < stored_at, fake.calls
    assert fake.applied is not None and fake.applied.gates == GATES

    clamped, clamped_engine, clamped_log, _ = make_runner(
        tmp_path / "clamped", monkeypatch
    )
    clamped.gates_readback = "474"  # the measured wrong-order clamp
    clamped_outcome = clamped_engine.run_point(point_for(1), DURATION_S)

    assert clamped_outcome.ok is False
    assert clamped_outcome.reason
    # No recording was attempted, so nothing was stored and no junk file exists.
    assert [call for call in clamped.calls if call[0] in STORE_CALLS] == []
    assert clamped.stored == []
    assert stored_names(clamped.directory) == []
    if clamped_log.exists():
        assert all(
            record.status is not PointStatus.OK
            for record in point_records(read_entries(clamped_log))
        )


# ------------------------------------------------ 3. the size signature is the guard


@pytest.mark.parametrize("size", [BIG_SIZE, TINY_SIZE], ids=["leftover", "truncated"])
def test_a_size_far_off_the_signature_is_never_logged_as_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    """The critical case: a file off the signature is evidence, never a valid point."""
    signature = SizeSignature()
    fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch, signature=signature)
    fake.script_size(size)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.reason
    named = sizes_named_in(outcome.reason)
    assert size in named, outcome.reason  # the actual size is named
    assert named & expectation_band(signature, GATES), outcome.reason  # ...and expected

    records = point_records(read_entries(log_path))
    assert len(records) == 1, "one point, one record — evidence kept, not dropped"
    record = records[0]
    if record.expected_size_bytes is not None:
        assert record.expected_size_bytes in named
    if record.file_size_bytes is not None:
        assert record.file_size_bytes == size

    # The critical assertion: the point is in the log, and it is NOT valid.
    assert record.status in (PointStatus.FAILED, PointStatus.INVALID)
    assert record.status is not PointStatus.OK
    assert [
        other
        for other in point_records(read_entries(log_path))
        if other.status is PointStatus.OK
    ] == []
    # The rejected file is evidence: the record names it and it is still there.
    assert record.file_path is not None
    assert Path(record.file_path).is_file()
    assert Path(record.file_path).name in stored_names(fake.directory)


def test_a_plausible_file_is_decoded_and_appended_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signature passes, so the file is decoded and the point is valid."""
    fake, engine, log_path, reader = make_runner(tmp_path, monkeypatch)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    assert status_of(outcome) is PointStatus.OK
    assert isinstance(outcome.decoded, DecodedBlock)
    assert outcome.decoded.channel == 1
    assert outcome.decoded.n_gates == GATES
    assert outcome.file is not None
    assert Path(str(outcome.file)).is_file()
    assert reader is not None and reader.count >= 1

    assert len([call for call in fake.calls if call[0] in STORE_CALLS]) == 1
    entries = read_entries(log_path)
    records = point_records(entries)
    assert len(records) == 1
    assert records[0].status is PointStatus.OK
    assert records[0].decoded is not None
    assert len(sweep_log.point_names(entries)) == 1


# ------------------------------------------------- 4. an actuator that cannot store


def test_an_actuator_that_cannot_store_yields_not_ok_and_one_log_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``(False, reason)`` is a failed point, not a crash and not a silence."""
    fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch)
    fake.store_failure = "the Store dialog never appeared"

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.reason
    assert fake.store_failure in outcome.reason or "store" in outcome.reason.lower()
    assert outcome.file is None or not Path(str(outcome.file)).exists()
    assert stored_names(fake.directory) == []

    records = point_records(read_entries(log_path))
    assert len(records) == 1
    assert records[0].status is not PointStatus.OK


# ------------------------------------------------------------------ 5. run() order


def test_run_visits_every_point_in_order_and_a_failure_does_not_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three points, the middle one contaminated: all three are logged, in order."""
    definition = definition_for(1, 2, 3)
    points = plan_sweep(definition)
    fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch)
    fake.script_size(None, BIG_SIZE, None)

    outcomes = engine.run(definition, DURATION_S)

    assert len(outcomes) == len(points) == 3
    assert [getattr(outcome.point, "key", None) for outcome in outcomes] == [
        point.key for point in points
    ]
    assert [outcome.ok for outcome in outcomes] == [True, False, True]
    assert len([call for call in fake.calls if call[0] in STORE_CALLS]) == 3

    entries = read_entries(log_path)
    records = point_records(entries)
    assert len(records) == 3
    assert [record.status is PointStatus.OK for record in records] == [
        True,
        False,
        True,
    ]
    assert len(sweep_log.point_names(entries)) == 3  # a distinct name per point


# ------------------------------------------------------- 6. run_point never raises


def test_run_point_returns_an_outcome_even_when_every_actuator_call_fails(
    tmp_path: Path,
) -> None:
    """A wedged application is a failed point, never an exception out of run_point."""
    try:
        engine = SweepRunner(
            ExplodingActuator(),
            RecordSettings(name_prefix="sw100"),
            tmp_path,
            signature=SizeSignature(),
            log_path=tmp_path / "sweep.jsonl",
        )
    except Exception as exc:  # noqa: BLE001 - the point is that it must not happen
        pytest.fail(f"constructing the runner touched the actuator and raised {exc!r}")

    try:
        outcome = engine.run_point(point_for(1), DURATION_S)
    except Exception as exc:  # noqa: BLE001 - the contract under test
        pytest.fail(f"run_point raised {exc!r} instead of returning an outcome")

    assert isinstance(outcome, PointOutcome)
    assert outcome.ok is False
    assert isinstance(outcome.reason, str) and outcome.reason


# ------------------------------------------------------- 7. the reset poll is bounded


def test_the_reset_poll_is_bounded_and_never_an_unbounded_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every view wait carries a timeout; the number of waits stays bounded."""
    fake, engine, _, _ = make_runner(tmp_path, monkeypatch)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    waits = [call for call in fake.calls if call[0] == "wait_for_view"]
    assert waits, "the reset must be observed, not assumed"
    for call in waits:
        wanted, timeout_s = call[1], call[2]
        assert wanted, call  # a wait names the views it waits for
        assert isinstance(timeout_s, float) and timeout_s > 0, call
        assert timeout_s <= 60.0, call  # a bounded budget, not an idiom of forever
    assert len(waits) <= 25, f"the poll was unbounded: {len(waits)} waits"
    assert fake.timeouts == [call[2] for call in waits]


# -------------------------------------------------- 8. the real committed .BDD file


def test_a_real_committed_point_decodes_through_the_real_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case that does not patch the decoder: the committed fixture.

    ``data/dop3010-velocity/sw100-k1-161738.BDD`` is the point this runner plans
    (rung 1, 805 gates, c = 1460 m/s, PRF 169 µs), 139,193 B of real recording —
    within a few per cent of the size the signature expects for it, so the guard
    has to pass it.
    """
    fixture = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "dop3010-velocity"
        / "sw100-k1-161738.BDD"
    )
    if not fixture.is_file():
        pytest.skip(f"the committed fixture is not in this checkout: {fixture}")
    pytest.importorskip(
        "udv_echo_process.io.dop.bdd",
        reason="the .BDD reader is not importable in this environment",
    )
    assert is_committed_point_sized(fixture)  # ~100 kB, not a stub file

    fake, engine, _, _ = make_runner(tmp_path, monkeypatch, script_reader=False)
    fake.payload = fixture

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    assert isinstance(outcome.decoded, DecodedBlock)
    # The file is the authority: channel 1 carries the measured 805 gates.
    assert outcome.decoded.channel == 1
    assert outcome.decoded.n_gates == GATES
    assert outcome.decoded.sound_speed_ms == SOUND_SPEED_MS


# ---------------------------------------------------------- 9. the circuit breaker
#
# A failure that leaves the *application's* state unverified or unstartable is not a
# worse point failure — it is the run being cut short. Two shapes matter: a strip that
# will not come back startable, and a panel nobody recognises. The first must stop the
# sweep, the second must stop it *without pressing anything*; and a point that merely
# fails on its own evidence (the size guard, a clamp) must still leave the sweep
# running, which is what section 5 asserts.


class WedgingActuator(FakeActuator):
    """A fake whose strip stops coming back startable from the Nth point on.

    The first :attr:`healthy` points run normally; after them the strip reports a
    structure the view table has no row for — what an application that has dropped
    into a panel of its own, or gone deaf to the strip, looks like from here. Nothing
    about the *file* fails: the wedge is in the application's state, which is the
    difference the circuit breaker is about.
    """

    def __init__(
        self, directory: Path, *, healthy: int = 1, **fake_kwargs: object
    ) -> None:
        super().__init__(directory, **fake_kwargs)
        self.healthy = healthy
        self.applied_count = 0

    @property
    def wedged(self) -> bool:
        """True once the strip has stopped answering with a startable view."""
        return self.applied_count >= self.healthy

    def _state(self) -> StripState:
        if self.wedged:
            return StripState(button_count=7)  # no row in STRIP_BUTTON_ORDER
        return super()._state()

    def apply_point(self, parameters: ParameterSet) -> Mapping[ParamRole | str, str]:
        """Apply a window and count it — one count per point that got this far."""
        self.applied_count += 1
        return super().apply_point(parameters)


def test_a_point_that_will_not_come_back_startable_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point 2 of 4 wedges the strip: points 3 and 4 are never attempted."""
    definition = definition_for(1, 2, 3, 4)
    assert len(plan_sweep(definition)) == 4
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=WedgingActuator, healthy=1
    )

    outcomes = engine.run(definition, DURATION_S)

    # The outcome tuple ends at the aborting point: there is no outcome for k=3 or k=4.
    assert [getattr(outcome.point, "key", None) for outcome in outcomes] == [1, 2]
    assert outcomes[0].ok is True, outcomes[0].reason
    assert outcomes[-1].ok is False

    # The abort is *marked*: a caller has to be able to tell "this point was bad"
    # from "the run was cut short", and the outcome surface must carry it.
    fields = set(getattr(PointOutcome, "model_fields", {}) or {}) or set(
        inspect.signature(PointOutcome).parameters
    )
    assert "aborted" in fields, fields
    assert outcomes[0].aborted is False
    assert outcomes[-1].aborted is True
    note = getattr(runner_module, "ABORT_NOTE", None)
    assert note and note in (outcomes[-1].reason or ""), outcomes[-1].reason

    # Points 3 and 4 were never attempted: no window applied, no store cycle, no
    # third name, no second file.
    assert fake.applied_count == 1, fake.calls
    assert len([call for call in fake.calls if call[0] in STORE_CALLS]) == 1
    assert len(stored_names(fake.directory)) == 1

    records = point_records(read_entries(log_path))
    assert [record.key for record in records] == [1, 2], "the abort is logged, once"
    assert [record.status is PointStatus.OK for record in records] == [True, False]
    assert len(sweep_log.point_names(read_entries(log_path))) == 2


class UnrecognisedPanel(Enum):
    """A panel the runner's table has no row for — deliberately not an ``OverlayKind``."""

    DEVICE_OFFLINE = "device_offline"


class OverlayActuator(FakeActuator):
    """A fake that reports one panel to ``answer_overlay``, forever.

    Every press the runner asks for is recorded, so "did it press anything?" is an
    assertion about the call sequence and nothing else.
    """

    def __init__(
        self, directory: Path, *, panel: object, **fake_kwargs: object
    ) -> None:
        super().__init__(directory, **fake_kwargs)
        self.panel = panel

    def answer_overlay(self) -> object:  # type: ignore[override] - a panel may be odd
        """Report what is up — a warning, the Store dialog, or something unknown."""
        value = getattr(self.panel, "value", self.panel)
        self.calls.append(("answer_overlay", value))
        return self.panel


def test_an_unrecognised_overlay_stops_the_run_instead_of_pressing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The policy on an unknown panel: refuse and stop — press nothing on it."""
    assert not isinstance(UnrecognisedPanel.DEVICE_OFFLINE, OverlayKind)
    definition = definition_for(1, 2)
    fake, engine, log_path, _ = make_runner(
        tmp_path,
        monkeypatch,
        fake_class=OverlayActuator,
        panel=UnrecognisedPanel.DEVICE_OFFLINE,
    )

    outcomes = engine.run(definition, DURATION_S)

    assert len(outcomes) == 1, "the run must stop at the unrecognised panel"
    outcome = outcomes[0]
    assert outcome.ok is False
    assert outcome.aborted is True
    assert "device_offline" in (outcome.reason or ""), outcome.reason

    # Not one button on it: no strip press, no cycle, no recording, no file.
    assert [call for call in fake.calls if call[0] == "press"] == [], fake.calls
    assert [call for call in fake.calls if call[0] in STORE_CALLS] == []
    assert fake.applied is None
    assert stored_names(fake.directory) == []

    records = point_records(read_entries(log_path))
    assert len(records) == 1
    assert records[0].status is not PointStatus.OK


def test_a_known_warning_is_answered_and_the_run_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is for panels nobody recognises, not for overlays as such."""
    definition = definition_for(1, 2)
    fake, engine, _, _ = make_runner(
        tmp_path, monkeypatch, fake_class=OverlayActuator, panel=OverlayKind.WARNING
    )

    outcomes = engine.run(definition, DURATION_S)

    assert [outcome.ok for outcome in outcomes] == [True, True], [
        outcome.reason for outcome in outcomes
    ]
    assert len([call for call in fake.calls if call[0] == "answer_overlay"]) >= 2


# ------------------------------------------------- 10. verified from the artifact
#
# The size signature says "a file this size"; only the file's own words say "the file
# this point asked for". That check is delegated to acquire/verify.py, so what these
# cases pin is what the runner does with the verdict — and that no verdict is never a
# pass.


def test_a_file_that_does_not_say_what_was_asked_for_is_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verification mismatch invalidates the point, mismatches and all."""
    mismatches = (
        "n_gates: the file holds 766, the point asked for 805",
        "emissions_per_profile: the file holds 40, the point asked for 52",
    )
    verifier = ScriptedVerifier(ok=False, mismatches=mismatches)
    fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch, verifier=verifier)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert status_of(outcome) is not PointStatus.OK
    assert outcome.aborted is False, "a mismatch is this point's failure, not an abort"
    assert outcome.reason and all(
        mismatch in outcome.reason for mismatch in mismatches
    ), outcome.reason

    # The check ran on this point's own stored file, against this point's request.
    assert len(verifier.calls) == 1, verifier.calls
    verified_path, requested = verifier.calls[0]
    assert outcome.file is not None
    assert Path(str(outcome.file)) == verified_path
    assert requested == point_for(1).parameters

    # The rejected file is evidence: still there, still this point's record, and the
    # record is never valid.
    assert stored_names(fake.directory) == [Path(str(outcome.file)).name]
    records = point_records(read_entries(log_path))
    assert len(records) == 1
    assert records[0].status is not PointStatus.OK
    assert records[0].decoded is not None


def test_verification_that_raises_refuses_the_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No verdict is not a pass: a verifier that blows up leaves the file unproven."""
    verifier = ScriptedVerifier(error=RuntimeError("the block carries no word 10"))
    _fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch, verifier=verifier)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is False
    assert outcome.reason and "word 10" in outcome.reason, outcome.reason

    records = point_records(read_entries(log_path))
    assert len(records) == 1
    assert records[0].status is not PointStatus.OK


def test_verification_that_cannot_be_imported_is_reported_not_silently_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``acquire/verify.py`` absent: the size guard still decides, but not silently.

    ``verifier=None`` is the state the runner is in when that module is not in the
    checkout, so the point keeps the verdict the size signature gave it — and its
    reason, and the log record's failure, both say that nothing read the file's words.
    """
    _fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch, verifier=None)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason  # the existing size behaviour, unchanged
    assert status_of(outcome) is PointStatus.OK
    reason = outcome.reason or ""
    assert "verif" in reason.lower(), reason
    assert "not importable" in reason, reason

    records = point_records(read_entries(log_path))
    assert len(records) == 1
    assert records[0].status is PointStatus.OK
    assert records[0].decoded is not None
    # The note reaches the log too: an OK point whose words nobody read says so.
    logged = records[0].failure or ""
    assert "verif" in logged.lower(), records[0].failure
