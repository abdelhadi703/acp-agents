#!/bin/bash
# Lancer 3 agents pour test des features AMBER ICI
# Layout: 3 panes en bas (code, frontend, security)
# Claude Code reste dans le terminal principal

cd "$(dirname "$0")"

SESSION="agents-test"

# Tuer la session existante si elle existe
tmux kill-session -t $SESSION 2>/dev/null

# Créer la session avec le premier agent (code:8003)
tmux new-session -d -s $SESSION -n agents \
    "echo '🟢 CODE (8003) — qwen3-coder-next:cloud'; python3 agent_runner.py code; read"

# Split horizontalement pour frontend (8005)
tmux split-window -t $SESSION:0 -h \
    "echo '🔵 FRONTEND (8005) — devstral-small-2:24b-cloud'; python3 agent_runner.py frontend; read"

# Split verticalement pour security (8007)
tmux split-window -t $SESSION:0.1 -v \
    "echo '🔴 SECURITY (8007) — cogito-2.1:671b-cloud'; python3 agent_runner.py security; read"

# Layout tiled (3 panes égaux)
tmux select-layout -t $SESSION:0 tiled

# Style tmux
tmux set-option -t $SESSION status-style "bg=colour235,fg=colour46"
tmux set-option -t $SESSION status-left " ★ ACP TEST — 3 agents "
tmux set-option -t $SESSION pane-border-status "top"
tmux set-option -t $SESSION pane-border-lines "heavy"
tmux set-option -t $SESSION pane-active-border-style "fg=green,bold"
tmux set-option -t $SESSION pane-border-style "fg=colour240"

echo "✅ Session tmux '$SESSION' créée avec 3 agents"
echo "   → code:8003 | frontend:8005 | security:8007"
echo ""
echo "Pour voir les agents:"
echo "   tmux attach -t $SESSION"
echo ""
echo "En attente du démarrage des agents..."

# Attendre que les 3 ports répondent
for i in $(seq 1 30); do
    ok=0
    for port in 8003 8005 8007; do
        if curl -s -o /dev/null -w '' http://localhost:$port/status 2>/dev/null; then
            ok=$((ok + 1))
        fi
    done
    if [ $ok -eq 3 ]; then
        echo "✅ Les 3 agents sont prêts!"
        exit 0
    fi
    sleep 2
done

echo "⚠️ Timeout — certains agents ne répondent pas encore"
echo "Vérifiez avec: tmux attach -t $SESSION"
