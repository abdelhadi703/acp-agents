#!/bin/bash
set -euo pipefail
# Lance les 9 agents ACP dans tmux (moniteur visuel)
# L'orchestrateur = Claude Code (pas dans tmux)
# Tu ouvres tmux dans un autre terminal juste pour VOIR les échanges
cd "$(dirname "$0")" || exit 1

tmux kill-session -t agents 2>/dev/null || true
sleep 0.5

# Créer session avec vision
tmux new-session -d -s agents -n agents \
  "printf '\033]2;VISION :8002\033\\'; python3 agent_runner.py vision"

# Ajouter chaque agent avec rebalancement
for agent_info in \
  "CODE:code" \
  "GENERALIST:generalist" \
  "FRONTEND:frontend" \
  "BACKEND:backend" \
  "SECURITY:security" \
  "I18N:i18n" \
  "DESIGN:design" \
  "LEGAL:legal"; do

  title="${agent_info%%:*}"
  name="${agent_info##*:}"
  port=$((8002 + $(echo "vision code generalist frontend backend security i18n design legal" | tr ' ' '\n' | grep -n "^${name}$" | cut -d: -f1) - 1))

  tmux split-window -t agents:agents \
    "printf '\033]2;${title} :${port}\033\\'; python3 agent_runner.py ${name}"
  tmux select-layout -t agents:agents tiled
done

# Style — status bar tmux
tmux set-option -t agents status-style "bg=colour235,fg=colour46"
tmux set-option -t agents status-left " #[fg=colour226,bold]★ ACP MONITOR #[fg=colour245]— 9 agents "
tmux set-option -t agents status-right " #[fg=colour245]Orchestrateur = Claude Code "
tmux set-option -t agents status-left-length 30
tmux set-option -t agents status-right-length 35

# Lancer le monitor de pane titles (stats par agent en temps réel)
python3 "$(dirname "$0")/tmux-monitor.py" 5 &
MONITOR_PID=$!

echo "✅ Moniteur tmux prêt — 9 agents + status monitor (PID: $MONITOR_PID)"
echo "   Ouvre un terminal : tmux attach -t agents"
echo "   Claude Code orchestre depuis ici"
