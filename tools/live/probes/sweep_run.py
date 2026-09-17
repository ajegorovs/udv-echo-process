"""Two points, one axis, through the runner — the shape this implementation exists for.

The near-term goal is a *single-channel* parametric sweep: one duration for every point,
a slot of parameter permutations, and a record of what each point did. This probe is that,
in miniature — two points, twelve seconds each, on one channel, with exactly one parameter
axis moving between them:

    k = 1   resolution 0.1217 mm   gates ~797   window 99 mm
    k = 2   resolution 0.2433 mm   gates ~399   window 99 mm

Same window, same sound speed, same first gate, same ``T``; the resolution ladder rung is
what changes, so the two files differ in *how finely* the window is sampled and in nothing
else — a like-for-like pair, which is what makes the comparison worth storing.

Everything below is the port's own code path: ``plan_sweep`` computes the requests from the
measured laws, ``SweepRunner`` writes them through the sidebar, reads the write back, records
and stores, decodes the stored file on the channel that measured, verifies its words against
the request and appends one JSONL entry per point, valid or not. The probe adds no input of
its own — if this works, the acquisition path is covered; if it does not, the log says which
point and which check.

Run through the scheduled task (session 1 owns the screen), never from this shell.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from udv_echo_process.acquire.config import RecordSettings
from udv_echo_process.acquire.driver import Win32Actuator
from udv_echo_process.acquire.plan import SweepDefinition, plan_sweep
from udv_echo_process.acquire.runner import SweepRunner

#: The application's own working directory — the one its Store dialog showed today
#: (`C:\REPOS\DOP-CONTROL\RECON\OUT\CAPTURE`), so no application setting is touched.
# The application's own working directory, where its Store dialog writes. On a machine that
# is not this one, set UDV_STORE_DIR to it: the cycle asserts the dialog before it commits,
# so a wrong value refuses the point instead of scattering files.
STORE = Path(
    os.environ.get(
        "UDV_STORE_DIR", str(Path(__file__).resolve().parents[3] / "outputs" / "capture")
    )
)
LOG = Path(__file__).resolve().parents[3] / "outputs" / "live" / "sweep.jsonl"

#: One duration for every point. Twelve seconds sits in the operator's own 10-15 s band.
DURATION_S = 12.0


def main() -> int:
    channel = int(os.environ.get("UDV_CHANNEL", "1"))
    notes: list[str] = []
    definition = SweepDefinition(
        sound_speed_ms=1460.0,  # word 19 of every file stored on this channel
        first_gate_mm=2.0,  # the application's First gate depth, as read today
        target_depth_mm=99.0,  # the window the channel already measures (word 2)
        duration_s=DURATION_S,
        rungs=(1, 2),  # the one axis that moves
        prf_us=212.0,  # word 5; the depth budget is checked against it before recording
        emissions_per_profile=150,  # word 14
        burst_length=4,  # word 8
    )

    print(f"two-point sweep: channel {channel}, T = {DURATION_S} s")
    print(f"  store dir: {STORE}")
    print(f"  log      : {LOG}")
    for point in plan_sweep(definition):
        parameters = point.parameters
        print(
            f"  plan k={point.key}: resolution {parameters.resolution_text} mm, "
            f"gates {parameters.gates}, window {point.expected_depth_mm} mm "
            f"(rung {definition.rung_mm:.4f} mm at c = {parameters.sound_speed_ms} m/s)"
        )

    actuator = Win32Actuator(channel=channel, note_sink=notes.append)
    settings = RecordSettings(capture_dir=str(STORE), name_prefix="sweep12")
    runner = SweepRunner(
        actuator, settings, STORE, signature=None, log_path=LOG, channel=channel
    )

    outcomes = runner.run(definition, DURATION_S)

    print(f"\n{len(outcomes)} outcome(s):")
    for outcome in outcomes:
        point = outcome.point
        print(
            f"\n  k={point.key if point is not None else '?'}  ok={outcome.ok}  "
            f"aborted={outcome.aborted}  status={outcome.status}"
        )
        print(f"    file  : {outcome.file}")
        print(f"    reason: {outcome.reason}")
        block = outcome.decoded
        if block is not None:
            fields = (
                "gates",
                "resolution_mm",
                "depth_mm",
                "sound_speed_ms",
                "prf_us",
                "emissions_per_profile",
                "burst_length",
            )
            print(
                "    stored: "
                + ", ".join(f"{name}={getattr(block, name, None)}" for name in fields)
            )

    print("\n  notes from the actuator:")
    for note in notes:
        print(f"    - {note}")
    if runner.log_errors:
        print("  log errors:", runner.log_errors)

    stored = sum(1 for outcome in outcomes if outcome.ok)
    verdict = "OK" if stored == 2 and len(outcomes) == 2 else "NOT OK"
    print(f"\nSWEEP {verdict}: {stored}/{len(outcomes)} point(s) ok")
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
