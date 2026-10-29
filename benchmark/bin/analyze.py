#!/usr/bin/env python3
"""Aggregate all runs into results/runs.csv, results/runs.json and results/summary.json.

Costs:
- DeepSeek: real tokens from the run's logging proxy (ds-proxy.jsonl), official deepseek-flash list price,
  peak/off-peak decided per request timestamp.
- Claude: tokens from the `result` event of the main Claude session (modelUsage, includes its subagents),
  priced at official Anthropic API list prices (what it would cost without the subscription).
"""
import csv, datetime as dt, glob, json, os, statistics as st, sys
LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# $/MTok — Anthropic list prices (platform.claude.com/docs/en/about-claude/pricing, read 2026-10-28)
CLAUDE = {
    "opus":   dict(inp=4.0, w5m=5.0, w1h=8.0, hit=0.20, out=20.0),
    "sonnet": dict(inp=2.0, w5m=2.5, w1h=4.0, hit=0.10, out=10.0),
    "haiku":  dict(inp=0.10, w5m=0.125, w1h=0.20, hit=0.01, out=0.50),
}
# $/MTok — DeepSeek list prices (api-docs.deepseek.com/quick_start/pricing, read 2026-10-28), off-peak; peak = x2
DS = {"deepseek-flash": dict(miss=0.15, hit=0.003, out=0.60), "deepseek-v4-pro": dict(miss=0.66, hit=0.022, out=1.98)}

def is_peak(ts):
    t = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    if t.weekday() >= 5: return False  # Chinese public holidays ignored (none on these dates)
    return 1 <= t.hour < 4 or 6 <= t.hour < 10

def claude_family(model):
    for k in CLAUDE:
        if k in model: return k
    return None

def claude_cost(mu):
    """mu: modelUsage dict from a result event."""
    tot = 0.0; toks = {}
    for model, u in (mu or {}).items():
        fam = claude_family(model)
        if not fam: continue
        p = CLAUDE[fam]
        w5 = u.get("cacheCreationEphemeral5mInputTokens", 0); w1 = u.get("cacheCreationEphemeral1hInputTokens", 0)
        wother = max(0, u.get("cacheCreationInputTokens", 0) - w5 - w1)
        c = (u.get("inputTokens", 0) * p["inp"] + (w5 + wother) * p["w5m"] + w1 * p["w1h"]
             + u.get("cacheReadInputTokens", 0) * p["hit"] + u.get("outputTokens", 0) * p["out"]) / 1e6
        tot += c
        t = toks.setdefault(fam, dict(input=0, cache_write=0, cache_read=0, output=0, cost=0.0))
        t["input"] += u.get("inputTokens", 0); t["cache_write"] += u.get("cacheCreationInputTokens", 0)
        t["cache_read"] += u.get("cacheReadInputTokens", 0); t["output"] += u.get("outputTokens", 0); t["cost"] += c
    return tot, toks

def last_result(path):
    res = None; n_tools = {}; ds_calls = []
    if not os.path.exists(path): return None, n_tools, ds_calls
    for line in open(path):
        try: j = json.loads(line)
        except Exception: continue
        if j.get("type") == "result": res = j
        if j.get("type") == "assistant":
            for b in j.get("message", {}).get("content", []):
                if b.get("type") == "tool_use":
                    name = b["name"]
                    if name == "Bash":
                        cmd = b.get("input", {}).get("command", "")
                        if "ds-worker" in cmd:
                            name = "Bash:ds-worker"; ds_calls.append(cmd[:200])
                    n_tools[name] = n_tools.get(name, 0) + 1
    return res, n_tools, ds_calls

def ds_cost(path):
    c = dict(miss=0, hit=0, out=0, cost=0.0, requests=0, errors=0, models=set(), server_tool_uses=0, peak_requests=0)
    if not os.path.exists(path): return c
    for line in open(path):
        r = json.loads(line); c["requests"] += 1
        if r.get("status") != 200: c["errors"] += 1; continue
        m = r.get("resp_model") or r.get("req_model"); c["models"].add(m)
        u = r.get("usage") or {}
        miss = u.get("input_tokens", 0) or 0; hit = u.get("cache_read_input_tokens", 0) or 0; out = u.get("output_tokens", 0) or 0
        p = DS.get(m, DS["deepseek-flash"]); k = 2 if is_peak(r["ts"]) else 1
        c["peak_requests"] += k == 2
        c["miss"] += miss; c["hit"] += hit; c["out"] += out
        c["cost"] += k * (miss * p["miss"] + hit * p["hit"] + out * p["out"]) / 1e6
        c["server_tool_uses"] += r.get("server_tool_uses", 0)
    c["models"] = sorted(x for x in c["models"] if x)
    return c

def run_row(mpath):
    m = json.load(open(mpath)); rd = os.path.dirname(mpath)
    res, tools, ds_calls = last_result(os.path.join(rd, "main.jsonl"))
    row = dict(run=m["run"], app=m["app"], config=m["config"], rep=m["rep"], wall_min=round(m["wall_s"] / 60, 1),
               timeout=m.get("timeout"), exit=m.get("exit_code"))
    j = m.get("judge", {})
    row.update(passed=j.get("passed"), total=j.get("total"), score=j.get("score"), started=j.get("server_started"),
               npm_ok=j.get("npm_install_ok"), pkg_root=j.get("package_json_at_root", True))
    cc, ctoks = claude_cost(res.get("modelUsage") if (res and m.get("main_is_claude")) else {})
    row["claude_api_eq_usd"] = round(cc, 4)
    for fam in ("opus", "sonnet", "haiku"):
        t = ctoks.get(fam, {})
        row[f"{fam}_tokens_total"] = sum(t.get(k, 0) for k in ("input", "cache_write", "cache_read", "output"))
        row[f"{fam}_out"] = t.get("output", 0)
        row[f"{fam}_cache_read"] = t.get("cache_read", 0)
        row[f"{fam}_cache_write"] = t.get("cache_write", 0)
        row[f"{fam}_input"] = t.get("input", 0)
    d = ds_cost(os.path.join(rd, "ds-proxy.jsonl"))
    row.update(ds_usd=round(d["cost"], 4), ds_miss=d["miss"], ds_hit=d["hit"], ds_out=d["out"], ds_requests=d["requests"],
               ds_errors=d["errors"], ds_models="|".join(d["models"]), ds_server_tools=d["server_tool_uses"], ds_peak_req=d["peak_requests"])
    row["total_usd_cash"] = row["ds_usd"]                       # what you actually pay with a subscription
    row["total_usd_api_eq"] = round(cc + d["cost"], 4)          # Claude at API list price + DeepSeek real
    workers = sorted(glob.glob(os.path.join(rd, "workers", "w*.task.md")))
    row["worker_sessions"] = len(workers)
    row["worker_resumes"] = sum(1 for w in workers if "resume-of:" in open(w).read())
    row["lead_tool_calls"] = json.dumps(tools, sort_keys=True)
    row["claude_turns"] = res.get("num_turns") if (res and m.get("main_is_claude")) else 0
    ub, ua = m.get("usage_before", {}), m.get("usage_after", {})
    row["q5h_before"], row["q5h_after"] = ub.get("five_hour"), ua.get("five_hour")
    row["q7d_before"], row["q7d_after"] = ub.get("seven_day"), ua.get("seven_day")
    row["t_start"], row["t_end"] = ub.get("t"), ua.get("t")
    row["ds_balance_before"], row["ds_balance_after"] = m.get("ds_balance_before"), m.get("ds_balance_after")
    row["result_is_error"] = bool(res and res.get("is_error")) if res else True
    return row

def main():
    rows = [run_row(p) for p in sorted(glob.glob(os.path.join(LAB, "runs", "*", "metrics.json")))]
    try: excl = json.load(open(os.path.join(LAB, "results", "excluded.json")))
    except Exception: excl = {}
    for r in rows: r["excluded"] = excl.get(r["run"], "")
    os.makedirs(os.path.join(LAB, "results"), exist_ok=True)
    json.dump(rows, open(os.path.join(LAB, "results", "runs.json"), "w"), indent=1)
    if rows:
        with open(os.path.join(LAB, "results", "runs.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    # summary per (app, config), excluding pilot runs
    groups = {}
    for r in rows:
        if str(r["rep"]).startswith("p") and "--with-pilots" not in sys.argv: continue
        if r["excluded"]: continue
        groups.setdefault((r["app"], r["config"]), []).append(r)
    summ = []
    for (app, cfg), rs in sorted(groups.items()):
        f = lambda k: [x[k] for x in rs if x[k] is not None]
        mean = lambda k: round(st.mean(f(k)), 4) if f(k) else None
        sd = lambda k: round(st.pstdev(f(k)), 4) if len(f(k)) > 1 else 0
        summ.append(dict(app=app, config=cfg, n=len(rs), score_mean=mean("score"), score_sd=sd("score"),
                         score_min=min(f("score")) if f("score") else None, wall_min=mean("wall_min"),
                         claude_api_eq_usd=mean("claude_api_eq_usd"), ds_usd=mean("ds_usd"), total_api_eq=mean("total_usd_api_eq"),
                         opus_tokens=mean("opus_tokens_total"), sonnet_tokens=mean("sonnet_tokens_total"),
                         worker_sessions=mean("worker_sessions"), worker_resumes=mean("worker_resumes")))
    json.dump(summ, open(os.path.join(LAB, "results", "summary.json"), "w"), indent=1)
    for s in summ: print(s)

if __name__ == "__main__":
    main()
