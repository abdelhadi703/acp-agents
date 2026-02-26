#!/bin/bash
set -uo pipefail
# Gestion des 9 agents ACP en mode daemon (arrière-plan)
# L'orchestrateur = Claude Code / ollama CLI / kilo
# Usage: ./agents-daemon.sh start|stop|status|restart

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/.agents.pid"
LOGDIR="$DIR/logs"

# 9 agents (pas d'orchestrateur — c'est Claude Code qui orchestre)
AGENTS=("vision:8002" "code:8003" "generalist:8004" "frontend:8005" "backend:8006" "security:8007" "i18n:8008" "design:8009" "legal:8010")

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RST='\033[0m'

start() {
    mkdir -p "$LOGDIR"

    echo -e "${BOLD}${CYAN}🚀 Démarrage des 9 agents ACP...${RST}"
    echo ""

    # Vérifier si déjà lancés
    if [ -f "$PIDFILE" ]; then
        running=0
        while read pid; do
            [[ "$pid" =~ ^[0-9]+$ ]] || continue
            kill -0 "$pid" 2>/dev/null && running=$((running+1))
        done < "$PIDFILE"
        if [ $running -gt 0 ]; then
            echo -e "${YELLOW}⚠ $running agent(s) déjà en cours. Utilisez 'restart' ou 'stop' d'abord.${RST}"
            return 1
        fi
    fi

    > "$PIDFILE"
    chmod 600 "$PIDFILE"

    for entry in "${AGENTS[@]}"; do
        name="${entry%%:*}"
        port="${entry##*:}"

        python3 "$DIR/agent_runner.py" "$name" > "$LOGDIR/$name.log" 2>&1 &
        pid=$!
        echo "$pid" >> "$PIDFILE"

        sleep 0.3

        # Vérifier le démarrage
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "  ${GREEN}✅ $name${RST}\t:$port\tpid=$pid"
        else
            echo -e "  ${RED}❌ $name${RST}\t:$port\tÉCHEC"
        fi
    done

    echo ""

    # Attendre que les ports soient prêts
    sleep 2

    # Vérification rapide
    ok=0
    for entry in "${AGENTS[@]}"; do
        port="${entry##*:}"
        curl -s --max-time 2 "http://localhost:$port/status" > /dev/null 2>&1 && ok=$((ok+1))
    done

    echo -e "${BOLD}${GREEN}✅ $ok/9 agents prêts${RST}"
    echo -e "${CYAN}   Claude Code peut maintenant orchestrer via les ports 8002-8010${RST}"
    echo ""
}

stop() {
    echo -e "${BOLD}${RED}🛑 Arrêt des agents...${RST}"

    if [ -f "$PIDFILE" ]; then
        while read pid; do
            [[ "$pid" =~ ^[0-9]+$ ]] || continue
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null
                echo -e "  Arrêté pid=$pid"
            fi
        done < "$PIDFILE"
        rm -f "$PIDFILE"
    fi

    # Kill tout ce qui reste sur les ports
    for entry in "${AGENTS[@]}"; do
        port="${entry##*:}"
        pid=$(lsof -ti:"$port" 2>/dev/null)
        if [ -n "$pid" ] && [[ "$pid" =~ ^[0-9]+$ ]]; then
            # Vérifier que c'est bien un agent_runner avant de kill
            if ps -p "$pid" -o command= 2>/dev/null | grep -q "agent_runner"; then
                kill "$pid" 2>/dev/null
            fi
        fi
    done

    echo -e "${GREEN}✅ Tous les agents arrêtés${RST}"
}

status() {
    echo -e "${BOLD}${CYAN}📊 Status des agents ACP${RST}"
    echo -e "${BOLD}   Agent          Port   Modèle                         Status${RST}"
    echo "   ─────────────  ─────  ─────────────────────────────  ──────"

    for entry in "${AGENTS[@]}"; do
        name="${entry%%:*}"
        port="${entry##*:}"

        result=$(curl -s --max-time 2 "http://localhost:$port/status" 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "$result" ]; then
            model=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['model'])" 2>/dev/null)
            msgs=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['messages'])" 2>/dev/null)
            printf "   ${GREEN}%-13s  %-5s  %-29s  ● actif (%s msgs)${RST}\n" "$name" "$port" "$model" "$msgs"
        else
            printf "   ${RED}%-13s  %-5s  %-29s  ○ inactif${RST}\n" "$name" "$port" "—"
        fi
    done
    echo ""
}

case "${1:-status}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
