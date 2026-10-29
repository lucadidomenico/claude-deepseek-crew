#!/usr/bin/env python3
"""Hidden acceptance judge. Usage: judge.py <workspace> <app> <outdir>
Copies the workspace (without node_modules/data/.git) to <outdir>/app, runs npm install, runs the hidden pytest suite.
Writes <outdir>/judge.json."""
import json, os, shutil, subprocess, sys, time, xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.abspath(__file__))
ws, app, out = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3])
os.makedirs(out, exist_ok=True)
dst = os.path.join(out, "app")
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(ws, dst, symlinks=True, ignore=shutil.ignore_patterns("node_modules", ".git", "data", "*.db", "*.sqlite", "*.sqlite3", "*.db-*"))
res = {"app": app, "ws": ws, "ts": time.time()}
# find project root: package.json at root (contract) or a single sub-dir with package.json (lenient, flagged)
root = dst
if not os.path.exists(os.path.join(dst, "package.json")):
    cands = [d for d in os.listdir(dst) if os.path.exists(os.path.join(dst, d, "package.json"))]
    res["package_json_at_root"] = False
    if len(cands) == 1: root = os.path.join(dst, cands[0])
else: res["package_json_at_root"] = True
t0 = time.time()
try:
    p = subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=root, capture_output=True, text=True, timeout=420)
    res["npm_install_ok"] = p.returncode == 0; res["npm_install_log"] = (p.stdout + p.stderr)[-3000:]
except Exception as e:
    res["npm_install_ok"] = False; res["npm_install_log"] = str(e)
res["npm_install_s"] = round(time.time() - t0, 1)
modules = ["bookmarks", "kanban", "splitter", "booking", "sheets"] if app == "suite" else [app]
passed, failed = [], []
t0 = time.time()
for mod in modules:
    prefix = f"/{mod}" if app == "suite" else ""
    env = dict(os.environ, JUDGE_APP_DIR=root, JUDGE_OUT=out, JUDGE_PREFIX=prefix)
    junit = os.path.join(out, f"junit-{mod}.xml")
    try:
        p = subprocess.run([os.path.join(HERE, ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir",
                            os.path.join(HERE, "tests"), os.path.join(HERE, "tests", mod), f"--junitxml={junit}"],
                           cwd=os.path.join(HERE, "tests"), env=env, capture_output=True, text=True, timeout=900)
        open(os.path.join(out, f"pytest-{mod}.txt"), "w").write(p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        res.setdefault("pytest_timeout", []).append(mod)
    if os.path.exists(junit):
        for tc in ET.parse(junit).getroot().iter("testcase"):
            name = (f"{mod}::" if app == "suite" else "") + tc.get("name")
            (failed if (tc.find("failure") is not None or tc.find("error") is not None) else passed).append(name)
res["pytest_s"] = round(time.time() - t0, 1)
res.update(total=len(passed) + len(failed), passed=len(passed), failed_tests=failed, score=round(len(passed) / max(1, len(passed) + len(failed)), 4))
if app == "suite":
    res["per_module"] = {m: dict(passed=sum(1 for x in passed if x.startswith(m + "::")), failed=sum(1 for x in failed if x.startswith(m + "::"))) for m in modules}
# server started at all?
res["server_started"] = not any(n.endswith("test_index_html") for n in failed) and len(passed) > 0
json.dump(res, open(os.path.join(out, "judge.json"), "w"), indent=1)
print(json.dumps({k: res[k] for k in ("app", "passed", "total", "score", "npm_install_ok", "server_started")}))
