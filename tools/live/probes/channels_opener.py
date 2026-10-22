"""One invocation: the ``Channels`` popup's **complete** open / read / close / reopen / read /
close lifecycle, with no operator gesture.

**What changed, and why.** The earlier probes needed the operator to open the popup and to close
it again. A live prototype (``channels-stepped-path-live-01``) then showed that a **bounded stepped
real-cursor path** off the popup (13 positions of <= 40 px) was followed by an observed ``ABSENT``
on both of its paths, where one warp to the same point had not closed it. That path is now owned by
production code, not by a probe:

* the geometry and the pure planner — :func:`…ui.menu.stepped_path`, bounded by
  :data:`…ui.menu.MAX_STEP_PX` / :data:`…ui.menu.MAX_STEPS` / :data:`…ui.menu.MAX_PATH_SECONDS`;
* the scheduling — :func:`…win32.cursor._move_real_cursor_stepped`, the facade's
  ``_move_real_cursor_stepped``: one bare ``SetCursorPos`` per position, the plan's own interval, a
  read-back per step, the production clip release, and the caller's per-step binding/foreground
  guard;
* the popup lifecycle — ``ParametersSurface.open_channels_popup`` and
  ``ParametersSurface.dismiss_channels_popup`` with typed ``PathPlan``, ``ChannelsOpen`` and
  ``ChannelsDismissal`` results.

This file is now only orchestration and comparison. It presses no popup entry, has no ``Record``,
``Stop``, ``Clear``, mode, tick or setting action, writes no field, takes no screenshot, posts no
message, and never retries a close. An already-open popup is **adopted** rather than refused, so a
run needs no operator baseline: nothing has to be hovered by hand before it starts.

**The chain, and what success means:**

    read (ABSENT or an already-readable popup, adopted)
      -> open_channels_popup (one measured hover only when the popup was absent)
      -> read + verify the full 8-band settings surface and its five amounts
      -> dismiss_channels_popup (one bounded stepped path)
      -> only on an observed ABSENT: one reopen -> fresh read -> compare five amounts
      -> a second bounded stepped path -> only an observed ABSENT ends the run

Exit ``0`` requires every one of those observed facts, including the **final** close. Exit ``3``
refused before any gesture; ``4`` no readable full popup; ``5`` a close that was not observed
``ABSENT`` or a reopen whose amounts are unreadable or changed; ``2`` unusable environment.
Nothing is retried and no operator action is requested.

**Run** (interactive session, no operator gesture needed):

    ./tools/live/dispatch.sh channels_opener.py [--settle 2.0] [--baseline PATH]

``--baseline`` is optional: it compares the first reading's numeric texts with a saved report.
Without it the numbers are recorded as the reference for the next run and the report says, in
``settings_unchanged``, that no comparison was made.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

__all__ = [
    "NUMERIC_FACTS",
    "amounts",
    "hover_outcome",
    "main",
    "reopen_comparison",
    "reopen_licence",
    "visual_mode",
]

#: The five amounts the full settings popup states in native text, in report order. Read through
#: ``channels_capture.numeric_slots`` — the reader's own map — never re-parsed here.
NUMERIC_FACTS: tuple[str, ...] = (
    "repeat",
    "start_channel",
    "apply_from",
    "profiles",
    "seconds",
)


class OpenerRefused(Exception):
    """A refusal that is a statement about the evidence, never a retry."""


class ReopenRefused(Exception):
    """The popup was not observed ABSENT, so the one licensed reopen is not taken."""


def amounts(read) -> dict[str, str | None]:
    """The five amounts as exact text, through the reader's own ``numeric_slots`` map.

    ``None`` means the reader stated no slot for that amount — it is *UNREADABLE*, never equal to
    another reading's ``None``.
    """
    from udv_echo_process.acquire.channels_capture import numeric_slots

    slots = numeric_slots(read)
    return {name: (slots[name][0] if name in slots else None) for name in NUMERIC_FACTS}


def _numeric_texts(read) -> dict[str, str | None]:
    """All five numeric texts of one reading — the same owner map the reopen comparison uses."""
    return amounts(read)


def visual_mode(read) -> dict:
    """The MODE / rolling attribution of one reading, or why the tree cannot state it."""
    capture = getattr(read, "capture", None)
    mark = None if capture is None else getattr(capture, "visual_mode_mark", None)
    if mark is None:
        return {
            "available": False,
            "mode": None,
            "rolling": None,
            "reason": (
                "no fresh capture accompanied this reading, so the painted MODE / rolling marks "
                "are not available for comparison; ticks and toggles are never readable from "
                "the tree"
            ),
        }
    return {
        "available": True,
        "mode": mark.mode,
        "rolling": mark.rolling,
        "native_fact": False,
    }


def reopen_comparison(before, after) -> dict:
    """Compare the open reading with the reading after the one licensed reopen.

    Five amounts are compared field by field; an amount either reading does not state is
    **UNREADABLE**, never "unchanged". The painted MODE / rolling attribution is compared only
    when both readings carry a fresh capture, and a reading without one says so.
    """
    base, now = amounts(before), amounts(after)
    from udv_echo_process.acquire.ui.channels import ChannelsSurface

    surface_ok = after.surface is ChannelsSurface.SETTINGS_POPUP
    compared = [
        name
        for name in NUMERIC_FACTS
        if base[name] is not None and now[name] is not None
    ]
    unreadable = [name for name in NUMERIC_FACTS if name not in compared]
    differences = [
        f"{name}: {base[name]!r} -> {now[name]!r}"
        for name in compared
        if base[name] != now[name]
    ]
    base_mark, now_mark = visual_mode(before), visual_mode(after)
    mode_differences: list[str] = []
    if base_mark["available"] and now_mark["available"]:
        for key in ("mode", "rolling"):
            if base_mark[key] != now_mark[key]:
                mode_differences.append(
                    f"{key}: {base_mark[key]!r} -> {now_mark[key]!r}"
                )
        mode_note = (
            "the painted MODE / rolling marks agree between the two readings"
            if not mode_differences
            else "the painted MODE / rolling marks differ between the two readings"
        )
    else:
        mode_note = base_mark.get("reason") or now_mark.get("reason") or "not available"
    return {
        "ok": surface_ok
        and not differences
        and not unreadable
        and not mode_differences,
        "surface": after.surface.value,
        "amounts_before": base,
        "amounts_after": now,
        "compared": compared,
        "unreadable": unreadable,
        "differences": differences,
        "mode_before": base_mark,
        "mode_after": now_mark,
        "mode_differences": mode_differences,
        "mode_note": mode_note,
    }


def reopen_licence(dismissal) -> None:
    """License the one reopen **only** on an observed ``ABSENT``; never retry the path."""
    from udv_echo_process.acquire.udop.parameters import DismissalOutcome

    if dismissal.outcome is not DismissalOutcome.ABSENT:
        raise ReopenRefused(
            f"the stepped dismissal did not produce an observed ABSENT surface (outcome "
            f"{dismissal.outcome.value!r}, last read {dismissal.surface_after!r}); this run takes "
            f"no second path and no retry: {dismissal.clause or 'no clause'}"
        )


def hover_outcome(before, after, baseline: dict | None = None) -> dict:
    """The one comparison: the full 8-band settings popup, read successfully, with its numbers.

    A reached full popup is accepted on what the reader can actually state about it: the
    ``settings_popup`` surface, the measured 8-band signature, ``readable`` true and no named
    refusal. It does **not** require an entry row: ``resolve_channels`` states an entry only on
    the multiplexer-on one-entry *clip*, while the full settings surface legitimately reports
    ``entry is None``.
    """
    from udv_echo_process.acquire.ui.channels import SETTINGS_SIGNATURE, ChannelsSurface

    problems: list[str] = []
    if after.surface is not ChannelsSurface.SETTINGS_POPUP:
        problems.append(
            f"the popup resolved to {after.surface.value!r}, not the full 'settings_popup'"
        )
    if tuple(after.signature) != SETTINGS_SIGNATURE:
        problems.append(
            f"the popup's band signature reads {list(after.signature)} where the measured "
            f"settings popup bands {list(SETTINGS_SIGNATURE)}: this is a changed structure, not "
            "the same popup"
        )
    if not after.readable:
        problems.append(
            "the popup reading is not readable, so the full popup was not read successfully"
        )
    refusals = tuple(getattr(after, "refusals", ()))
    if refusals:
        problems.append(
            "the popup reading carries named refusal(s): " + "; ".join(refusals)
        )
    texts = _numeric_texts(after)
    if baseline is None:
        unchanged = (
            "UNKNOWN: no prior baseline was supplied, so the numbers below are a reference for "
            "a later run and no before/after comparison was made"
        )
        differences: list[str] = []
        uncompared: list[str] = []
    else:
        base_texts = dict(baseline.get("numeric_texts") or {})
        # A slot either reading does not state is UNREADABLE, never "unchanged".
        shared = [
            name
            for name in texts
            if texts[name] is not None and base_texts.get(name) is not None
        ]
        uncompared = [name for name in NUMERIC_FACTS if name not in shared]
        differences = [
            f"{name}: {base_texts[name]!r} -> {texts[name]!r}"
            for name in shared
            if base_texts[name] != texts[name]
        ]
        if differences:
            unchanged = "the baseline's numeric texts differ from this reading"
        elif shared:
            unchanged = (
                f"UNKNOWN: only the {len(shared)} of {len(NUMERIC_FACTS)} numeric text(s) both "
                "the baseline and this reading state were compared; ticks and toggles are never "
                "readable"
            )
        else:
            unchanged = (
                "UNKNOWN: the baseline and this reading share no stated numeric text, so no "
                "comparison was made"
            )
    return {
        "ok": not problems,
        "problems": problems,
        "surface": after.surface.value,
        "readable": after.readable,
        "signature": list(after.signature),
        "entry": None if after.entry is None else after.entry.model_dump(mode="json"),
        "numeric_texts": texts,
        "baseline_differences": differences,
        "baseline_uncompared": uncompared,
        "settings_unchanged": unchanged,
    }


def _unexpected(exc: BaseException, *, gesture_attempted: bool) -> dict:
    """A failed run must not keep a success-shaped prior state; record what is actually known."""
    return {
        "phase": "failed",
        "written_at": _now(),
        "failed": f"{type(exc).__name__}: {exc}",
        "gesture_attempted": gesture_attempted,
        "popup_left_open_for_operator": None,
        "note": (
            "the run ended on an exception this probe does not classify; the popup's state is "
            "UNKNOWN, no cleanup path was walked, and nothing is retried"
        ),
    }


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat()


def _write(path: Path, payload: dict) -> None:
    """Durable before the gesture: flush and fsync, so a crash still leaves the note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _open(actuator, target, read, *, settle: float):
    """Take one open attempt and return its typed record — including an ``UNKNOWN`` one.

    The record is evidence: an ``UNKNOWN`` open is returned, never converted into a bare
    exception, so the report keeps what the hover attempt observed instead of discarding it.
    """
    return actuator.open_channels_popup(
        target=target, read=read, timeout_s=max(0.0, settle), adopt_open=True
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, help="a prior channels_opener report to compare"
    )
    parser.add_argument(
        "--settle", type=float, default=2.0, help="poll bound after a gesture (s)"
    )
    parser.add_argument(
        "--report", type=Path, help="report path (default outputs/live/...)"
    )
    args = parser.parse_args(argv)

    from udv_echo_process.acquire.channels_read import read_channels
    from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
    from udv_echo_process.acquire.udop.parameters import DismissalOutcome, PopupOutcome
    from udv_echo_process.acquire.ui.channels import surface_left_open
    from udv_echo_process.acquire.ui.layout import MAIN_CLASS
    from udv_echo_process.acquire.win32.tree import visible_main_windows

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    report_path = (
        args.report or REPO / "outputs" / "live" / f"channels-opener-{stamp}.json"
    )
    baseline = None
    if args.baseline is not None:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    scope = {
        "presses": 0,
        "record": False,
        "mode": False,
        "settings": False,
        "dismissal": "one bounded stepped real-cursor path off the popup",
        "reopen": "one measured hover, only after an observed ABSENT",
        "paths": 2,
        "retries": 0,
        "screenshots": False,
        "gesture": (
            "measured Channels hover to open (or adopt), a bounded stepped real-cursor path to "
            "close, a measured hover to reopen, then a second bounded stepped path; no posted "
            "message, no press and no operator gesture"
        ),
    }
    payload: dict = {
        "phase": "starting",
        "written_at": _now(),
        "command": "channels_opener",
        "scope": scope,
        "note": (
            "written before any cursor movement and rewritten at each stage with that stage's own "
            "facts; it never states a success the run did not observe. If the run dies below, "
            "the last written stage is what remains on disk"
        ),
    }

    # Durable BEFORE any gesture: if the run dies below, this note is what remains on disk.
    _write(report_path, payload)
    gesture_attempted = False
    try:
        windows = visible_main_windows(MAIN_CLASS)
        if len(windows) != 1:
            raise OpenerRefused(
                f"{len(windows)} visible {MAIN_CLASS} windows: this run requires exactly one and "
                "binds nothing"
            )
        actuator = Win32Actuator(allow_real_input=True)
        target = actuator.bind_target(windows[0])
        payload["bound_target"] = target.model_dump(mode="json")

        def read():
            return read_channels(actuator=actuator, target=target)

        first = read()
        payload["baseline"] = {
            "surface": first.surface.value,
            "readable": bool(first.readable),
            "adopted_or_absent": first.surface.value
            in ("absent", "settings_popup", "multiplexer_on_entry"),
        }
        # Recorded before the hover, so a crash during it still shows that a gesture was taken.
        gesture_attempted = True
        payload["gesture_attempted"] = True
        payload["phase"] = "gesturing"
        _write(report_path, payload)
        opened = _open(actuator, target, read, settle=args.settle)
        payload["opened"] = opened.model_dump(mode="json")
        if opened.outcome is not PopupOutcome.OPEN:
            payload.update(
                {
                    "phase": "open_unconfirmed",
                    "written_at": _now(),
                    "refused": (
                        "the measured Channels hover produced no readable popup: "
                        f"{opened.clause or opened.surface}"
                    ),
                    "gesture_attempted": True,
                    "popup_left_open_for_operator": surface_left_open(opened.surface),
                }
            )
            _write(report_path, payload)
            print(json.dumps(payload, indent=2))
            return 4
        opened_reading = read()
    except (OpenerRefused, AcquisitionError) as exc:
        payload.update(
            {
                "phase": "refused",
                "written_at": _now(),
                "refused": str(exc),
                "gesture_attempted": gesture_attempted,
            }
        )
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 3
    except Exception as exc:  # noqa: BLE001 — an unexpected failure is evidence, not a silent exit
        payload.update(_unexpected(exc, gesture_attempted=gesture_attempted))
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 2

    outcome = hover_outcome(first, opened_reading, baseline)
    payload.update(outcome)
    payload["phase"] = "open"
    payload["popup_left_open_for_operator"] = True
    if not outcome["ok"]:
        payload["operator_cleanup"] = (
            "the popup is readable but not the full settings surface; no dismissal path is "
            "walked and the operator may close it"
        )
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 4

    payload["gesture_attempted"] = True
    try:
        dismissal = actuator.dismiss_channels_popup(
            target=target, read=read, timeout_s=max(0.0, args.settle)
        )
    except AcquisitionError as exc:
        payload.update({"phase": "dismissal_refused", "refused": str(exc)})
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 3
    except Exception as exc:  # noqa: BLE001
        payload.update(_unexpected(exc, gesture_attempted=True))
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 2
    payload["close_1"] = dismissal.model_dump(mode="json")
    payload["popup_left_open_for_operator"] = (
        dismissal.outcome is not DismissalOutcome.ABSENT
    )
    try:
        reopen_licence(dismissal)
    except ReopenRefused as exc:
        payload.update(
            {
                "phase": "dismissal_unconfirmed",
                "refused": str(exc),
                "operator_cleanup": (
                    "the popup was not observed ABSENT: the run stops here, takes no second path "
                    "and no reopen, and the operator closes the popup"
                ),
            }
        )
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 5
    _write(report_path, payload)

    try:
        reopened_open = _open(actuator, target, read, settle=args.settle)
        payload["reopen"] = reopened_open.model_dump(mode="json")
        if reopened_open.outcome is not PopupOutcome.OPEN:
            payload.update(
                {
                    "phase": "reopen_failed",
                    "refused": (
                        "the measured Channels hover produced no readable popup on reopen: "
                        f"{reopened_open.clause or reopened_open.surface}"
                    ),
                    "popup_left_open_for_operator": surface_left_open(
                        reopened_open.surface
                    ),
                }
            )
            _write(report_path, payload)
            print(json.dumps(payload, indent=2))
            return 5
        reopened = read()
    except (OpenerRefused, AcquisitionError) as exc:
        payload.update(
            {
                "phase": "reopen_failed",
                "refused": str(exc),
                "popup_left_open_for_operator": None,
            }
        )
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 5
    except Exception as exc:  # noqa: BLE001
        payload.update(_unexpected(exc, gesture_attempted=True))
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 2
    comparison = reopen_comparison(opened_reading, reopened)
    payload["comparison"] = comparison
    payload["phase"] = "reopened_after_absence"
    _write(report_path, payload)
    if comparison["surface"] != "settings_popup":
        payload["phase"] = "reopen_unreadable"
        payload["popup_left_open_for_operator"] = True
        payload["operator_cleanup"] = (
            "the reopened surface is not the full settings popup"
        )
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 5

    try:
        final = actuator.dismiss_channels_popup(
            target=target, read=read, timeout_s=max(0.0, args.settle)
        )
    except AcquisitionError as exc:
        payload.update(
            {
                "phase": "final_dismissal_refused",
                "refused": str(exc),
                "popup_left_open_for_operator": True,
            }
        )
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 3
    except Exception as exc:  # noqa: BLE001
        payload.update(_unexpected(exc, gesture_attempted=True))
        _write(report_path, payload)
        print(json.dumps(payload, indent=2))
        return 2
    closed = final.outcome is DismissalOutcome.ABSENT
    payload["close_2"] = final.model_dump(mode="json")
    payload["phase"] = "complete" if closed and comparison["ok"] else "incomplete"
    payload["popup_left_open_for_operator"] = not closed
    payload["operator_cleanup"] = (
        "none: both bounded stepped paths produced an observed ABSENT and the popup is closed"
        if closed
        else (
            "the popup was not observed ABSENT after the second path: no third path is walked "
            "and the operator closes it"
        )
    )
    payload["limitations"] = [
        "one invocation, one geometry: no conclusion about other popups or other screens",
        (
            "the exact position at which the popup closed is not observed; only 'not closed by "
            "the end of the path' and 'closed during the bounded poll' are distinguished"
        ),
        (
            "the stepped path supports the path-versus-jump difference measured once live; it "
            "does not establish the OS mechanism"
        ),
        "the operator's cursor is left at the last path point; it is not restored",
    ]
    _write(report_path, payload)
    print(json.dumps(payload, indent=2))
    return 0 if closed and comparison["ok"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
