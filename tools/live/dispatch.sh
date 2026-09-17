#!/usr/bin/env bash
# Dispatch one in-repo probe into the interactive session, and return when the probe is done.
#
# **Why a dispatcher at all.** The agent's shell is session 0; UDOP is session 1. Every probe
# that touches the application has to be *started in* session 1, so it goes through
# `task_run.py` (see its docstring for the pythonw/no-console rule) and the scheduled task
# named below.
#
# **Why it polls instead of sleeping.** The probe's own log closes with `=== exit=<code> ===`.
# Sleeping a fixed time after the run is what a *previous* version did, and it made a 24 s run
# look like a two-minute stall: the tool-call timer showed the sleep, not the run, and nobody
# watching the screen could tell the two apart. This returns when the run returns; a hang is
# visible as a timeout with the log printed.
#
# Usage:  ./dispatch.sh <probe.py> [args...]
#         PROBE_TIMEOUT_S=900 ./dispatch.sh -m udv_echo_process.cli acquire sweep --seconds 12 --rungs 1,2
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="$REPO/outputs/live"
TASK="${LIVE_TASK_NAME:-hermes_gui_probe}"

# Two forms: a probe file, or `-m <module>` for the installed commands. `-m` takes its module
# as the next argument, so typing it the way it reads works.
if [ "${1:-}" = "-m" ]; then
  probe="-m ${2:?usage: dispatch.sh -m <module> [args...]}"
  shift 2
else
  probe="${1:?usage: dispatch.sh <probe.py> [args...] | -m <module> [args...]}"
  shift
fi
mkdir -p "$OUT"

printf '%s' "$probe" > "$OUT/task_target.txt"
printf '%s' "$*" > "$OUT/task_args.txt"
# The same slug rule as task_run.py: `-m udv_echo_process.cli acquire-status` -> task-udv_echo_process.cli.log
slug=$(printf '%s' "$probe" | sed 's/^-m //; s/[^A-Za-z0-9_.-]/-/g')
log="$OUT/task-$slug.log"
rm -f "$log"

if ! schtasks /query /tn "$TASK" >/dev/null 2>&1; then
  echo "no scheduled task '$TASK' on this machine — create it with the command in tools/live/README.md"
  exit 2
fi
schtasks /run /tn "$TASK" >/dev/null 2>&1 || { echo "could not start the task '$TASK'"; exit 2; }

limit="${PROBE_TIMEOUT_S:-600}"
waited=0
while [ "$waited" -lt "$limit" ]; do
  if [ -f "$log" ] && grep -q '^=== exit=' "$log" 2>/dev/null; then
    break
  fi
  sleep 2
  waited=$((waited + 2))
done

if [ "$waited" -ge "$limit" ]; then
  echo "--- $probe: no exit line after ${limit}s (the probe may be wedged) ---"
else
  echo "--- $probe: finished in ${waited}s of polling ---"
fi
cat "$log" 2>/dev/null || echo "(no log at $log)"
