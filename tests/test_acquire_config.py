"""Tests for the measurement channel — the single knob in ``acquire/config.py``.

A stored ``.BDD`` holds an independent configuration **per channel**, so a point
recorded on the wrong channel decodes as a perfectly valid point that is not the
point (docs/16 §12, the channel trap). Retargeting a run must therefore be one
knob and nothing else — a config field or the ``UDV_CHANNEL`` environment
variable — and the two consumers that need the channel (the driver that selects
it, the decode that names it) must both take it from there.

Pinned here:

- the precedence, in order: **explicit value > ``UDV_CHANNEL`` > default**;
- the default (channel 1 — the channel the verified sessions used);
- the accepted range 1..10, with a *clear* failure for anything else, because a
  silent fall-back to channel 1 after a typo in the variable is exactly the
  failure the channel trap makes undetectable downstream;
- the 0-based dialog index (probe: the combo's items are ``'1'``..``'10'`` with
  channel 1 at index 0), derived from the range rather than listed again;
- that no second parallel channel constant exists in the driver;
- that the driver and the runner read the channel from this one place.

Everything runs headless: neither the driver nor the runner needs ``pywin32``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from udv_echo_process.acquire.config import (
    CHANNEL_ENV_VAR,
    DEFAULT_CHANNEL,
    MAX_CHANNEL,
    MIN_CHANNEL,
    ChannelSetting,
    channel_from_environment,
)

# --------------------------------------------------------------- the environment


def test_an_unset_variable_means_the_default_channel() -> None:
    assert CHANNEL_ENV_VAR == "UDV_CHANNEL"
    assert DEFAULT_CHANNEL == 1
    assert (MIN_CHANNEL, MAX_CHANNEL) == (1, 10)
    assert channel_from_environment({}) == DEFAULT_CHANNEL


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_variable_is_unset_not_channel_zero(blank: str) -> None:
    """An empty value is a missing setting; channel 0 does not exist."""
    assert channel_from_environment({CHANNEL_ENV_VAR: blank}) == DEFAULT_CHANNEL


@pytest.mark.parametrize("value", ["2", " 7 ", "10", "1", "3\n"])
def test_the_variable_names_a_channel(value: str) -> None:
    assert channel_from_environment({CHANNEL_ENV_VAR: value}) == int(value.strip())


@pytest.mark.parametrize("value", ["eleven", "1.5", "ch1", "-3", "0", "11", "100"])
def test_an_invalid_variable_fails_loudly_and_names_itself(value: str) -> None:
    """A silent fall-back to channel 1 would measure the wrong channel — refuse."""
    with pytest.raises(ValueError, match=CHANNEL_ENV_VAR) as excinfo:
        channel_from_environment({CHANNEL_ENV_VAR: value})
    message = str(excinfo.value)
    assert value.strip() in message or repr(value) in message
    assert "1..10" in message


def test_the_variable_is_read_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CHANNEL_ENV_VAR, "4")
    assert channel_from_environment() == 4
    monkeypatch.setenv(CHANNEL_ENV_VAR, "not-a-channel")
    with pytest.raises(ValueError, match=CHANNEL_ENV_VAR):
        channel_from_environment()


# -------------------------------------------------------------------- precedence


def test_explicit_value_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ChannelSetting(channel=...)`` is the operator's explicit statement."""
    monkeypatch.setenv(CHANNEL_ENV_VAR, "9")
    assert channel_from_environment({CHANNEL_ENV_VAR: "9"}) == 9
    # The environment is only consulted for an *omitted* field: an explicit value
    # cannot be overridden by it, and the default cannot override the environment.
    assert ChannelSetting(channel=3).channel == 3
    assert ChannelSetting().channel == 9


def test_the_setting_takes_the_environment_when_the_field_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CHANNEL_ENV_VAR, "6")
    assert ChannelSetting().channel == 6
    assert ChannelSetting(channel=2).channel == 2  # explicit still wins
    monkeypatch.delenv(CHANNEL_ENV_VAR)
    assert ChannelSetting().channel == DEFAULT_CHANNEL


def test_an_invalid_environment_value_fails_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error must name the variable, not surface later as a wrong channel."""
    monkeypatch.setenv(CHANNEL_ENV_VAR, "zero")
    with pytest.raises(Exception, match=CHANNEL_ENV_VAR):
        ChannelSetting()


# ------------------------------------------------------------------- validation


@pytest.mark.parametrize("channel", [0, 11, -1, 100])
def test_a_channel_outside_the_offered_range_is_rejected(channel: int) -> None:
    with pytest.raises(Exception, match="channel"):
        ChannelSetting(channel=channel)


@pytest.mark.parametrize("channel", list(range(MIN_CHANNEL, MAX_CHANNEL + 1)))
def test_every_offered_channel_is_accepted(channel: int) -> None:
    assert ChannelSetting(channel=channel).channel == channel


def test_the_dialog_index_is_zero_based_and_derived_from_the_range() -> None:
    """Probe: the combo's items are '1'..'10', channel 1 at index 0."""
    assert ChannelSetting(channel=1).combo_index == 0
    assert ChannelSetting(channel=10).combo_index == 9
    assert ChannelSetting(channel=7).combo_index == 6
    assert ChannelSetting(channel=MAX_CHANNEL).combo_index == MAX_CHANNEL - MIN_CHANNEL


# -------------------------------------------------- the channel has one consumer


def test_the_driver_takes_its_channel_from_the_one_knob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No second channel constant: the driver asks the config for it."""
    driver = pytest.importorskip("udv_echo_process.acquire.driver")

    monkeypatch.setenv(CHANNEL_ENV_VAR, "5")
    assert driver.Win32Actuator().channel == 5
    assert driver.Win32Actuator(channel=2).channel == 2  # explicit wins
    monkeypatch.delenv(CHANNEL_ENV_VAR)
    assert driver.Win32Actuator().channel == DEFAULT_CHANNEL
    # The combo's item list is derived from the one range, not written again.
    assert driver.channel_items() == tuple(str(n) for n in range(MIN_CHANNEL, MAX_CHANNEL + 1))
    with pytest.raises(Exception, match="channel"):
        driver.Win32Actuator(channel=99)


def test_the_runner_names_that_channel_on_every_decode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The verification path takes the same channel: no per-call channel argument."""
    runner_module = pytest.importorskip("udv_echo_process.acquire.runner")
    from udv_echo_process.acquire.config import RecordSettings

    class _NoRunActuator:
        """The runner only stores its channel at construction here."""

    def make(channel: int | None = None):
        kwargs = {} if channel is None else {"channel": channel}
        return runner_module.SweepRunner(
            _NoRunActuator(),
            RecordSettings(name_prefix="sw100"),
            tmp_path / "capture",
            **kwargs,
        )

    monkeypatch.setenv(CHANNEL_ENV_VAR, "8")
    assert make().channel == 8
    assert make(channel=3).channel == 3
    monkeypatch.delenv(CHANNEL_ENV_VAR)
    assert make().channel == DEFAULT_CHANNEL
    with pytest.raises(Exception, match="channel"):
        make(channel=0)


def test_the_environment_is_read_in_one_place_only() -> None:
    """Only ``config`` may read the variable — one source of truth, not two."""
    import udv_echo_process.acquire.config as config_module

    package = Path(config_module.__file__).resolve().parent
    readers = [
        path.name
        for path in sorted(package.rglob("*.py"))
        if "os.environ" in path.read_text(encoding="utf-8")
        or "getenv(" in path.read_text(encoding="utf-8")
    ]
    assert readers == ["config.py"], readers
    assert os.path.exists(config_module.__file__)  # the scan reads real files
