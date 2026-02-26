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
            }},
            # === Features AMBER ICI ===
            {"name": "archive_search", "description": "Rechercher dans l'archive vectorielle des agents ACP (semantic search via embeddings)", "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texte de recherche sémantique"},
                    "top_k": {"type": "integer", "description": "Nombre de résultats (défaut: 5, max: 50)"}
                },
                "required": ["query"]
            }},
            {"name": "archive_index", "description": "Indexer du texte dans l'archive vectorielle ACP", "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texte à indexer"},
                    "agent": {"type": "string", "description": "Agent cible (défaut: code)"},
                    "metadata": {"type": "object", "description": "Métadonnées optionnelles"}
                },
                "required": ["text"]
            }},
            {"name": "upload_file", "description": "Uploader un fichier (PDF/DOCX/TXT/MD) vers les agents ACP pour extraction et indexation", "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Agent cible (défaut: code)"},
                    "filename": {"type": "string", "description": "Nom du fichier avec extension"},
                    "content": {"type": "string", "description": "Contenu du fichier encodé en base64"},
                    "metadata": {"type": "object", "description": "Métadonnées optionnelles"}
                },
                "required": ["filename", "content"]
            }},
            {"name": "list_files", "description": "Lister les fichiers uploadés dans les agents ACP", "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Agent cible (défaut: code)"}
                }
            }},
            {"name": "get_telemetry", "description": "Obtenir les statistiques de télémétrie (tokens/sec, débit) de tous les agents ACP", "inputSchema": {
                "type": "object",
                "properties": {}
            }},
            {"name": "get_graph", "description": "Obtenir le graphe de corrélations agents/tâches/fichiers des agents ACP", "inputSchema": {
                "type": "object",
                "properties": {}
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
        # === Features AMBER ICI ===
        elif name == "archive_search":
            query = args.get("query", "")
            top_k = args.get("top_k", 5)
            agent_name = "code"
            try:
                r = requests.post(
                    f"http://localhost:{AGENTS[agent_name]['port']}/archive/search",
                    json={"query": query, "top_k": top_k}, timeout=30
                )
                data = r.json()
                results = data.get("results", [])
                txt = f"Archive Search: {len(results)} résultats\n\n"
                for i, res in enumerate(results):
                    txt += f"{i+1}. [score: {res['score']}] {res['text'][:200]}\n"
                    if res.get("metadata"):
                        txt += f"   meta: {json.dumps(res['metadata'])}\n"
                return {"content": [{"type": "text", "text": txt}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Erreur archive search: {e}"}]}
        elif name == "archive_index":
            text = args.get("text", "")
            agent_name = args.get("agent", "code")
            meta = args.get("metadata", {})
            if agent_name not in AGENTS:
                agent_name = "code"
            try:
                r = requests.post(
                    f"http://localhost:{AGENTS[agent_name]['port']}/archive/index",
                    json={"text": text, "metadata": meta}, timeout=30
                )
                data = r.json()
                return {"content": [{"type": "text", "text": f"Indexé: {data.get('id', '?')} — {data.get('status', '?')}"}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Erreur indexation: {e}"}]}
        elif name == "upload_file":
            agent_name = args.get("agent", "code")
            filename = args.get("filename", "")
            content = args.get("content", "")
            meta = args.get("metadata", {})
            if agent_name not in AGENTS:
                agent_name = "code"
            try:
                r = requests.post(
                    f"http://localhost:{AGENTS[agent_name]['port']}/files/upload",
                    json={"filename": filename, "content": content, "metadata": meta},
                    timeout=120
                )
                data = r.json()
                if "error" in data:
                    return {"content": [{"type": "text", "text": f"Erreur upload: {data['error']}"}]}
                txt = f"Fichier uploadé: {data.get('filename', '?')}\n"
                txt += f"ID: {data.get('id', '?')}\n"
                txt += f"Taille: {data.get('size_bytes', 0)} bytes\n"
                txt += f"Texte extrait: {data.get('text_extracted', 0)} chars\n"
                txt += f"Chunks indexés: {data.get('chunks_indexed', 0)}"
                return {"content": [{"type": "text", "text": txt}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Erreur upload: {e}"}]}
        elif name == "list_files":
            agent_name = args.get("agent", "code")
            if agent_name not in AGENTS:
                agent_name = "code"
            try:
                r = requests.get(
                    f"http://localhost:{AGENTS[agent_name]['port']}/files", timeout=10
                )
                data = r.json()
                files = data.get("files", [])
                txt = f"Fichiers uploadés: {len(files)}\n\n"
                for f in files:
                    txt += f"  — {f['filename']} ({f['size_bytes']} bytes, {f['chunks_indexed']} chunks)\n"
                return {"content": [{"type": "text", "text": txt}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Erreur list files: {e}"}]}
        elif name == "get_telemetry":
            txt = "Télémétrie ACP Agents\n\n"
            for ag_name, cfg in AGENTS.items():
                try:
                    r = requests.get(
                        f"http://localhost:{cfg['port']}/telemetry", timeout=3
                    )
                    data = r.json()
                    tps = data.get("current_tps", 0)
                    peak = data.get("peak_tps", 0)
                    avg = data.get("avg_tps", 0)
                    t_in = data.get("total_tokens_in", 0)
                    t_out = data.get("total_tokens_out", 0)
                    txt += f"  {ag_name}: {tps:.1f} tok/s (avg: {avg:.1f}, peak: {peak:.1f}) | in: {t_in} out: {t_out}\n"
                except Exception:
                    txt += f"  {ag_name}: offline\n"
            return {"content": [{"type": "text", "text": txt}]}
        elif name == "get_graph":
            agent_name = "code"
            try:
                r = requests.get(
                    f"http://localhost:{AGENTS[agent_name]['port']}/graph", timeout=10
                )
                data = r.json()
                nodes = data.get("nodes", [])
                edges = data.get("edges", [])
                txt = f"Graph ACP: {len(nodes)} noeuds, {len(edges)} arêtes\n\n"
                txt += "Noeuds:\n"
                for n in nodes[:20]:
                    txt += f"  [{n['type']}] {n['id']}: {n['label']}\n"
                txt += "\nArêtes:\n"
                for e in edges[:20]:
                    txt += f"  {e['source']} —{e['type']}→ {e['target']}\n"
                if len(nodes) > 20:
                    txt += f"\n... et {len(nodes) - 20} noeuds de plus\n"
                if len(edges) > 20:
                    txt += f"... et {len(edges) - 20} arêtes de plus\n"
                return {"content": [{"type": "text", "text": txt}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Erreur graph: {e}"}]}
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
