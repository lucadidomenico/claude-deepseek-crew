**🇮🇹 Italiano** · [🇬🇧 English](INSTALL_WITH_CLAUDE.md)

# Installa con Claude

Apri Claude Code (in qualsiasi cartella), copia il prompt qui sotto e incollalo. Claude installa tutto e ti guida.
L'unica cosa che ti serve è una chiave API DeepSeek con qualche dollaro di credito: https://platform.deepseek.com/api_keys

```text
Installa sul mio computer claude-deepseek-crew (https://github.com/lucadidomenico/claude-deepseek-crew), seguendo questi passi:

1. Requisiti. Controlla che ci siano git, python3, flock e timeout. Se manca qualcosa, installalo:
   su macOS con Homebrew (`brew install flock coreutils`), su Linux con il gestore pacchetti (util-linux, coreutils).
   Se sono su Windows fermati e dimmi di usare WSL.
2. Codice. Clona il repository in ~/claude-deepseek-crew (se la cartella esiste già, fai git pull).
3. Chiave DeepSeek. NON chiedermela in chat e non stamparla mai. Controlla se esiste già la variabile
   DEEPSEEK_API_KEY o il file ~/.config/claude-deepseek-crew/env. Se non c'è, dammi da eseguire in un
   terminale separato questo comando, che mi chiede la chiave senza mostrarla:
   mkdir -p ~/.config/claude-deepseek-crew && printf 'Chiave DeepSeek: ' && read -rs K && printf 'DEEPSEEK_API_KEY=%s\n' "$K" > ~/.config/claude-deepseek-crew/env && chmod 600 ~/.config/claude-deepseek-crew/env && echo && echo salvata
   poi aspetta che ti dica di aver fatto.
4. Installazione. Dalla cartella del repository esegui ./install.sh --test e controlla che stampi TEST SUPERATO.
   Se fallisce, leggi l'errore, risolvilo e riprova.
5. PATH. Se ~/.local/bin non è nel PATH, aggiungilo al file di profilo della mia shell (~/.zshrc o ~/.bashrc).
6. Fine. Dimmi in poche righe cosa hai installato e come si usa: riavviare Claude Code per caricare la skill,
   poi /model opus e /deepseek-crew <cosa sviluppare> (oppure /deepseek-crew --review <cosa sviluppare>).
```

Cosa fa l'installazione: mette i comandi `ds-worker`, `ds-worker-batch`, `ds-cost` e `ds-claude` in `~/.local/bin`
e la skill `/deepseek-crew` in `~/.claude/skills/`. Non tocca il tuo login di Claude e non modifica le impostazioni di Claude Code.
Per disinstallare: `~/claude-deepseek-crew/install.sh --uninstall`.
