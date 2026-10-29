[🇮🇹 Italiano](README.md) · **🇬🇧 English**

# Benchmark harness

Everything needed to reproduce [docs/BENCHMARK.en.md](../docs/BENCHMARK.en.md).

- `apps/<app>/SPEC.md` + `apps/COMMON.md`: the specs given to the agents.
- `judge/tests/<app>/`: hidden acceptance tests (pytest, black-box HTTP). `judge/judge.py` grades a workspace.
- `judge/reference/<app>/`: reference implementations used to validate the tests (100% on all suites).
- `prompts/`: builder prompt and tech-lead prompts (common, review, no-review, parallel).
- `bin/run.py <app> <config> <rep>`: one run on a clean copy, then grading. Configs A–H are defined at the top of the file.
- `bin/matrix.py`: runs many configurations in parallel, with guards on plan usage, DeepSeek balance and DeepSeek peak hours.
- `bin/ds-proxy.py`: logging proxy for DeepSeek traffic (model and tokens of every request).
- `bin/analyze.py`, `bin/audit.py`, `bin/report_tables.py`: aggregation, transcript audit, tables.
- `results/`: raw per-run data (`runs.csv`, `runs.json`), plan-usage polling, calibration, audit, excluded runs.

```bash
export DEEPSEEK_API_KEY=...            # never ANTHROPIC_API_KEY: Claude sessions use your Claude Code login
uv venv judge/.venv && VIRTUAL_ENV=judge/.venv uv pip install pytest requests
python3 bin/usage-poll.py &            # plan usage (5h / weekly) + DeepSeek balance every 3 minutes
python3 bin/run.py kanban D 1          # Opus lead + DeepSeek developers on the kanban app
python3 bin/matrix.py --apps bookmarks,kanban --configs A,D,E --reps 1,2 --jobs 4
python3 bin/analyze.py && python3 bin/audit.py && python3 bin/report_tables.py
```

`run.py` isolates each run in a PID namespace with `sudo -n unshare`. Without sudo, remove that prefix and run one job at a time.
The scripts assume the harness lives in its own directory. The hidden tests must stay outside the agents' workspaces;
in a stricter setup they should not even be readable by the user the agents run as.
