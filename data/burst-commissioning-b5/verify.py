"""Recheck the portable B5 commissioning evidence, without instrument access."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from udv_echo_process.acquire.verify import read_words
from udv_echo_process.io.dop.bdd import read

root = Path(__file__).resolve().parent
report = json.loads((root / "manifest.json").read_text())
expected = [
    ("burst-4", "10", 4, "1.776", 5),
    ("common-reference-1", "4", 10, "1.850", 1),
    ("burst-18", "10", 18, "3.330", 5),
    ("common-reference-2", "18", 10, "1.850", 1),
]
assert report["pending_jobs"] == [
    "emissions-8",
    "common-reference-3",
    "emissions-64",
    "common-reference-4",
    "emissions-128",
]
assert len(report["jobs"]) == len(expected)
fixed_reference = None
count = 0
for step, (job, (name, before, burst, volume, point_count)) in enumerate(
    zip(report["jobs"], expected, strict=True), start=1
):
    assert job["job"] == name and job["step"] == step
    assert job["status"] == "ok" and len(job["points"]) == point_count
    assert job["compilation_identity"]["burst_length"]["value"] == str(burst)
    assert len(job["burst_transitions"]) == 1
    transition = job["burst_transitions"][0]
    assert transition["state"] == "verified" and transition["channel"] == "1"
    assert transition["before_burst"]["text"] == before
    assert transition["after_burst"]["text"] == str(burst)
    assert transition["after_sampling_volume"]["text"] == volume
    for point in job["points"]:
        path = root / point["file"]
        assert path.is_file() and path.parent == root
        assert hashlib.sha256(path.read_bytes()).hexdigest() == point["sha256"]
        assert path.stat().st_size == point["bytes"]
        assert point["enforced_covariates"] == [
            "sound_speed_ms",
            "prf_us",
            "burst_length",
            "emissions_per_profile",
        ]
        words = read_words(path)
        assert (
            words.burst_length,
            words.prf_us,
            words.emissions_per_profile,
            words.sound_speed_ms,
        ) == (burst, 600, 20, 1480)
        config = read(path).recording.streams[0].config.model_dump()
        assert config == point["decoded_config"]
        assert (config["burst_length"], config["sampling_volume_index"]) == (burst, 1)
        fixed = {
            key: value
            for key, value in config.items()
            if key not in {"burst_length", "n_gates", "resolution_mm", "max_depth_mm"}
        }
        if fixed_reference is None:
            fixed_reference = fixed
        assert fixed == fixed_reference
        if point["label"].startswith(("ctrl-", "cr")):
            assert (
                config["n_gates"],
                config["resolution_mm"],
                config["max_depth_mm"],
            ) == (50, 1.85, 100.788)
        else:
            assert (config["n_gates"], round(config["resolution_mm"], 6)) in {
                (145, round(1.85 / 3, 6)),
                (31, 2.96),
            }
        count += 1
    print(f"{name}: {point_count} BDD(s), {before}->{burst}, observed {volume} mm")
assert count == 12
print("PASS: 12 BDD hashes, four recorded transitions, word 8, decoded fixed settings")
