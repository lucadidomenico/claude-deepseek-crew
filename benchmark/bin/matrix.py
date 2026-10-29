#!/usr/bin/env python3
"""Run the experiment matrix with N parallel slots and safety guards.

Usage: bin/matrix.py --apps a,b --configs A,B --reps 1,2,3 [--jobs 3] [--max-weekly 50] [--min-ds-balance 1]
Order: rep-major, so every (app, config) gets its 1st repetition before any gets its 2nd (spreads reps over time).
Guards (checked before starting each run):
  - weekly subscription utilization >= --max-weekly  -> stop starting Claude runs (DeepSeek-only runs continue)
  - 5h utilization >= 90                               -> wait for the 5h window reset before starting Claude runs
  - DeepSeek balance < --min-ds-balance               -> stop starting runs that use DeepSeek
"""
import argparse, glob, datetime as dt, importlib.util, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); LAB = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("run", os.path.join(HERE, "run.py")); run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)

ap = argparse.ArgumentParser()
ap.add_argument("--apps"); ap.add_argument("--configs"); ap.add_argument("--reps", default="1,2,3")
ap.add_argument("--jobs", type=int, default=3); ap.add_argument("--max-weekly", type=float, default=50)
ap.add_argument("--min-ds-balance", type=float, default=1.0)
ap.add_argument("--max-ds-jobs", type=int, default=4, help="max runs using DeepSeek at the same time (budget control)")
ap.add_argument("--allow-peak", action="store_true", help="start DeepSeek runs also during/just before DeepSeek peak hours")
a = ap.parse_args()
queue = [(app, c, r) for r in a.reps.split(",") for c in a.configs.split(",") for app in a.apps.split(",")]
def busy(q):
    rd = os.path.join(LAB, "runs", f"{q[0]}-{q[1]}-r{q[2]}")
    if os.path.exists(os.path.join(rd, "metrics.json")): return True
    for f in ("RUNNING",):
        try: os.kill(int(open(os.path.join(rd, f)).read()), 0); return True
        except Exception: pass
    # legacy: started before the RUNNING marker existed -> look for a live run.py with this id
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                cl = [x for x in open(f"/proc/{pid}/cmdline").read().split("\0") if x]
                if any(x.endswith("run.py") for x in cl) and cl[-3:] == list(q): return True
            except Exception: pass
    return False
queue = [q for q in queue if not busy(q)]
uses_claude = lambda c: not (run.CONFIGS[c]["kind"] == "single" and run.CONFIGS[c]["provider"] == "deepseek")
uses_ds = lambda c: not (run.CONFIGS[c]["kind"] == "single" and run.CONFIGS[c]["provider"] == "claude")
def near_peak(margin_min=40):
    """DeepSeek peak (x2 price): 01-04 and 06-10 UTC Mon-Fri. True if now is peak or peak starts within margin."""
    for m in (0, margin_min):
        t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=m)
        if t.weekday() < 5 and (1 <= t.hour < 4 or 6 <= t.hour < 10): return True
    return False
log = open(os.path.join(LAB, "logs", "matrix.log"), "a")
def L(msg):
    s = f"{dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds')}Z {msg}"; print(s, flush=True); log.write(s + "\n"); log.flush()
L(f"start: {len(queue)} runs, jobs={a.jobs}")
running = {}
while queue or running:
    for k, p in list(running.items()):
        if p.poll() is not None: L(f"done {k} rc={p.returncode}"); del running[k]
    def live_runs():
        n = 0
        for f in glob.glob(os.path.join(LAB, "runs", "*", "RUNNING")):
            try: os.kill(int(open(f).read()), 0); n += 1
            except Exception: pass
        return n
    def live_ds_runs():
        n = 0
        for f in glob.glob(os.path.join(LAB, "runs", "*", "RUNNING")):
            try:
                os.kill(int(open(f).read()), 0)
                if uses_ds(os.path.basename(os.path.dirname(f)).split("-")[1]): n += 1
            except Exception: pass
        return n
    if queue and len(running) < a.jobs and live_runs() < a.jobs:
        u = run.oauth_usage(); bal = run.ds_balance()
        pick = None
        for q in queue:
            c = q[1]
            if uses_claude(c):
                if u.get("seven_day") is not None and u["seven_day"] >= a.max_weekly: continue
                if u.get("five_hour") is not None and u["five_hour"] >= 90: continue
            if uses_ds(c) and bal is not None and bal < a.min_ds_balance: continue
            if uses_ds(c) and not a.allow_peak and near_peak(): continue
            if uses_ds(c) and live_ds_runs() >= a.max_ds_jobs: continue
            pick = q; break
        if pick is None:
            blocked_forever = all((uses_claude(q[1]) and (u.get("seven_day") or 0) >= a.max_weekly) or
                                  (uses_ds(q[1]) and bal is not None and bal < a.min_ds_balance) for q in queue)
            if blocked_forever and not running and not near_peak():
                L(f"guards block all remaining runs (usage={u}, ds_balance={bal}); remaining={queue}"); break
            time.sleep(60); continue
        queue.remove(pick)
        k = f"{pick[0]}-{pick[1]}-r{pick[2]}"
        lf = open(os.path.join(LAB, "logs", f"run-{k}.log"), "w")
        running[k] = subprocess.Popen([sys.executable, os.path.join(HERE, "run.py"), *pick], stdout=lf, stderr=subprocess.STDOUT)
        L(f"start {k} (5h={u.get('five_hour')} 7d={u.get('seven_day')} ds=${bal})")
        time.sleep(5)
    else:
        time.sleep(10)
L("matrix finished")
