#!/usr/bin/env python3
"""
Serveur MCP pour les Agents ACP/A2A
Connecte les 10 agents Ollama à Claude Code CLI
Supporte la découverte d'agents et les sessions
"""

import sys
import json
import os
import re
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [mcp] %(message)s')
logger = logging.getLogger("mcp")

UUID_RE = re.compile(r'^[a-f0-9-]{36}$')

AGENT_CARDS_DIR = os.path.join(os.path.dirname(__file__), "agent_cards")

AGENTS = {
    "orchestrator": {"port": 8001, "model": "glm-5:cloud", "role": "Coordination"},
    "vision": {"port": 8002, "model": "qwen3-vl:235b-cloud", "role": "Vision/Images"},
    "code": {"port": 8003, "model": "qwen3-coder-next:cloud", "role": "Code"},
    "generalist": {"port": 8004, "model": "minimax-m2.5:cloud", "role": "Généraliste"},
    "frontend": {"port": 8005, "model": "devstral-small-2:24b-cloud", "role": "Frontend/UI"},
    "backend": {"port": 8006, "model": "devstral-2:123b-cloud", "role": "Backend/API"},
    "security": {"port": 8007, "model": "cogito-2.1:671b-cloud", "role": "Sécurité"},
    "i18n": {"port": 8008, "model": "qwen3.5:cloud", "role": "Traductions"},
    "design": {"port": 8009, "model": "kimi-k2.5:cloud", "role": "Design/UX"},
    "legal": {"port": 8010, "model": "gpt-oss:120b-cloud", "role": "Légal/RGPD"}
}

def call_agent(agent: str, message: str) -> str:
    if agent not in AGENTS:
        return f"Agent '{agent}' inconnu"
    try:
        r = requests.post(f"http://localhost:{AGENTS[agent]['port']}/message",
                         json={"message": message, "from": "claude"}, timeout=120)
        return r.json().get("response", "Erreur de l'agent")
    except Exception as e:
        logger.error(f"Erreur appel {agent}: {e}")
        return "Erreur de communication avec l'agent"


def discover_agents() -> dict:
    """Découvrir tous les agents via Agent Cards (ACP/A2A)"""
    result = {"ollama": [], "anthropic": [], "live": []}

    # Charger les Agent Cards depuis les fichiers
    for system in ("ollama", "anthropic"):
        card_dir = os.path.join(AGENT_CARDS_DIR, system)
        if os.path.isdir(card_dir):
            for f in sorted(os.listdir(card_dir)):
                if f.endswith(".json"):
                    with open(os.path.join(card_dir, f)) as fh:
                        result[system].append(json.load(fh))

    # Vérifier les agents Ollama en live
    for name, cfg in AGENTS.items():
        try:
            r = requests.get(f"http://localhost:{cfg['port']}/status", timeout=3)
            if r.status_code == 200:
                data = r.json()
                result["live"].append({
                    "name": name,
                    "status": "online",
                    "model": data.get("model", cfg["model"]),
                    "context_usage_pct": data.get("context_usage_pct", 0),
                    "messages": data.get("messages", 0),
                    "protocol": data.get("protocol", "acp")
                })
        except Exception:
            result["live"].append({"name": name, "status": "offline"})

    return result

def make_tool(name: str, description: str):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Message à envoyer à l'agent"}},
            "required": ["message"]
        }
    }

def tools_list():
    return {
        "tools": [
            make_tool("ask_orchestrator", "Agent coordinateur principal (glm-5, 744B) — orchestration et délégation"),
            make_tool("ask_vision", "Agent vision/images (qwen3-vl, 235B) — analyse screenshots, maquettes, OCR"),
            make_tool("ask_code", "Agent code (qwen3-coder-next, 80B) — développement, debugging, refactoring"),
            make_tool("ask_generalist", "Agent généraliste (minimax-m2.5) — multi-tâches, brainstorming, rédaction"),
            make_tool("ask_frontend", "Agent frontend (devstral-small-2, 24B, vision) — UI, React, CSS, responsive"),
            make_tool("ask_backend", "Agent backend (devstral-2, 123B) — API, BDD, infrastructure"),
            make_tool("ask_security", "Agent sécurité (cogito-2.1, 671B) — audits, vulnérabilités, corrections"),
            make_tool("ask_i18n", "Agent i18n (qwen3.5, 122B, multilingue) — traductions, internationalisation"),
            make_tool("ask_design", "Agent design/UX (kimi-k2.5, vision) — maquettes, ergonomie, accessibilité"),
            make_tool("ask_legal", "Agent légal (gpt-oss, 120B) — RGPD, conformité, mentions légales"),
            {"name": "list_agents", "description": "Lister tous les agents ACP avec leur statut", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "discover_agents", "description": "Découvrir tous les agents (ACP/A2A) — Agent Cards Ollama + Anthropic + statut live", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "create_session", "description": "Créer une session ACP avec un agent pour une conversation avec état", "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Nom de l'agent (code, vision, etc.)"},
                    "metadata": {"type": "object", "description": "Métadonnées optionnelles de la session"}
                },
                "required": ["agent"]
            }},
            {"name": "session_message", "description": "Envoyer un message dans une session ACP existante", "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Nom de l'agent"},
                    "session_id": {"type": "string", "description": "ID de la session"},
                    "message": {"type": "string", "description": "Message à envoyer"}
                },
                "required": ["agent", "session_id", "message"]
            }}
        ]
    }

def handle(req):
    method = req.get("method", "")
    params = req.get("params", {})

    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "acp-agents", "version": "2.0"}}
    elif method == "tools/list":
        return tools_list()
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "list_agents":
            txt = "\n".join([f"- {n}: {c['role']} ({c['model']}) → port {c['port']}" for n, c in AGENTS.items()])
            return {"content": [{"type": "text", "text": f"Agents ACP (10):\n{txt}"}]}
        elif name == "discover_agents":
            data = discover_agents()
            ollama_count = len(data["ollama"])
            anthropic_count = len(data["anthropic"])
            live_online = [a for a in data["live"] if a["status"] == "online"]
            txt = f"🔍 Discovery ACP/A2A\n\n"
            txt += f"Agent Cards Ollama: {ollama_count}\n"
            for card in data["ollama"]:
                txt += f"  - {card['name']}: {card.get('description', '')} ({card.get('model', {}).get('name', '')})\n"
            txt += f"\nAgent Cards Anthropic: {anthropic_count}\n"
            for card in data["anthropic"]:
                txt += f"  - {card['name']}: {card.get('description', '')} ({card.get('model', {}).get('name', '')})\n"
            txt += f"\nAgents live: {len(live_online)}/{len(data['live'])} en ligne\n"
            for a in data["live"]:
                if a["status"] == "online":
                    txt += f"  ● {a['name']}: {a['model']} — ctx {a['context_usage_pct']}% — {a['messages']} msgs — {a['protocol']}\n"
                else:
                    txt += f"  ○ {a['name']}: offline\n"
            return {"content": [{"type": "text", "text": txt}]}
        elif name == "create_session":
            agent_name = args.get("agent", "")
            if agent_name not in AGENTS:
                return {"content": [{"type": "text", "text": f"Agent '{agent_name}' inconnu"}]}
            try:
                r = requests.post(f"http://localhost:{AGENTS[agent_name]['port']}/sessions",
                                 json={"metadata": args.get("metadata", {})}, timeout=10)
                data = r.json()
                return {"content": [{"type": "text", "text": f"Session créée: {data.get('session_id', '?')} sur {agent_name}"}]}
            except Exception as e:
                logger.error(f"Erreur création session: {e}")
                return {"content": [{"type": "text", "text": "Erreur lors de la création de la session"}]}
        elif name == "session_message":
            agent_name = args.get("agent", "")
            session_id = args.get("session_id", "")
            message = args.get("message", "")
            if agent_name not in AGENTS:
                return {"content": [{"type": "text", "text": f"Agent '{agent_name}' inconnu"}]}
            if not UUID_RE.match(session_id):
                return {"content": [{"type": "text", "text": "ID de session invalide"}]}
            try:
                r = requests.post(f"http://localhost:{AGENTS[agent_name]['port']}/sessions/{session_id}/messages",
                                 json={"message": message, "from": "claude"}, timeout=120)
                data = r.json()
                return {"content": [{"type": "text", "text": data.get("response", "Pas de réponse")}]}
            except Exception as e:
                logger.error(f"Erreur session message: {e}")
                return {"content": [{"type": "text", "text": "Erreur de communication avec l'agent"}]}
        elif name.startswith("ask_"):
            agent = name.replace("ask_", "")
            if agent in AGENTS:
                resp = call_agent(agent, args.get("message", ""))
                return {"content": [{"type": "text", "text": resp}]}
            return {"content": [{"type": "text", "text": f"Agent '{agent}' inconnu"}]}
        return {"error": f"Outil inconnu: {name}"}
    return {"error": "Méthode non supportée"}

def main():
    for line in sys.stdin:
        try:
            req = json.loads(line.strip())
            resp = handle(req)
            req_id = req.get("id")
            if isinstance(req_id, (int, str)) and len(str(req_id)) < 256:
                resp["id"] = req_id
            print(json.dumps(resp), flush=True)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"JSON invalide: {e}")
            print(json.dumps({"error": "JSON invalide"}), flush=True)
        except Exception as e:
            logger.error(f"Erreur inattendue: {e}")
            print(json.dumps({"error": "Erreur interne"}), flush=True)

if __name__ == "__main__":
    main()
