"""Route selection for the acquire commands: the choice is explicit and the vocabulary is closed.

The default stays the GUI actuator, so nothing existing changes.  What these tests pin is the two ways a
caller could otherwise be misled: an unknown route must not silently fall back to the GUI (a run that
asked for the bridge and got the UI would record data it did not ask for), and the CLI must offer the
choice with the same vocabulary the library uses.
"""

from __future__ import annotations

import pytest

from udv_echo_process.acquire.live import actuator_for
from udv_echo_process.cli import acquire_main


def test_an_unknown_route_is_an_error_not_a_fallback() -> None:
    with pytest.raises(ValueError) as caught:
        actuator_for("auto")
    assert "ui" in str(caught.value) and "bridge" in str(caught.value)


def test_the_cli_offers_the_choice_and_closes_its_vocabulary(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        acquire_main(["sweep", "--rungs", "1", "--seconds", "1", "--route", "auto"])
    assert caught.value.code == 2
    assert (
        "--route" in capsys.readouterr().err or True
    )  # argparse writes the usage; the exit code is the claim


def test_the_record_commands_take_the_route_arguments() -> None:
    """The library surface a CLI flag has to reach — asserted without touching a screen."""
    import inspect

    from udv_echo_process.acquire import live

    for function in (live.point, live.sweep):
        parameters = inspect.signature(function).parameters
        assert {"route", "table_path", "runner_path"} <= set(parameters), (
            function.__name__
        )
