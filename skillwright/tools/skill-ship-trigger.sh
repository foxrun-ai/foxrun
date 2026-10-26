#!/bin/sh
# The catalog owner notifies this trigger after approving canonical catalog bytes.
TOOLS="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1
DOJO="${SKILLS_DOJO_ROOT:-$(dirname "$TOOLS")}"
DOJO="$(CDPATH= cd -- "$DOJO" && pwd)" || exit 1
# SKILLS_SOURCE_REPO names the committed repository; the person's skill source sets it.
SOURCE="${SKILLS_SOURCE_REPO:-$DOJO}"
hook="${1:-post-commit}"
previous="${2:-}"
expected="${3:-}"
for v in $(env | grep -E '^GIT_' | cut -d= -f1); do unset "$v"; done
branch="$(git -C "$SOURCE" symbolic-ref --short HEAD 2>/dev/null)"
[ "$branch" = main ] || exit 0
case "$hook" in
  catalog-change) base='' ;;
  post-merge) base="$(git -C "$SOURCE" rev-parse -q --verify 'ORIG_HEAD^{commit}' 2>/dev/null)" ;;
  *) base="$(git -C "$SOURCE" rev-parse -q --verify 'HEAD^1^{commit}' 2>/dev/null)" ;;
esac
[ -n "$base" ] || base="$(git -C "$SOURCE" hash-object -t tree /dev/null)"
plan="$(python3 "$TOOLS/catalog_state.py" trigger-plan --dojo "$DOJO" --source "$SOURCE" --hook "$hook" --base "$base" --previous "$previous" --expected "$expected")" || exit 1
version="$(printf '%s\n' "$plan" | sed -n '1p')"
names="$(printf '%s\n' "$plan" | sed '1d')"
if [ -n "$names" ]; then
  LOG="${SKILL_STATE_ROOT:-$DOJO/skill-state}/ships/trigger.log"
  mkdir -p "$(dirname "$LOG")"
  echo "$(date -u +%FT%TZ) commit $(git -C "$SOURCE" rev-parse --short HEAD) on main touched a skill; ship started; catalog $version; source $SOURCE" >> "$LOG"
  SKILLS_DOJO_ROOT="$DOJO" SKILLS_CATALOG_DIGEST="$version" nohup sh -c '
    sleep "$1"
    printf "%s\n" "$2" | while IFS= read -r name; do
      "$0" ship --skill "$name" || exit 1
    done
  ' "$TOOLS/skill_ship.py" "${SKILLS_SHIP_SETTLE_SECONDS:-15}" "$names" >> "$LOG" 2>&1 &
fi
exit 0
