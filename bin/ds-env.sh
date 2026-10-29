# claude-deepseek-crew — environment for a Claude Code process that must run on DeepSeek.
# Source it ONLY inside the worker process (ds-worker / ds-claude do this for you).
# It never touches your normal Claude Code login: it uses a separate config dir without Anthropic credentials,
# so a mistake cannot bill your Claude subscription or the Anthropic API.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/ds-i18n.sh"
CREW_HOME="${CREW_HOME:-$HOME/.config/claude-deepseek-crew}"
# la chiave può stare nella variabile d'ambiente o nel file $CREW_HOME/env (riga DEEPSEEK_API_KEY=...)
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -f "$CREW_HOME/env" ]; then . "$CREW_HOME/env"; fi
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  t "claude-deepseek-crew: manca la chiave DeepSeek (variabile DEEPSEEK_API_KEY o file $CREW_HOME/env)" \
    "claude-deepseek-crew: DeepSeek key missing (DEEPSEEK_API_KEY variable or $CREW_HOME/env file)" >&2
  return 1 2>/dev/null || exit 1
fi
unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN CLAUDECODE CLAUDE_CODE_SESSION_ID CLAUDE_CODE_ENTRYPOINT \
      CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_CODE_SESSION_ATTENDED
export ANTHROPIC_BASE_URL="${CREW_BASE_URL:-https://api.deepseek.com/anthropic}"
export ANTHROPIC_AUTH_TOKEN="$DEEPSEEK_API_KEY"
CREW_MODEL="${CREW_MODEL:-deepseek-flash}"
# every model slot is set explicitly: an empty Opus slot would be mapped by DeepSeek to the (pricier) V4 Pro
export ANTHROPIC_MODEL="$CREW_MODEL" ANTHROPIC_DEFAULT_OPUS_MODEL="$CREW_MODEL" ANTHROPIC_DEFAULT_SONNET_MODEL="$CREW_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$CREW_MODEL" ANTHROPIC_SMALL_FAST_MODEL="$CREW_MODEL" CLAUDE_CODE_SUBAGENT_MODEL="$CREW_MODEL"
export CLAUDE_CONFIG_DIR="$CREW_HOME/claude-config"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1
export CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
mkdir -p "$CLAUDE_CONFIG_DIR"
if [ -e "$CLAUDE_CONFIG_DIR/.credentials.json" ]; then
  t "claude-deepseek-crew: mi fermo, $CLAUDE_CONFIG_DIR contiene credenziali Anthropic" \
    "claude-deepseek-crew: refusing to run, $CLAUDE_CONFIG_DIR contains Anthropic credentials" >&2; return 1 2>/dev/null || exit 1
fi
# DeepSeek bills server-side web search/fetch from 2026-11-01: workers get no web tools
CREW_DISALLOWED="WebSearch WebFetch"
