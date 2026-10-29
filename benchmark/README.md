**🇮🇹 Italiano** · [🇬🇧 English](README.en.md)

# Harness del benchmark

Tutto quello che serve per riprodurre [docs/BENCHMARK.md](../docs/BENCHMARK.md).

- `apps/<app>/SPEC.md` + `apps/COMMON.md`: le specifiche date agli agenti (in inglese, come i prompt).
- `judge/tests/<app>/`: test di accettazione nascosti (pytest, HTTP black-box). `judge/judge.py` valuta un workspace.
- `judge/reference/<app>/`: implementazioni di riferimento usate per validare i test (100% su tutte le suite).
- `prompts/`: prompt dell'agente singolo e prompt del tech lead (comune, review, senza review, parallelo).
- `bin/run.py <app> <config> <rip>`: un run su una copia pulita, poi la valutazione. Le configurazioni A–H sono definite in cima al file.
- `bin/matrix.py`: esegue molte configurazioni in parallelo, con controlli su quota del piano, saldo DeepSeek e fasce di punta DeepSeek.
- `bin/ds-proxy.py`: proxy che registra il traffico DeepSeek (modello e token di ogni richiesta).
- `bin/analyze.py`, `bin/audit.py`, `bin/report_tables.py`: aggregazione, audit dei transcript, tabelle.
- `results/`: dati grezzi per run (`runs.csv`, `runs.json`), rilevazioni della quota, calibrazione, audit, run esclusi.

```bash
export DEEPSEEK_API_KEY=...            # mai ANTHROPIC_API_KEY: le sessioni Claude usano il tuo login di Claude Code
uv venv judge/.venv && VIRTUAL_ENV=judge/.venv uv pip install pytest requests
python3 bin/usage-poll.py &            # quota del piano (5 ore / settimana) + saldo DeepSeek ogni 3 minuti
python3 bin/run.py kanban D 1          # Opus lead + sviluppatori DeepSeek sull'app kanban
python3 bin/matrix.py --apps bookmarks,kanban --configs A,D,E --reps 1,2 --jobs 4
python3 bin/analyze.py && python3 bin/audit.py && python3 bin/report_tables.py
```

`run.py` isola ogni run in un PID namespace con `sudo -n unshare`. Senza sudo, togli quel prefisso e lancia un run alla volta.
Gli script presumono che l'harness stia in una cartella sua. I test nascosti devono restare fuori dai workspace degli agenti;
in una configurazione più rigorosa non dovrebbero nemmeno essere leggibili dall'utente con cui girano gli agenti.
