#!/usr/bin/env python3
"""
Archive vectorielle pour ACP Agents
Utilise Ollama Embeddings API pour indexer et rechercher les réponses des agents.
Stockage JSON sur disque (state/vector_store.json).
"""

import json
import os
import math
import time
import hashlib
import logging
import threading
from typing import List, Dict, Optional

import httpx

logger = logging.getLogger("vector-store")

# Constantes
DEFAULT_EMBED_MODEL = "nomic-embed-text"
MAX_TEXT_LENGTH = 8000
MAX_ENTRIES = 10_000
STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
STORE_PATH = os.path.join(STORE_DIR, "vector_store.json")
OLLAMA_API = os.environ.get("OLLAMA_API", "http://localhost:11434/api")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity entre deux vecteurs."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore:
    """Store vectoriel JSON-backed avec embeddings Ollama."""

    def __init__(self, store_path: str = STORE_PATH, embed_model: str = DEFAULT_EMBED_MODEL):
        self.store_path = store_path
        self.embed_model = embed_model
        self._lock = threading.Lock()
        self.entries: List[Dict] = []
        self._load()

    def _load(self):
        """Charger le store depuis le disque."""
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, 'r') as f:
                    data = json.load(f)
                self.entries = data.get("entries", [])
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Erreur chargement vector store: {e}")
                self.entries = []

    def _save(self):
        """Sauvegarder le store sur disque (atomique, appeler avec _lock)."""
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        tmp_path = self.store_path + ".tmp"
        with open(tmp_path, 'w') as f:
            json.dump({"entries": self.entries, "count": len(self.entries)}, f, ensure_ascii=False)
        os.replace(tmp_path, self.store_path)

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """Obtenir l'embedding d'un texte via Ollama POST /api/embed."""
        text = text[:MAX_TEXT_LENGTH]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # API Ollama standard
                resp = await client.post(
                    f"{OLLAMA_API}/embed",
                    json={"model": self.embed_model, "input": text}
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings", [])
                if embeddings and len(embeddings) > 0:
                    return embeddings[0]
                # Fallback ancien format
                embedding = data.get("embedding")
                if embedding:
                    return embedding
                return None
        except Exception:
            return None

    async def index(self, text: str, metadata: Optional[Dict] = None) -> Optional[str]:
        """Indexer un texte : générer embedding + stocker. Retourne l'ID ou None."""
        if not text or not text.strip():
            return None
        if len(self.entries) >= MAX_ENTRIES:
            logger.warning("Store plein, suppression du plus ancien")
            with self._lock:
                self.entries = self.entries[1:]

        embedding = await self.get_embedding(text)
        if embedding is None:
            return None

        entry_id = hashlib.sha256(f"{text[:200]}{time.time()}".encode()).hexdigest()[:16]
        entry = {
            "id": entry_id,
            "text": text[:MAX_TEXT_LENGTH],
            "embedding": embedding,
            "metadata": metadata or {},
            "timestamp": time.time(),
            "text_length": len(text)
        }

        with self._lock:
            self.entries.append(entry)
            self._save()

        return entry_id

    async def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Rechercher les textes les plus similaires à la query."""
        top_k = min(max(top_k, 1), 50)
        query_embedding = await self.get_embedding(query)
        if query_embedding is None:
            return []

        scored = []
        for entry in self.entries:
            emb = entry.get("embedding")
            if emb:
                score = cosine_similarity(query_embedding, emb)
                scored.append({
                    "id": entry["id"],
                    "text": entry["text"][:500],
                    "score": round(score, 4),
                    "metadata": entry.get("metadata", {}),
                    "timestamp": entry.get("timestamp")
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def stats(self) -> Dict:
        """Statistiques du store."""
        return {
            "total_entries": len(self.entries),
            "max_entries": MAX_ENTRIES,
            "embed_model": self.embed_model,
            "store_path": self.store_path,
            "total_text_chars": sum(e.get("text_length", 0) for e in self.entries),
            "oldest": self.entries[0]["timestamp"] if self.entries else None,
            "newest": self.entries[-1]["timestamp"] if self.entries else None
        }
