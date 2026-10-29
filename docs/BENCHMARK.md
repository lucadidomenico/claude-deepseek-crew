**🇮🇹 Italiano** · [🇬🇧 English](BENCHMARK.en.md)

# Benchmark

28 ottobre 2026. Claude Code 2.1.312, piano Claude Max 20x, DeepSeek `deepseek-flash` (V4.1-Flash-1017).
Dati grezzi, script e test nascosti sono in [`benchmark/`](../benchmark).

**Configurazione consigliata: Opus 5.5 come tech lead + sviluppatori DeepSeek V4.1 Flash** (`/deepseek-crew`, con o senza `--review`).
Per confronto ho misurato anche Sonnet 5.5 e DeepSeek da solo: i loro risultati sono riportati qui sotto per intero.

## Metodo

- **6 web app** sviluppate a partire da una specifica precisa. Lo stack è fisso (Node 22, `npm start`, `PORT`, `DATA_DIR`).

  | app | cosa fa | test nascosti |
  |---|---|---|
  | bookmarks | CRUD con tag, filtri, paginazione, CSV | 35 |
  | kanban | account, token, bacheche condivise, regole 401/403/404, ordinamento delle card, limite WIP | 25 |
  | splitter | spese di gruppo in centesimi, 4 tipi di ripartizione con arrotondamento a resti più grandi, saldi, rimborsi con algoritmo greedy | 29 |
  | booking | ruoli, fusi orari IANA con ora legale, ricorrenze tutto-o-niente, disponibilità | 41 |
  | sheets | motore di fogli di calcolo: parser, coercizioni, errori, cicli, inserimento/cancellazione righe con riscrittura dei riferimenti, copia relativa/assoluta | 90 |
  | suite | i 5 moduli qui sopra in un unico server, ognuno sotto il proprio prefisso | 220 |

- **Test di accettazione nascosti.** Test HTTP black-box (pytest) che gli agenti non hanno mai visto. Girano su una copia
  pulita, con `npm install` da zero, una cartella dati nuova e un riavvio del server per verificare la persistenza.
  Ogni suite è stata validata su un'implementazione di riferimento indipendente (100%).
- **Stesso prompt per ogni configurazione.** Ogni sessione gira con `claude -p --safe-mode --permission-mode bypassPermissions`
  e gli strumenti web disattivati. Ogni run ha il suo PID namespace, così i run in parallelo non possono interferire tra loro.
- **Prompt del benchmark, non la skill.** Nei run il lead riceveva le istruzioni da tech lead dai prompt in
  [`benchmark/prompts/`](../benchmark/prompts) (in inglese: `lead-common` più `lead-noreview` o `lead-review`), non dal comando
  `/deepseek-crew`. La skill l'ho scritta dopo, partendo da quei prompt e con la stessa logica. I numeri qui sotto sono
  stati misurati con i prompt.
- **Quota Claude** = token reali dai transcript delle sessioni, valorizzati al listino API di Anthropic. È la misura più fine
  disponibile del consumo del piano: l'endpoint del piano riporta solo punti percentuali interi.
- **Costo DeepSeek** = token reali registrati da un proxy, al listino DeepSeek. Il totale calcolato coincide con il saldo
  dell'account entro l'1%.
- **Audit.** Ogni chiamata agli strumenti, in ogni sessione, è stata controllata. Ho escluso due run in cui uno sviluppatore aveva letto i test nascosti.

## Risultati

| configurazione | run | test nascosti superati | run perfetti | quota Claude vs Opus da solo | quota Claude ($/app a prezzi API) | DeepSeek $/app | tempo medio |
|---|---|---|---|---|---|---|---|
| Opus da solo | 18 | 100% | 18/18 | 100% | 0.98 | – | 4,1 min |
| **Opus lead + DeepSeek, modalità veloce** | 10 | **100%** | 10/10 | **35%** | 0.28 | 0.15 | 12,2 min |
| **Opus lead + DeepSeek, `--review`** | 12 | **100%** | 12/12 | **56%** | 0.47 | 0.12 | 10,7 min |
| Sonnet da solo | 18 | 99,9% | 16/18 | 30% | 0.32 | – | 2,0 min |
| Sonnet lead + DeepSeek, con review | 12 | 100% | 12/12 | 12% | 0.085 | 0.10 | 7,7 min |
| Sonnet lead + DeepSeek, senza review | 5 | 100% | 5/5 | 9% | 0.052 | 0.07 | 8,5 min |
| DeepSeek da solo (`ds-claude`) | 13 | 100% | 13/13 | 0% | – | 0.075 | 8,4 min |

«Quota Claude vs Opus da solo» è il rapporto calcolato app per app e poi mediato sulle 6 app. I tempi sono gonfiati dal fatto
che giravano 5–9 run in parallelo su una macchina da 4 vCPU: vanno confrontati tra configurazioni, non letti come valori assoluti.

### Per app: quota Claude ($ a prezzi API) + DeepSeek ($)

| app | Opus da solo | Opus lead, veloce | Opus lead, review | Sonnet da solo | Sonnet lead, review | DeepSeek da solo |
|---|---|---|---|---|---|---|
| bookmarks | 0.37 | 0.17 + 0.04 | 0.26 + 0.02 | 0.13 | 0.11 + 0.03 | 0.026 |
| kanban | 0.58 | 0.19 + 0.05 | 0.38 + 0.07 | 0.16 | 0.06 + 0.05 | 0.042 |
| splitter | 0.64 | 0.19 + 0.05 | 0.40 + 0.07 | 0.16 | 0.06 + 0.03 | 0.038 |
| booking | 0.67 | 0.30 + 0.11 | 0.36 + 0.07 | 0.18 | 0.06 + 0.06 | 0.058 |
| sheets | 1.13 | 0.47 + 0.35 | 0.62 + 0.16 | 0.37 | 0.07 + 0.09 | 0.119 |
| suite | 2.51 | **0.43** + 0.36 | 0.80 + 0.32 | 0.91 | 0.16 + 0.33 | 0.193 |

Il risparmio del lead Opus cresce con la dimensione del progetto: −55% sull'app più piccola, −83% sulla suite a 5 moduli.

### Limiti del piano

Sul piano Max 20x, l'1% della finestra di 5 ore vale circa $3.6 di consumo a prezzi API, e l'1% del limite settimanale circa
$15.6. Le due stime sono calibrate rispettivamente su 13 e 3 punti percentuali: quella settimanale è approssimativa.
Anthropic dichiara che Max 5x e Max 20x danno 5× e 20× l'uso di Pro per sessione di 5 ore, quindi una finestra di 5 ore di Pro
vale circa $18 a prezzi API. Il rapporto settimanale tra Pro e Max non è pubblicato.

| configurazione | app per finestra di 5 ore Pro | suite a 5 moduli per finestra di 5 ore Pro |
|---|---|---|
| Opus da solo | ~18 | ~7 |
| Opus lead + DeepSeek, veloce | ~64 | ~42 |
| Opus lead + DeepSeek, review | ~38 | ~23 |
| Sonnet da solo | ~57 | ~20 |
| Sonnet lead + DeepSeek, review | ~210 | ~110 |

## Osservazioni

- **La review costa quasi quanto il lavoro.** Opus 5.5 scrive codice in modo molto efficiente. Per verificare una consegna
  deve rileggere spec, piano e codice, e questo porta il suo consumo dal 35% al 56% di Opus da solo. Nei miei test le
  specifiche erano precise e la qualità era già al 100% anche senza review.
- **Su DeepSeek il grosso lo fa la cache:** il 98–99% dei token di input degli sviluppatori sono cache hit ($0.003 per milione).
- **Con DeepSeek il `/cost` di Claude Code sbaglia di circa 40 volte**, perché applica i prezzi Claude. I conteggi di token
  nel risultato `stream-json` invece sono esatti, ed è da lì che legge `ds-cost`.
- **Gli sviluppatori con permessi completi vanno tenuti in una sandbox.** Ho visto `pkill -f "node server.js"` uccidere
  processi di altri progetti, file scritti in percorsi con le maiuscole sbagliate fuori dal progetto e, in 2 run su 12 in
  modalità veloce, uno sviluppatore cercare i test nascosti nel filesystem. Quei due run sono esclusi.

## Limiti

- Tutte le specifiche erano precise e complete. Non ho misurato richieste vaghe in stile vibe coding, codebase esistenti
  e cresciute nel tempo o sessioni di debugging: sono i casi in cui il giudizio del lead dovrebbe pesare di più.
- Da 1 a 3 ripetizioni per configurazione e app (93 run). La terza ripetizione delle configurazioni con DeepSeek non è stata eseguita.
- Dell'interfaccia ho verificato solo che venga servita (`GET /` restituisce HTML), senza provarla in un browser.
- Tutto il traffico DeepSeek è avvenuto fuori dalle fasce di punta. In fascia di punta i costi DeepSeek qui sopra raddoppiano.
