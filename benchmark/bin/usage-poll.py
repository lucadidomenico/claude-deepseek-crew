#!/usr/bin/env python3
"""Every 5 minutes: subscription utilization (5h / 7d) + DeepSeek balance -> results/usage-poll.jsonl"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("run", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py"))
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "usage-poll.jsonl")
os.makedirs(os.path.dirname(out), exist_ok=True)
while True:
    u = run.oauth_usage(fresh=True); u["ds_balance"] = run.ds_balance()
    open(out, "a").write(json.dumps(u) + "\n")
    if "error" not in u:
        json.dump(u, open(run.USAGE_CACHE + ".tmp", "w")); os.replace(run.USAGE_CACHE + ".tmp", run.USAGE_CACHE)
    time.sleep(180 if "error" not in u else 60)
