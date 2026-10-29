#!/usr/bin/env python3
"""All Claude (subscription) token usage of this machine's Claude Code sessions in a time window, from the JSONL
transcripts in ~/.claude/projects (main sessions + subagents), priced at API list prices.
Used to calibrate: subscription % consumed vs API-equivalent dollars.
Usage: claude-usage-timeline.py <from_epoch> <to_epoch> [bucket_seconds]"""
import glob, json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import CLAUDE, claude_family
t0, t1 = float(sys.argv[1]), float(sys.argv[2]); bucket = int(sys.argv[3]) if len(sys.argv) > 3 else 0
seen = {}; 
for f in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True):
    try:
        if os.path.getmtime(f) < t0: continue
    except OSError: continue
    for line in open(f, errors="replace"):
        if '"usage"' not in line: continue
        try: j = json.loads(line)
        except Exception: continue
        m = j.get("message") or {}
        if j.get("type") != "assistant" or "usage" not in m: continue
        ts = dt.datetime.fromisoformat(j["timestamp"].replace("Z", "+00:00")).timestamp()
        if not (t0 <= ts < t1): continue
        fam = claude_family(m.get("model", ""))
        if not fam: continue
        key = (m.get("id"), j.get("requestId"))
        seen[key] = (ts, fam, m["usage"], f)       # last entry per message id wins (streamed duplicates)
rows = {}
for ts, fam, u, f in seen.values():
    p = CLAUDE[fam]; cc = u.get("cache_creation") or {}
    w1 = cc.get("ephemeral_1h_input_tokens", 0); w5 = u.get("cache_creation_input_tokens", 0) - w1
    cost = (u.get("input_tokens", 0) * p["inp"] + w5 * p["w5m"] + w1 * p["w1h"] + u.get("cache_read_input_tokens", 0) * p["hit"]
            + u.get("output_tokens", 0) * p["out"]) / 1e6
    b = int(ts // bucket * bucket) if bucket else 0
    exp = "-deepseek-opus-runs-" in f or "/deepseek-opus/runs/" in f
    r = rows.setdefault((b, fam, "experiment" if exp else "orchestrator"), dict(cost=0.0, msgs=0, out=0))
    r["cost"] += cost; r["msgs"] += 1; r["out"] += u.get("output_tokens", 0)
for (b, fam, who), r in sorted(rows.items()):
    print(json.dumps(dict(bucket=b, model=fam, who=who, api_eq_usd=round(r["cost"], 4), messages=r["msgs"], output=r["out"])))
