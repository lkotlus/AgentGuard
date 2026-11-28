#!/bin/bash
# Runs the v0.5-comparable static replays for each AgentGuard commit given.
set -u
S=/Users/<user>/scratch/agentguard-v08-run-2026-11-27; V5=/Users/<user>/scratch/agentguard-evidence-2026-11-24/AgentGuard/tests/runs/2026-11-07_3007e09_v0.5
export OLLAMA_HOST=http://<model-host>:11434 AG_PY=$S/venv/bin/python
ADOP=$S/adop-cyse
for C in "$@"; do
  export AG_DIR=$S/ag-$C; O=$S/out/$C; mkdir -p $O
  (cd $ADOP && $AG_PY -m adop_testbed.scripts.reset_testbed)
  for r in 1 2 3; do $AG_PY $S/scripts/run_ag.py $O/reference-r$r $ADOP/testbed-repo $ADOP/corpus/clean $ADOP/corpus/poisoned; done
  for r in 1 2; do $AG_PY $S/scripts/run_ag.py $O/archived-18-sessions-r$r $ADOP/testbed-repo $V5/archived-18-sessions-r1/corpus/live-session-*; done
  $AG_PY $S/scripts/run_ag.py $O/live-3-sessions-replay $ADOP/testbed-repo $V5/live-3-sessions/corpus/live-session-*
  echo "DONE $C $(date)"
done
