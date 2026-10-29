#!/usr/bin/env python3
"""Run one experiment: app x config x repetition, on a clean copy, then judge it.

Usage: bin/run.py <app> <config> <rep>
Configs are defined in CONFIGS below. Results: runs/<app>-<config>-r<rep>/metrics.json
"""
import json, os, shutil, signal, socket, subprocess, sys, time, urllib.request
LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(LAB, "bin")
P = lambda *a: os.path.join(LAB, *a)

def prompt(name): return open(P("prompts", name)).read()

# kind: single (one session does everything) | lead (Claude tech lead + DeepSeek workers)
CONFIGS = {
    "A": dict(kind="single", provider="claude", model="opus"),
    "B": dict(kind="single", provider="claude", model="sonnet"),
    "C": dict(kind="single", provider="deepseek"),
    "D": dict(kind="lead", model="opus", review=False),
    "E": dict(kind="lead", model="opus", review=True),
    "F": dict(kind="lead", model="sonnet", review=True),
    "G": dict(kind="lead", model="sonnet", review=False),
    "H": dict(kind="lead", model="opus", review=True, parallel=True),
}

STRIP = ["ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION",
         "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_PID",
         "CLAUDE_EFFORT", "CLAUDE_CODE_EXECPATH", "CLAUDE_PLUGIN_DATA", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"]

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

USAGE_CACHE = os.path.join(LAB, "results", "usage-latest.json")

def oauth_usage(fresh=False, max_age=420):
    """Subscription utilization. Reads the cache written by bin/usage-poll.py (the endpoint rate-limits at 429)."""
    if not fresh:
        try:
            j = json.load(open(USAGE_CACHE))
            if time.time() - j["t"] < max_age: return j
        except Exception: pass
        return {"t": time.time(), "error": "no fresh cache"}
    try:
        tok = json.load(open(os.path.expanduser("~/.claude/.credentials.json")))["claudeAiOauth"]["accessToken"]
        r = urllib.request.Request("https://api.anthropic.com/api/oauth/usage",
                                   headers={"Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20"})
        j = json.load(urllib.request.urlopen(r, timeout=20))
        return {"t": time.time(), "five_hour": j["five_hour"]["utilization"], "seven_day": j["seven_day"]["utilization"],
                "five_hour_resets": j["five_hour"]["resets_at"], "extra_usage_enabled": j["extra_usage"]["is_enabled"]}
    except Exception as e:
        return {"t": time.time(), "error": str(e)}

def ds_balance():
    try:
        r = urllib.request.Request("https://api.deepseek.com/user/balance", headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]})
        return float(json.load(urllib.request.urlopen(r, timeout=20))["balance_infos"][0]["total_balance"])
    except Exception as e:
        return None

def kill_tree_under(path):
    """Kill leftover processes (servers started by agents) whose cwd is inside the run dir."""
    me = os.getpid(); killed = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me: continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            if cwd.startswith(path):
                os.kill(int(pid), signal.SIGKILL); killed.append(int(pid))
        except Exception: pass
    return killed

def claude_env(port):
    env = {k: v for k, v in os.environ.items() if k not in STRIP}
    env["PORT"] = str(port)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    env["BASH_DEFAULT_TIMEOUT_MS"] = "3600000"; env["BASH_MAX_TIMEOUT_MS"] = "3600000"
    env["PATH"] = BIN + ":" + env["PATH"]
    return env

COMMON_FLAGS = ["--safe-mode", "--permission-mode", "bypassPermissions", "--disallowedTools", "WebSearch WebFetch",
                "--output-format", "stream-json", "--verbose"]

def main():
    app, cfg_name, rep = sys.argv[1], sys.argv[2], sys.argv[3]
    cfg = CONFIGS[cfg_name]
    rid = f"{app}-{cfg_name}-r{rep}"
    rd = P("runs", rid)
    if os.path.exists(os.path.join(rd, "metrics.json")):
        print("already done", rid); return
    shutil.rmtree(rd, ignore_errors=True)
    ws = os.path.join(rd, "ws"); os.makedirs(ws)
    open(os.path.join(rd, "RUNNING"), "w").write(str(os.getpid()))
    with open(os.path.join(ws, "SPEC.md"), "w") as f:
        f.write(open(P("apps", app, "SPEC.md")).read() + "\n\n" + open(P("apps", "COMMON.md")).read())
    port = free_port(); proxy_port = free_port()
    meta = dict(run=rid, app=app, config=cfg_name, cfg=cfg, rep=rep, port=port)
    # logging proxy for all DeepSeek traffic of this run
    proxy = subprocess.Popen([sys.executable, os.path.join(BIN, "ds-proxy.py"), str(proxy_port)],
                             env=dict(os.environ, DS_PROXY_LOG=os.path.join(rd, "ds-proxy.jsonl")), start_new_session=True)
    time.sleep(0.5)
    env = claude_env(port)
    env["DS_RUN_DIR"] = rd; env["DS_PROXY_PORT"] = str(proxy_port)
    meta["usage_before"] = oauth_usage(); meta["ds_balance_before"] = ds_balance()
    t0 = time.time()
    out = open(os.path.join(rd, "main.jsonl"), "w"); err = open(os.path.join(rd, "main.err"), "w")
    if cfg["kind"] == "single" and cfg["provider"] == "claude":
        cmd = ["claude", "-p", prompt("builder.txt"), "--model", cfg["model"]] + COMMON_FLAGS
        meta["main_is_claude"] = True
    elif cfg["kind"] == "single":
        cmd = ["bash", "-c", f'DS_CONFIG_DIR="{rd}/ds-config" . "{BIN}/ds-env.sh"; mkdir -p "$CLAUDE_CONFIG_DIR"; exec claude "$@"', "_",
               "-p", prompt("builder.txt")] + COMMON_FLAGS
        meta["main_is_claude"] = False
    else:
        sysp = prompt("lead-common.txt") + "\n" + prompt("lead-review.txt" if cfg["review"] else "lead-noreview.txt")
        if cfg.get("parallel"): sysp += prompt("lead-parallel.txt")
        task = ("Build the web application specified in SPEC.md (in the current directory) as tech lead, delegating the "
                "implementation to developers with ds-worker. It will be graded by an automated, hidden acceptance test suite "
                "that exercises the HTTP API exactly as documented. Work fully autonomously — there is no human to answer "
                "questions. The environment variable PORT is set to a free port.")
        cmd = ["claude", "-p", task, "--model", cfg["model"], "--append-system-prompt", sysp] + COMMON_FLAGS
        meta["main_is_claude"] = True
    meta["cmd"] = [c if len(c) < 300 else c[:300] + "..." for c in cmd]
    # Each run lives in its own PID namespace (created by root via sudo, then dropped back to this user), so that an
    # agent running e.g. `pkill -f "node server.js"` cannot kill servers/agents of the other runs executing in parallel.
    # When the namespace's first process exits, everything left inside it is killed automatically.
    ns = ["sudo", "-n", "-E", "unshare", "--pid", "--fork", "--mount-proc", "--kill-child", "setpriv",
          f"--reuid={os.getuid()}", f"--regid={os.getgid()}", "--init-groups", "--", "env", f"PATH={env['PATH']}"]
    meta["pid_namespace"] = True
    p = subprocess.Popen(ns + cmd, cwd=ws, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
    try:
        p.wait(timeout=int(os.environ.get("RUN_TIMEOUT", 3 * 3600)))
        meta["timeout"] = False
    except subprocess.TimeoutExpired:
        kill_tree_under(rd); p.wait(); meta["timeout"] = True
    meta["exit_code"] = p.returncode
    meta["wall_s"] = round(time.time() - t0, 1)
    time.sleep(2)
    meta["killed_leftovers"] = kill_tree_under(rd)
    meta["usage_after"] = oauth_usage(); meta["ds_balance_after"] = ds_balance()
    proxy.terminate()
    # judge on a copy (hidden tests live outside the workspace)
    jt = time.time()
    j = subprocess.run([P("judge", ".venv", "bin", "python"), P("judge", "judge.py"), ws, app, os.path.join(rd, "judge")],
                       capture_output=True, text=True)
    meta["judge_s"] = round(time.time() - jt, 1)
    try: meta["judge"] = json.load(open(os.path.join(rd, "judge", "judge.json")))
    except Exception: meta["judge"] = {"error": j.stdout[-2000:] + j.stderr[-2000:]}
    kill_tree_under(os.path.join(rd, "judge"))
    shutil.rmtree(os.path.join(rd, "judge", "app", "node_modules"), ignore_errors=True)
    json.dump(meta, open(os.path.join(rd, "metrics.json"), "w"), indent=1)
    os.remove(os.path.join(rd, "RUNNING"))
    sc = meta["judge"].get("score")
    print(f"{rid}: score={sc} wall={meta['wall_s']}s exit={meta['exit_code']}")

if __name__ == "__main__":
    main()
