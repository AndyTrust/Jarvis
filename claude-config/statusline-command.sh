#!/bin/bash
# Status line: model, current directory, git branch, context usage, rate limits.
# Reads the Claude Code status-line JSON from stdin, prints one colored line.

input=$(cat)

model=$(echo "$input" | jq -r '.model.display_name')
dir=$(echo "$input" | jq -r '.workspace.current_dir')
ddir="${dir/#$HOME/~}"

# Git branch (skip optional locks so we never block another process).
branch=""
if git -C "$dir" --no-optional-locks rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  branch=$(git -C "$dir" --no-optional-locks branch --show-current 2>/dev/null)
fi

# Context window usage (percentage used).
used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
ctx=""
if [ -n "$used" ]; then
  ctx="${used%%.*}%"  # niente printf: col locale italiano non legge il punto decimale
  # per il riassunto al 50% (~/.claude/hooks/sessioni.py legge questo file al prompt dopo)
  sid=$(echo "$input" | jq -r '.session_id // empty')
  [ -n "$sid" ] && mkdir -p "$HOME/.locale-onedrive/ctx" && printf '%s' "$used" > "$HOME/.locale-onedrive/ctx/$sid"
fi

# Consumi (l'utente, 02/10/2026): Sessione 50% ($36.83) | 5h: 3% (reset 16:10) | Sett: 25% (reset mar 20:00); n/d se il dato manca.
cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')
five=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
five_r=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
week=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
week_r=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
nd="n/d"
s_ctx="$nd"; [ -n "$ctx" ] && s_ctx="$ctx"
s_cost='$0.00'; [ -n "$cost" ] && s_cost=$(LC_ALL=C awk -v c="$cost" 'BEGIN{printf "$%.2f", c}')
s_five="$nd"
if [ -n "$five" ]; then
  s_five="${five%%.*}%"
  [ -n "$five_r" ] && s_five="$s_five (reset $(LC_ALL=it_IT.UTF-8 date -r "${five_r%%.*}" '+%H:%M' 2>/dev/null))"
fi
s_week="$nd"
if [ -n "$week" ]; then
  s_week="${week%%.*}%"
  [ -n "$week_r" ] && s_week="$s_week (reset $(LC_ALL=it_IT.UTF-8 date -r "${week_r%%.*}" '+%a %H:%M' 2>/dev/null))"
fi
rl="Sessione $s_ctx ($s_cost) | 5h: $s_five | Sett: $s_week"

# Dim ANSI colors (the status line already renders dimmed in the terminal).
C_MODEL=$'\033[36m'
C_DIR=$'\033[34m'
C_GIT=$'\033[35m'
C_CTX=$'\033[33m'
C_RESET=$'\033[0m'

out=$(printf "%s%s%s" "$C_MODEL" "$model" "$C_RESET")
out="$out $(printf "%s%s%s" "$C_DIR" "$ddir" "$C_RESET")"
if [ -n "$branch" ]; then
  out="$out $(printf "%s(%s)%s" "$C_GIT" "$branch" "$C_RESET")"
fi
out="$out $(printf "%s%s%s" "$C_CTX" "$rl" "$C_RESET")"

printf "%s" "$out"
