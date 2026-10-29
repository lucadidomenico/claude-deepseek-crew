#!/usr/bin/env python3
"""Markdown tables for REPORT.md from results/runs.json + quota calibration from results/usage-poll.jsonl.
Writes results/tables.md and results/calibration.json."""
import json, os, statistics as st, subprocess, sys
LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = lambda *a: os.path.join(LAB, "results", *a)
allrows = json.load(open(R("runs.json")))
rows = [r for r in allrows if not str(r["rep"]).startswith("p") and not r.get("excluded")]
APPS = ["bookmarks", "kanban", "splitter", "booking", "sheets", "suite"]
CFG = {"A": "Opus 5.5 solo", "B": "Sonnet 5.5 solo", "C": "DeepSeek Flash solo", "D": "Opus lead → DS, no review",
       "E": "Opus lead → DS + review", "F": "Sonnet lead → DS + review", "G": "Sonnet lead → DS, no review", "H": "Opus lead → DS paralleli + review"}

# ---- quota calibration: $ API-equivalent per 1 point of utilization, from deltas between polls ----
polls = [json.loads(l) for l in open(R("usage-poll.jsonl"))]
polls = [p for p in polls if "error" not in p]
def spend(t0, t1):
    out = subprocess.run([sys.executable, os.path.join(LAB, "bin", "claude-usage-timeline.py"), str(t0), str(t1)], capture_output=True, text=True).stdout
    return sum(json.loads(l)["api_eq_usd"] for l in out.splitlines() if l.strip())
cal = {}
if len(polls) >= 2:
    # 5h: use the longest stretch inside one window (same resets_at)
    best = None
    for i, p in enumerate(polls):
        for q in polls[i + 1:]:
            if q["five_hour_resets"][:16] == p["five_hour_resets"][:16] and q["five_hour"] > p["five_hour"]:
                if not best or (q["t"] - p["t"]) > (best[1]["t"] - best[0]["t"]): best = (p, q)
    if best:
        p, q = best; s = spend(p["t"], q["t"])
        cal["five_hour"] = dict(t0=p["t"], t1=q["t"], pct_delta=q["five_hour"] - p["five_hour"], api_eq_usd=round(s, 2),
                                usd_per_pct=round(s / (q["five_hour"] - p["five_hour"]), 2))
    p, q = polls[0], polls[-1]
    if q["seven_day"] > p["seven_day"]:
        s = spend(p["t"], q["t"])
        cal["seven_day"] = dict(t0=p["t"], t1=q["t"], pct_delta=q["seven_day"] - p["seven_day"], api_eq_usd=round(s, 2),
                                usd_per_pct=round(s / (q["seven_day"] - p["seven_day"]), 2))
json.dump(cal, open(R("calibration.json"), "w"), indent=1)
k5 = cal.get("five_hour", {}).get("usd_per_pct"); k7 = cal.get("seven_day", {}).get("usd_per_pct")

def m(xs): return st.mean(xs) if xs else None
def f2(x, d=2): return "–" if x is None else f"{x:.{d}f}"
out = []
out.append("## Qualità e costi per app e configurazione (media sulle ripetizioni)\n")
out.append("| app | cfg | n | test passati (media, min) | tempo min | Claude $ eq. API | DeepSeek $ reali | worker (sessioni/resume) |")
out.append("|---|---|---|---|---|---|---|---|")
for app in APPS:
    for c in CFG:
        rs = [r for r in rows if r["app"] == app and r["config"] == c]
        if not rs: continue
        sc = [r["score"] for r in rs if r["score"] is not None]
        out.append(f"| {app} | {c} | {len(rs)} | {100*m(sc):.1f}% ({100*min(sc):.0f}%) | {f2(m([r['wall_min'] for r in rs]),1)} | "
                   f"{f2(m([r['claude_api_eq_usd'] for r in rs]),3)} | {f2(m([r['ds_usd'] for r in rs]),3)} | "
                   f"{f2(m([r['worker_sessions'] for r in rs]),1)}/{f2(m([r['worker_resumes'] for r in rs]),1)} |")
out.append("\n## Sintesi per configurazione (tutte le app)\n")
out.append("| cfg | descrizione | run | test passati | run perfetti | Claude $ eq. medio | vs A | DeepSeek $ medio | % 5h Max20x | % 5h Pro | run per finestra 5h Pro | tempo medio |")
out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
base = {app: m([r["claude_api_eq_usd"] for r in rows if r["app"] == app and r["config"] == "A"]) for app in APPS}
for c, desc in CFG.items():
    rs = [r for r in rows if r["config"] == c]
    if not rs: continue
    sc = [r["score"] for r in rs if r["score"] is not None]
    ratio = [r["claude_api_eq_usd"] / base[r["app"]] for r in rs if base.get(r["app"])]
    cl = m([r["claude_api_eq_usd"] for r in rs])
    p5 = cl / k5 if (k5 and cl is not None) else None
    pro = p5 * 20 if p5 is not None else None
    out.append(f"| {c} | {desc} | {len(rs)} | {100*m(sc):.1f}% | {sum(1 for x in sc if x == 1)}/{len(sc)} | {f2(cl,3)} | "
               f"{f2(100*m(ratio),0)}% | {f2(m([r['ds_usd'] for r in rs]),3)} | {f2(p5,2)} | {f2(pro,1)} | "
               f"{'∞' if pro == 0 else f2(100/pro if pro else None,0)} | {f2(m([r['wall_min'] for r in rs]),1)} |")
out.append(f"\nCalibrazione quota (Max 20x): 1% finestra 5h ≈ ${f2(k5)} eq. API; 1% settimanale ≈ ${f2(k7)} eq. API "
           f"(dettagli in results/calibration.json). Pro = Max 20x / 20 per finestra 5h (rapporto pubblicato da Anthropic); Max 5x = /4.")
open(R("tables.md"), "w").write("\n".join(out) + "\n")
print("\n".join(out))
