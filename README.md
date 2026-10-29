**🇮🇹 Italiano** · [🇬🇧 English](README.en.md)

![Opus pianifica, una crew DeepSeek scrive il codice](docs/banner.png)

# claude-deepseek-crew

**Opus pianifica. DeepSeek scrive il codice. Tu risparmi il 65% della quota Claude del tuo abbonamento.**

Quando chiedi a Claude Code di sviluppare qualcosa, la maggior parte della quota non se ne va nel ragionamento ma nel
lavoro manuale: scrivere file, rileggerli, lanciare i test, correggere, rilanciare. claude-deepseek-crew divide il
lavoro in due. **Opus 5.5 fa il tech lead**: capisce la richiesta, scrive il piano e controlla il risultato.
**Gli sviluppatori sono sessioni di Claude Code che girano su DeepSeek V4.1 Flash**, un modello che costa una frazione
di centesimo per migliaio di righe, e fanno tutto il resto.

Il risultato, misurato su 6 app con test nascosti: stessa qualità di Opus da solo, un terzo della quota del piano e
qualche centesimo di DeepSeek.

| | Opus fa tutto | **Opus lead + crew DeepSeek** |
|---|---|---|
| Test di accettazione nascosti superati | 100% | **100%** |
| Quota Claude consumata (limiti del tuo piano) | 100% | **35%  (−65%)** |
| Costo aggiuntivo | – | ~$0.15 di DeepSeek per app |
| Sull'app più grande (5 moduli, 220 test) | 100% | **17%  (−83%)** |

<sub>Benchmark: 6 web app sviluppate a partire da una specifica, valutate con test di accettazione nascosti che gli agenti non hanno mai visto, più ripetizioni per ogni configurazione.
Quota Claude misurata dai token reali. Dati completi e metodo: [docs/BENCHMARK.md](docs/BENCHMARK.md).</sub>

## Come funziona

```
tu ──► Opus (la tua sessione di Claude Code, sul tuo piano)
         │  1. legge la richiesta e il repository
         │  2. scrive PLAN.md: struttura, dati, regole, elenco dei compiti
         │  3. affida i compiti con ds-worker
         ▼
       sviluppatore DeepSeek (Claude Code su DeepSeek, sul tuo account DeepSeek)
         │  scrive il codice, lancia i test, corregge
         │  restituisce un report: file toccati, come ha verificato, cosa resta aperto
         ▼
       Opus legge il report ─► accetta, oppure rimanda indietro le correzioni
         │
tu ◄─────┘  riepilogo finale: cosa è stato sviluppato, come è stato verificato, quanto è costato
```

Lo sviluppatore non è un altro programma: è **lo stesso Claude Code**, con gli stessi strumenti (lettura e scrittura di
file, terminale, test), ma collegato all'endpoint compatibile Anthropic di DeepSeek invece che ai server Anthropic. Gira
nella cartella del tuo progetto, con una configurazione separata che non contiene il tuo login Claude.

Tu parli solo con Opus, come sempre. Il comando `/deepseek-crew` gli dice di comportarsi da tech lead: non scrive codice
applicativo, delega.

## Perché si risparmia

Quando lavora da solo, Opus spende la maggior parte dei token per implementare: generare il codice, rileggere i file,
interpretare l'output dei test, iterare. Con la crew quella parte la paga DeepSeek. Opus spende token solo per capire,
pianificare e leggere i report, che è il lavoro in cui un modello di punta fa davvero la differenza.

Per questo **il risparmio cresce con la dimensione del lavoro**: −55% sull'app più piccola, −83% sulla suite a 5 moduli.
Al contrario, su un compito minuscolo (una riga da correggere) il costo fisso del lead, che deve comunque leggere e
pianificare, annulla il risparmio: lì conviene usare Claude Code normalmente.

DeepSeek costa poco anche per un altro motivo: Claude Code rimanda spesso lo stesso contesto, e DeepSeek lo recupera dalla
cache nel 98% dei casi a $0.003 per milione di token. Un'app intera costa pochi centesimi.

## Due modalità

| | modalità veloce (predefinita) | `--review` |
|---|---|---|
| Cosa fa Opus | legge i report degli sviluppatori e si fida | lancia i test, prova l'app, legge il codice critico e rimanda i problemi |
| Quota Claude rispetto a Opus da solo | **35%** | 56% |
| Test nascosti superati nel benchmark | 100% | 100% |

La review costa quasi quanto il lavoro stesso, perché per verificare Opus deve rileggere specifica, piano e codice.
Nei miei test le specifiche erano precise e la qualità era già al 100% senza review. Usa `--review` quando la richiesta
è ambigua o il codice è delicato e vuoi un secondo paio d'occhi prima di accettarlo.

## Quando conviene

- **Sì:** app o funzionalità nuove di una certa dimensione, con requisiti chiari o che Opus può rendere chiari nel piano.
  Più il lavoro è grande, più risparmi.
- **No:** correzioni di poche righe, domande sul codice, esplorazioni veloci. Lì usa Claude Code normale.
- **Non ancora misurato:** richieste vaghe, codebase grandi e di lunga data, sessioni di debugging. Probabilmente
  funziona, ma non ho numeri.
- **Tempi:** la crew è più lenta. Nel benchmark un'app richiedeva in media 12 minuti contro 4 di Opus da solo (tempi
  gonfiati da molti run in parallelo sulla stessa macchina). Risparmi quota, non tempo.

## Si parte in 2 minuti

Servono [Claude Code](https://code.claude.com), Python 3 e una [chiave API DeepSeek](https://platform.deepseek.com/api_keys) con qualche dollaro di credito.

**Il modo più semplice:** apri Claude Code e incolla il prompt di [INSTALLA_CON_CLAUDE.md](INSTALLA_CON_CLAUDE.md).
Claude controlla i requisiti, installa tutto, ti fa salvare la chiave DeepSeek senza che passi dalla chat e lancia il test.

**A mano:**

```bash
git clone https://github.com/lucadidomenico/claude-deepseek-crew.git
cd claude-deepseek-crew
./install.sh --test     # se manca la chiave DeepSeek ti dice come salvarla, poi rilancialo
```

`--test` fa una chiamata minima a DeepSeek (circa $0.002) e stampa `TEST SUPERATO`.

## Il primo lavoro

Apri Claude Code nel tuo progetto, scegli Opus e assegna il lavoro:

```
/model opus
/deepseek-crew sviluppa l'app descritta in SPEC.md
```

Opus legge `SPEC.md` e il repository, scrive `PLAN.md` e lancia uno o più sviluppatori. Mentre lavorano vedi Opus in
attesa del comando `ds-worker`: ogni sviluppatore impiega da pochi minuti a mezz'ora. Alla fine Opus ti riporta cosa è
stato sviluppato, come è stato verificato, cosa resta aperto e quanto è costato su DeepSeek.

Con la review:

```
/deepseek-crew --review sviluppa l'app descritta in SPEC.md
```

Non serve una specifica scritta: puoi descrivere il lavoro direttamente nel comando. Più la richiesta è precisa, meglio
lavorano gli sviluppatori.

## Cosa contiene

| | |
|---|---|
| `/deepseek-crew` | Skill di Claude Code: Opus diventa tech lead e delega a DeepSeek. Con `--review` Opus verifica ogni consegna. |
| `ds-worker` | Il comando che Opus usa per delegare: un compito → una sessione Claude Code su DeepSeek → un report. Puoi usarlo anche tu: `ds-worker "aggiungi la paginazione a /api/items, con i test"`. Con `--resume w01 "..."` dai altro lavoro allo stesso sviluppatore, che ricorda cosa ha fatto. |
| `ds-worker-batch` | Più compiti indipendenti in parallelo, su file diversi. |
| `ds-cost` | Quanto sono costati davvero gli sviluppatori DeepSeek. Il `/cost` di Claude Code usa i prezzi Claude e con DeepSeek sbaglia di circa 40 volte. |
| `ds-claude` | Claude Code normale che gira su DeepSeek, per quando non ti serve un lead. |

Transcript, testi dei compiti e costi degli sviluppatori restano in `./.crew/` nel tuo progetto: puoi sempre rileggere
cosa ha fatto ciascuno.
I messaggi sono in italiano o in inglese in base alla lingua del sistema; per forzarla usa `CREW_LANG=it` o `CREW_LANG=en`.

## Pro o Max?

Funziona con entrambi. La crew conta di più dove i limiti si sentono:

- **Pro ($20):** con le misure del benchmark, in una finestra di 5 ore di Pro entrano circa 18 app di media
  complessità con Opus da solo, e **circa 64 con la crew**. Per l'app a 5 moduli: circa 7 contro **circa 42**.
- **Max:** arrivi al limite settimanale circa 3 volte più tardi, e le sessioni lunghe smettono di essere un problema di quota.

Anthropic non pubblica i limiti in token. Li ho calibrati su un piano Max 20x e riportati a Pro con il rapporto
20× per sessione di 5 ore dichiarato da Anthropic. I dettagli sono nel benchmark.

## Opzioni di installazione

```bash
./install.sh                    # strumenti in ~/.local/bin, skill in ~/.claude/skills/deepseek-crew
./install.sh --test             # come sopra, più una verifica completa da circa $0.002
./install.sh --no-skill         # solo gli strumenti, senza la skill
PREFIX=/opt/crew ./install.sh   # installa gli strumenti altrove
./install.sh --uninstall        # rimuove tutto quello che ha installato
```

Requisiti: `claude`, `python3`, `flock` e `timeout` (già presenti su Linux; su macOS: `brew install flock coreutils`).
Per usare la skill in un solo progetto, copia `skill/deepseek-crew` in `<progetto>/.claude/skills/`.

## Sicurezza e costi

- **Il tuo login Claude resta fuori.** Gli sviluppatori girano con una cartella di configurazione separata, senza
  credenziali Anthropic: anche per errore non possono consumare il tuo piano né chiamare le API Anthropic a pagamento.
  Se in quella cartella compaiono credenziali, gli strumenti si rifiutano di partire.
- **Dove sta la chiave DeepSeek:** nel file `~/.config/claude-deepseek-crew/env` (permessi 600) oppure nella variabile
  `DEEPSEEK_API_KEY`. Il file si crea con il comando che stampa `./install.sh`, che la chiede senza mostrarla.
- **Non fare mai `export` delle variabili DeepSeek** (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`...) nella tua shell:
  dirotterebbero anche il tuo Claude Code normale. Gli strumenti le impostano solo dentro i processi degli sviluppatori.
- **Fatturazione:** il lead è la tua normale sessione di Claude Code, quindi consuma i limiti del piano come sempre
  (help center Anthropic, aggiornato il 07/10/2026). Gli sviluppatori addebitano solo il tuo account DeepSeek.
- **Fasce di punta:** DeepSeek costa il doppio dalle 01:00 alle 04:00 e dalle 06:00 alle 10:00 UTC, dal lunedì al venerdì
  (in Italia: dalle 2 alle 5 e dalle 7 alle 11 con l'ora solare, un'ora più tardi con l'ora legale).
- **Niente ricerca web per gli sviluppatori.** Dal 01/11/2026 DeepSeek fa pagare a richiesta la ricerca e il fetch lato
  server, quindi gli strumenti disattivano `WebSearch` e `WebFetch` per gli sviluppatori. Metti nel repo o nel compito la documentazione che serve loro.
- **Gli sviluppatori hanno permessi completi** (`bypassPermissions`), così non si fermano mai a chiedere. Trattali come un
  tirocinante con accesso root a una sandbox: usa una copia usa e getta del progetto, un container o una VM. Nel mio
  benchmark alcuni sviluppatori hanno lanciato `pkill` su processi estranei, scritto fuori dalla cartella del progetto o
  cercato i test nascosti.

## Come l'ho verificato

Nel benchmark ogni richiesta a DeepSeek è passata da un proxy che registra il modello sia nella richiesta sia nella risposta.
`strace` su un processo sviluppatore non ha mostrato connessioni diverse dall'endpoint configurato. Un run di controllo con la
stessa configurazione ma senza variabili DeepSeek risulta «Not logged in» a Claude. I conteggi di token che legge `ds-cost`
coincidono esattamente con quelli del proxy, e il costo DeepSeek calcolato coincide con il saldo reale dell'account entro l'1%.
Vedi [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Autore

Creato da **Luca Di Domenico**

- Sito: [lucadidomenico.studio](https://lucadidomenico.studio)
- AI Builders Italia: [aibuildersitalia.com](https://aibuildersitalia.com)

## Licenza

[MIT](LICENSE) © 2026 Luca Di Domenico
