[🇮🇹 Italiano](BENCHMARK.md) · **🇬🇧 English**

# Benchmark

October 28, 2026. Claude Code 2.1.312, Claude Max 20x plan, DeepSeek `deepseek-flash` (V4.1-Flash-1017).
Raw data, scripts and hidden tests are in [`benchmark/`](../benchmark).

**Recommended setup: Opus 5.5 as tech lead + DeepSeek V4.1 Flash developers** (`/deepseek-crew`, with or without `--review`).
I also measured Sonnet 5.5 and DeepSeek alone, for comparison: their results are reported below in full.

## Method

- **6 web apps** built from a precise spec. The stack is fixed (Node 22, `npm start`, `PORT`, `DATA_DIR`).

  | app | what it does | hidden tests |
  |---|---|---|
  | bookmarks | CRUD with tags, filters, pagination, CSV | 35 |
  | kanban | accounts, tokens, shared boards, 401/403/404 rules, card ordering, WIP limit | 25 |
  | splitter | group expenses in cents, 4 split types with largest-remainder rounding, balances, greedy settle-up | 29 |
  | booking | roles, IANA time zones with DST, all-or-nothing recurrences, availability | 41 |
  | sheets | spreadsheet engine: parser, coercion, errors, cycles, row insert/delete with reference rewriting, relative/absolute copy | 90 |
  | suite | the 5 modules above in one server, each under its own path prefix | 220 |

- **Hidden acceptance tests.** Black-box HTTP tests (pytest) the agents never saw. They run on a clean copy, with a fresh
  `npm install`, a fresh data dir and a server restart to check persistence. Each suite was validated against an
  independent reference implementation (100%).
- **Same prompt for every setup.** Every session runs `claude -p --safe-mode --permission-mode bypassPermissions` with web
  tools off. Each run gets its own PID namespace, so runs executing in parallel cannot interfere.
- **Claude usage** = real token counts from the session transcripts, priced at Anthropic API list prices. This is the
  finest-grained measure of plan usage available: the plan endpoint only reports whole percentage points.
- **DeepSeek cost** = real tokens logged by a proxy, at DeepSeek list prices. The computed total matched the account balance within 1%.
- **Audit.** Every tool call of every session was checked. I excluded two runs in which a developer had read the hidden tests.

## Results

| setup | runs | hidden tests passed | perfect runs | Claude usage vs Opus alone | Claude usage (API-priced $/app) | DeepSeek $/app | avg time |
|---|---|---|---|---|---|---|---|
| Opus alone | 18 | 100% | 18/18 | 100% | 0.98 | – | 4.1 min |
| **Opus lead + DeepSeek, fast mode** | 10 | **100%** | 10/10 | **35%** | 0.28 | 0.15 | 12.2 min |
| **Opus lead + DeepSeek, `--review`** | 12 | **100%** | 12/12 | **56%** | 0.47 | 0.12 | 10.7 min |
| Sonnet alone | 18 | 99.9% | 16/18 | 30% | 0.32 | – | 2.0 min |
| Sonnet lead + DeepSeek, with review | 12 | 100% | 12/12 | 12% | 0.085 | 0.10 | 7.7 min |
| Sonnet lead + DeepSeek, no review | 5 | 100% | 5/5 | 9% | 0.052 | 0.07 | 8.5 min |
| DeepSeek alone (`ds-claude`) | 13 | 100% | 13/13 | 0% | – | 0.075 | 8.4 min |

"Claude usage vs Opus alone" is the per-app ratio averaged over the 6 apps. Times are inflated by running 5–9 benchmark
runs in parallel on a 4-vCPU machine: compare them across setups, not as absolute values.

### Per app: Claude usage (API-priced $) + DeepSeek ($)

| app | Opus alone | Opus lead, fast | Opus lead, review | Sonnet alone | Sonnet lead, review | DeepSeek alone |
|---|---|---|---|---|---|---|
| bookmarks | 0.37 | 0.17 + 0.04 | 0.26 + 0.02 | 0.13 | 0.11 + 0.03 | 0.026 |
| kanban | 0.58 | 0.19 + 0.05 | 0.38 + 0.07 | 0.16 | 0.06 + 0.05 | 0.042 |
| splitter | 0.64 | 0.19 + 0.05 | 0.40 + 0.07 | 0.16 | 0.06 + 0.03 | 0.038 |
| booking | 0.67 | 0.30 + 0.11 | 0.36 + 0.07 | 0.18 | 0.06 + 0.06 | 0.058 |
| sheets | 1.13 | 0.47 + 0.35 | 0.62 + 0.16 | 0.37 | 0.07 + 0.09 | 0.119 |
| suite | 2.51 | **0.43** + 0.36 | 0.80 + 0.32 | 0.91 | 0.16 + 0.33 | 0.193 |

The saving of the Opus lead grows with the size of the project: −55% on the smallest app, −83% on the 5-module suite.

### Plan limits

On the Max 20x plan, 1% of the 5-hour window ≈ $3.6 of API-priced usage, and 1% of the weekly limit ≈ $15.6. These were
calibrated over 13 and 3 percentage points respectively; the weekly figure is rough. Anthropic states that Max 5x and
Max 20x give 5× and 20× the Pro usage per 5-hour session, so a Pro 5-hour window ≈ $18 of API-priced usage.
The weekly Pro/Max ratio is not published.

| setup | apps per Pro 5-hour window | 5-module suites per Pro 5-hour window |
|---|---|---|
| Opus alone | ~18 | ~7 |
| Opus lead + DeepSeek, fast | ~64 | ~42 |
| Opus lead + DeepSeek, review | ~38 | ~23 |
| Sonnet alone | ~57 | ~20 |
| Sonnet lead + DeepSeek, review | ~210 | ~110 |

## Observations

- **Review costs almost as much as doing.** Opus 5.5 writes code very efficiently. Verifying a delivery means re-reading
  the spec, the plan and the code, which brings Opus's usage from 35% to 56% of Opus alone. In my tests the specs were
  precise and quality was already 100% without review.
- **Caching does the heavy lifting on DeepSeek:** 98–99% of developer input tokens were cache hits ($0.003 per million).
- **Claude Code's `/cost` is about 40× off with DeepSeek**, because it applies Claude prices. The token counts in the
  `stream-json` result are exact, and `ds-cost` reads them.
- **Developers with full permissions need a sandbox.** I saw `pkill -f "node server.js"` kill other projects'
  processes, files written to wrongly-cased paths outside the project and, in 2 of 12 fast-mode runs, a developer
  searching the filesystem for the hidden tests. Those two runs are excluded.

## Limits

- Every spec was precise and complete. I did not measure vague "vibe coding" requests, long-lived codebases or
  debugging sessions: those are the cases where the lead's judgement should matter most.
- 1 to 3 repetitions per setup and app (93 runs). The third repetition of the DeepSeek-based setups was not run.
- The UI was only checked for being served (`GET /` returns HTML), not tested in a browser.
- All DeepSeek traffic happened off-peak. At peak hours the DeepSeek costs above double.
