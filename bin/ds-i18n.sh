# claude-deepseek-crew — language of the messages: CREW_LANG=it|en, otherwise the system locale (it* → Italian, else English)
case "${CREW_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in it*|IT*) CREW_IT=1;; *) CREW_IT=0;; esac
export CREW_IT
# t "testo italiano" "english text"
t() { if [ "$CREW_IT" = 1 ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }
