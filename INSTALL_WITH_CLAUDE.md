[🇮🇹 Italiano](INSTALLA_CON_CLAUDE.md) · **🇬🇧 English**

# Install with Claude

Open Claude Code (in any folder), copy the prompt below and paste it. Claude installs everything and guides you.
All you need is a DeepSeek API key with a few dollars of credit: https://platform.deepseek.com/api_keys

```text
Install claude-deepseek-crew (https://github.com/lucadidomenico/claude-deepseek-crew) on my computer, following these steps:

1. Requirements. Check that git, python3, flock and timeout are available. If something is missing, install it:
   on macOS with Homebrew (`brew install flock coreutils`), on Linux with the package manager (util-linux, coreutils).
   If I am on Windows, stop and tell me to use WSL.
2. Code. Clone the repository into ~/claude-deepseek-crew (if the folder already exists, run git pull).
3. DeepSeek key. Do NOT ask me for it in the chat and never print it. Check whether the DEEPSEEK_API_KEY variable
   or the file ~/.config/claude-deepseek-crew/env already exists. If not, give me this command to run in a
   separate terminal, which asks for the key without showing it:
   mkdir -p ~/.config/claude-deepseek-crew && printf 'DeepSeek key: ' && read -rs K && printf 'DEEPSEEK_API_KEY=%s\n' "$K" > ~/.config/claude-deepseek-crew/env && chmod 600 ~/.config/claude-deepseek-crew/env && echo && echo saved
   then wait until I tell you it's done.
4. Install. From the repository folder run CREW_LANG=en ./install.sh --test and check that it prints TEST PASSED.
   If it fails, read the error, fix it and try again.
5. PATH. If ~/.local/bin is not in the PATH, add it to my shell profile (~/.zshrc or ~/.bashrc), and add
   export CREW_LANG=en there too so the tools talk to me in English.
6. Done. Tell me in a few lines what you installed and how to use it: restart Claude Code to load the skill,
   then /model opus and /deepseek-crew <what to build> (or /deepseek-crew --review <what to build>).
```

What the installation does: it puts the `ds-worker`, `ds-worker-batch`, `ds-cost` and `ds-claude` commands in `~/.local/bin`
and the `/deepseek-crew` skill in `~/.claude/skills/`. It does not touch your Claude login or your Claude Code settings.
To uninstall: `~/claude-deepseek-crew/install.sh --uninstall`.
