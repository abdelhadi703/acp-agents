#!/usr/bin/env python3
"""
ACP-like Server for Ollama Agents
Protocole de communication entre agents basé sur HTTP REST
"""

import json
import re
import logging
import httpx
import asyncio
import uuid
import os
import threading
from typing import Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger("acp")

# Features AMBER ICI
from vector_store import VectorStore
from telemetry import telemetry_registry
from graph import Graph
from file_ingestion import FileIngestion
from fractal_memory import FractalMemory

# Configuration des agents (10 agents)
AGENTS = {
    "orchestrator": {
        "model": "glm-5:cloud",
        "port": 8001,
        "role": "Coordination et orchestration des tâches",
        "color": "\033[1;33m"  # Jaune
    },
    "vision": {
        "model": "qwen3-vl:235b-cloud",
        "port": 8002,
        "role": "Analyse d'images et vision",
        "color": "\033[1;36m"  # Cyan
    },
    "code": {
        "model": "qwen3-coder-next:cloud",
        "port": 8003,
        "role": "Génération et analyse de code",
        "color": "\033[1;32m"  # Vert
    },
    "generalist": {
        "model": "minimax-m2.5:cloud",
        "port": 8004,
        "role": "Tâches générales et assistance",
        "color": "\033[1;35m"  # Magenta
    },
    "frontend": {
        "model": "devstral-small-2:24b-cloud",
        "port": 8005,
        "role": "Interface utilisateur, composants, styles, responsive",
        "color": "\033[1;34m"  # Bleu
    },
    "backend": {
        "model": "devstral-2:123b-cloud",
        "port": 8006,
        "role": "API, base de données, infrastructure",
        "color": "\033[1;31m"  # Rouge
    },
    "security": {
        "model": "cogito-2.1:671b-cloud",
        "port": 8007,
        "role": "Audits sécurité, détection de vulnérabilités",
        "color": "\033[1;91m"  # Rouge clair
    },
    "i18n": {
        "model": "qwen3.5:cloud",
        "port": 8008,
        "role": "Internationalisation, traductions, adaptation culturelle",
        "color": "\033[1;93m"  # Jaune clair
    },
    "design": {
        "model": "kimi-k2.5:cloud",
        "port": 8009,
        "role": "Analyse design, maquettes, ergonomie, UX",
        "color": "\033[1;95m"  # Magenta clair
    },
    "legal": {
        "model": "gpt-oss:120b-cloud",
        "port": 8010,
        "role": "Conformité légale, RGPD, réglementation",
        "color": "\033[1;37m"  # Blanc
    },
    "evolve": {
        "model": "glm-5:cloud",
        "port": 8011,
        "role": "Évaluateur et optimiseur de tous les agents",
        "color": "\033[1;95m"  # Magenta clair
    }
}

OLLAMA_API = os.environ.get("OLLAMA_API", "http://localhost:11434/api")
AGENT_CARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_cards")

# Limites de sécurité
MAX_MESSAGE_LENGTH = 100_000
MAX_SESSIONS_PER_AGENT = 100
MAX_MESSAGES_PER_SESSION = 100
VALID_SYSTEMS = {"ollama", "anthropic"}
VALID_NAME_RE = re.compile(r'^[a-z0-9_-]+$')


def load_agent_card(name: str, system: str = "ollama") -> dict:
    """Charger l'Agent Card JSON d'un agent (protégé contre path traversal)"""
    if system not in VALID_SYSTEMS:
        return {"name": name, "error": "invalid system"}
    if not VALID_NAME_RE.match(name):
        return {"name": name, "error": "invalid name"}
    path = os.path.realpath(os.path.join(AGENT_CARDS_DIR, system, f"{name}.json"))
    if not path.startswith(os.path.realpath(AGENT_CARDS_DIR)):
        return {"name": name, "error": "path traversal blocked"}
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"name": name, "error": "card not found"}


def load_all_cards(system: str = "ollama") -> list:
    """Charger toutes les Agent Cards d'un système (protégé contre path traversal)"""
    if system not in VALID_SYSTEMS:
        return []
    card_dir = os.path.realpath(os.path.join(AGENT_CARDS_DIR, system))
    if not card_dir.startswith(os.path.realpath(AGENT_CARDS_DIR)):
        return []
    cards = []
    if os.path.isdir(card_dir):
        for f in sorted(os.listdir(card_dir)):
            if f.endswith(".json"):
                with open(os.path.join(card_dir, f)) as fh:
                    cards.append(json.load(fh))
    return cards


class Session:
    """Session ACP — conversation avec état entre agents"""

    def __init__(self, metadata: dict = None):
        self.id = str(uuid.uuid4())
        self.created = datetime.now().isoformat()
        self.messages = []
        self.metadata = metadata or {}
        self.status = "active"

    def add_message(self, role: str, content: str, agent: str = None):
        self.messages.append({
            "role": role,
            "content": content,
            "agent": agent,
            "timestamp": datetime.now().isoformat()
        })

    def to_dict(self):
        return {
            "id": self.id,
            "created": self.created,
            "status": self.status,
            "messages": self.messages,
            "metadata": self.metadata,
            "message_count": len(self.messages)
        }


class ACPAgent:
    """Agent ACP utilisant l'API Ollama"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.model = config["model"]
        self.port = config["port"]
        self.color = config["color"]
        self.role = config["role"]
        self.history = []
        self.sessions = {}  # Session store
        self._lock = threading.Lock()  # Thread safety pour les compteurs
        # Context tracking
        self.context_length = 0
        self.capabilities = []
        self.total_prompt_tokens = 0
        self.total_eval_tokens = 0
        self.message_count = 0
        # Features AMBER ICI (singletons partagés entre tous les agents)
        if not hasattr(ACPAgent, '_vector_store'):
            ACPAgent._vector_store = VectorStore()
            ACPAgent._graph = Graph()
            ACPAgent._file_ingestion = FileIngestion(vector_store=ACPAgent._vector_store)
            ACPAgent._fractal_memory = FractalMemory(vector_store=ACPAgent._vector_store)

    async def fetch_model_info(self):
        """Récupérer les infos du modèle (context_length, capabilities) via Ollama API"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(f"{OLLAMA_API}/show", json={"name": self.model})
                response.raise_for_status()
                data = response.json()
                self.capabilities = data.get('capabilities', [])
                model_info = data.get('model_info', {})
                for key, value in model_info.items():
                    if 'context_length' in key:
                        self.context_length = value
                        break
                if not self.context_length:
                    self.context_length = 131072  # défaut pour modèles cloud
        except Exception:
            self.context_length = 131072
            self.capabilities = []

    def get_context_usage(self) -> dict:
        """Retourner les stats de contexte"""
        used = self.total_prompt_tokens + self.total_eval_tokens
        pct = round((used / self.context_length * 100), 1) if self.context_length else 0
        return {
            "context_length": self.context_length,
            "prompt_tokens": self.total_prompt_tokens,
            "eval_tokens": self.total_eval_tokens,
            "total_tokens_used": used,
            "context_usage_pct": min(pct, 100.0),
            "messages": self.message_count,
            "capabilities": self.capabilities
        }

    async def call_ollama(self, prompt: str, system: Optional[str] = None) -> str:
        """Appeler l'API Ollama"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(f"{OLLAMA_API}/chat", json=payload)
                response.raise_for_status()
                result = response.json()
                # Track token usage — utiliser les compteurs Ollama si dispo,
                # sinon estimer ~4 chars/token (modèles cloud ne renvoient pas toujours les counts)
                prompt_tokens = result.get('prompt_eval_count', 0)
                eval_tokens = result.get('eval_count', 0)
                if prompt_tokens == 0:
                    prompt_text = (system or "") + prompt
                    prompt_tokens = max(len(prompt_text) // 4, 1)
                if eval_tokens == 0:
                    content = result.get("message", {}).get("content", "")
                    eval_tokens = max(len(content) // 4, 1)
                # Telemetry recording
                eval_duration = result.get('eval_duration', 0)
                prompt_eval_duration = result.get('prompt_eval_duration', 0)
                if eval_tokens > 0 and eval_duration > 0:
                    telemetry_registry.record(
                        self.name, eval_tokens, eval_duration,
                        prompt_tokens, prompt_eval_duration
                    )
                with self._lock:
                    self.total_prompt_tokens += prompt_tokens
                    self.total_eval_tokens += eval_tokens
                    self.message_count += 1
                content = result["message"]["content"]
                # Auto-indexation dans le vector store
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(
                            ACPAgent._vector_store.index(content, metadata={
                                "agent": self.name, "type": "response"
                            })
                        )
                except Exception:
                    pass
                return content
        except Exception as e:
            logger.error(f"Erreur call_ollama: {e}")
            return "Erreur interne lors de l'appel au modèle"

    async def call_ollama_stream(self, prompt: str, system: Optional[str] = None):
        """Appeler l'API Ollama en mode streaming — yield chaque chunk"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": self.model, "messages": messages, "stream": True}

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", f"{OLLAMA_API}/chat", json=payload) as resp:
                    full_content = ""
                    async for line in resp.aiter_lines():
                        if line:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                full_content += token
                                yield token
                            if chunk.get("done"):
                                eval_c = chunk.get("eval_count", len(full_content) // 4)
                                eval_d = chunk.get("eval_duration", 0)
                                pe_c = chunk.get("prompt_eval_count", len(prompt) // 4)
                                pe_d = chunk.get("prompt_eval_duration", 0)
                                if eval_c > 0 and eval_d > 0:
                                    telemetry_registry.record(
                                        self.name, eval_c, eval_d, pe_c, pe_d
                                    )
                                with self._lock:
                                    self.total_prompt_tokens += pe_c
                                    self.total_eval_tokens += eval_c
                                    self.message_count += 1
        except Exception as e:
            logger.error(f"Erreur streaming: {e}")
            yield "\n[Erreur streaming]"

    def create_session(self, metadata: dict = None) -> Optional[Session]:
        """Créer une nouvelle session (limitée à MAX_SESSIONS_PER_AGENT)"""
        if len(self.sessions) >= MAX_SESSIONS_PER_AGENT:
            # Nettoyer les sessions closes
            self.sessions = {k: v for k, v in self.sessions.items() if v.status == "active"}
            if len(self.sessions) >= MAX_SESSIONS_PER_AGENT:
                return None
        session = Session(metadata=metadata)
        self.sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            self.sessions[session_id].status = "closed"
            return True
        return False

    async def send_to_agent(self, agent_name: str, message: str) -> str:
        """Envoyer un message à un autre agent via ACP"""
        if agent_name not in AGENTS:
            return f"Agent '{agent_name}' inconnu"

        target = AGENTS[agent_name]
        target_url = f"http://localhost:{target['port']}/message"

        payload = {
            "from": self.name,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(target_url, json=payload)
                response.raise_for_status()
                return response.json().get("response", "")
        except Exception as e:
            logger.error(f"Erreur communication avec {agent_name}: {e}")
            return "Erreur de communication avec l'agent"

    def get_system_prompt(self) -> str:
        """Prompt système pour l'agent"""
        agents_list = "\n".join([f"- {n}: {c['role']} (port {c['port']}, modèle {c['model']})" for n, c in AGENTS.items()])
        return f"""Tu es l'agent '{self.name}' avec le rôle: {self.role}
Réponds toujours en français.

Tu fais partie d'un système multi-agents (10 agents). Voici tous les agents disponibles:
{agents_list}

Pour déléguer une tâche à un autre agent, utilise le format: [DELEGATE:agent_name:message]
Exemple: [DELEGATE:code:Écris une fonction Python pour calculer Fibonacci]
Exemple: [DELEGATE:security:Audite ce code pour les failles XSS]

Règles:
- Délègue aux agents SPÉCIALISÉS (pas au generalist si un spécialiste existe)
- Sois précis dans tes délégations
- Synthétise les résultats de manière claire
"""


def print_banner():
    """Afficher le banner"""
    print("\n" + "="*60)
    print("  🤖 ACP Server - Multi-Agent Ollama")
    print("="*60)
    print("\n  Agents disponibles:")
    print("  ┌─────────────────┬──────────┬────────────────────┐")
    print("  │ Agent           │ Port     │ Modèle             │")
    print("  ├─────────────────┼──────────┼────────────────────┤")
    for name, cfg in AGENTS.items():
        print(f"  │ {name:15} │ {cfg['port']:8} │ {cfg['model']:18} │")
    print("  └─────────────────┴──────────┴────────────────────┘")
    print("\n  Endpoints REST:")
    print("  - POST /message    : Envoyer un message")
    print("  - POST /delegate   : Déléguer à un autre agent")
    print("  - GET  /status     : État de l'agent")
    print("  - GET  /agents     : Liste des agents")
    print("="*60 + "\n")


if __name__ == "__main__":
    print_banner()
    print("Pour démarrer les agents, lancez:")
    for name, cfg in AGENTS.items():
        print(f"  python3 agent_runner.py {name} &")