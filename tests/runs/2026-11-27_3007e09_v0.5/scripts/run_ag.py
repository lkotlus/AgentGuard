"""Static-replay driver for AgentGuard: copy a corpus into a fresh watch dir, start main.py
(--plain), wait until every 'reviewing' call has a final analyst decision and output is idle,
then SIGINT. Usage: run_ag.py <run_dir> <agent_root> <corpus_file_or_dir>..."""
import json, os, shutil, signal, subprocess, sys, time
from pathlib import Path

AG = Path(os.environ["AG_DIR"])
PY = os.environ["AG_PY"]

run = Path(sys.argv[1]).resolve(); agent_root = sys.argv[2]; srcs = [Path(p) for p in sys.argv[3:]]
corpus = run / "corpus"; mirror = run / "mirror"
if run.exists():
    sys.exit(f"{run} exists")
corpus.mkdir(parents=True)
for s in srcs:
    # keep the parent dir name (clean/poisoned or live-session-x) so file layout mirrors ADOP's corpus/
    if s.is_dir():
        shutil.copytree(s, corpus / s.name)
    else:
        (corpus / s.parent.name).mkdir(exist_ok=True)
        shutil.copy2(s, corpus / s.parent.name / s.name)
n_records = sum(1 for f in corpus.rglob("*.jsonl") for l in open(f) if l.strip())

env = dict(os.environ, OLLAMA_HOST=os.environ.get("OLLAMA_HOST", "http://<model-host>:11434"))
cmd = [PY, "main.py", "-p", str(corpus), "-a", agent_root, "-m", str(mirror), "--plain"]
(run / "command.txt").write_text(f"cd {AG} && OLLAMA_HOST={env['OLLAMA_HOST']} " + " ".join(cmd) + "\n")
t0 = time.time()
with open(run / "stdout.txt", "w") as out:
    p = subprocess.Popen(cmd, cwd=AG, env=env, stdout=out, stderr=subprocess.STDOUT)
    ev = mirror / "agentguard-events.jsonl"
    last_change, last_size = time.time(), -1
    while True:
        time.sleep(2)
        if p.poll() is not None:
            break
        size = ev.stat().st_size if ev.exists() else 0
        if size != last_size:
            last_size, last_change = size, time.time()
        events = [json.loads(l) for l in open(ev)] if ev.exists() else []
        calls = [e for e in events if e["kind"] == "call"]
        first = {(e["session_id"], e["seq"]) for e in calls if e["decision"] in ("reviewing", "suppressed") or e["source"] == "signature"}
        pending = {(e["session_id"], e["seq"]) for e in calls if e["decision"] == "reviewing"} - \
                  {(e["session_id"], e["seq"]) for e in calls if e["decision"] in ("cleared", "error") or (e["decision"] == "alert" and e["source"] == "analyst")}
        if len(first) >= n_records and not pending and time.time() - last_change > 10:
            break
        if time.time() - t0 > 3600:
            print("timeout", file=sys.stderr); break
    p.send_signal(signal.SIGINT)
    try:
        p.wait(30)
    except subprocess.TimeoutExpired:
        p.kill()
(run / "meta.json").write_text(json.dumps({"records": n_records, "wall_s": round(time.time() - t0, 1),
                                           "ollama_host": env["OLLAMA_HOST"], "returncode": p.returncode}, indent=1))
print(run, n_records, "records", round(time.time() - t0, 1), "s")
