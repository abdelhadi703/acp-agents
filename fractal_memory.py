#!/usr/bin/env python3
"""
Fibonacci Fractal Memory pour ACP Agents
Chunking hiérarchique avec tailles Fibonacci, embeddings multi-granularité.
Beam search pour recherche contextuelle optimisée.
"""

import math
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("fractal-memory")

# Tailles Fibonacci par niveau (du plus gros au plus petit)
FIBONACCI_SIZES = [987, 610, 377, 233, 144]
FIBONACCI_OVERLAPS = [89, 61, 37, 23, 14]
NUM_LEVELS = 5
BEAM_WIDTH = 3
TOP_K = 5


class FractalNode:
    """Noeud dans l'arbre fractal Fibonacci."""

    def __init__(self, level: int, text: str, start: int, end: int):
        self.level = level
        self.text = text
        self.start = start
        self.end = end
        self.embedding: Optional[List[float]] = None
        self.centroid: Optional[List[float]] = None
        self.children: List['FractalNode'] = []

    def to_dict(self) -> Dict:
        return {
            "level": self.level,
            "start": self.start,
            "end": self.end,
            "text_length": len(self.text),
            "has_embedding": self.embedding is not None,
            "has_centroid": self.centroid is not None,
            "children_count": len(self.children)
        }


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[Tuple[int, int, str]]:
    """Découper un texte en chunks avec overlap. Retourne [(start, end, chunk_text)]."""
    if not text:
        return []
    chunks = []
    step = max(chunk_size - overlap, 1)
    for i in range(0, len(text), step):
        end = min(i + chunk_size, len(text))
        chunks.append((i, end, text[i:end]))
        if end >= len(text):
            break
    return chunks


def build_fractal_tree(text: str) -> Optional[FractalNode]:
    """Construire l'arbre fractal hiérarchique.

    Level 0: chunks de 987 chars (overlap 89) — racines
    Level 1: chaque chunk L0 redécoupé en 610 (overlap 61)
    Level 2: 377 (overlap 37)
    Level 3: 233 (overlap 23)
    Level 4: 144 (overlap 14) — feuilles (embeddings)
    """
    if not text:
        return None

    if len(text) < FIBONACCI_SIZES[-1]:
        # Texte trop court : un seul noeud feuille
        return FractalNode(level=0, text=text, start=0, end=len(text))

    root = FractalNode(level=-1, text="", start=0, end=len(text))

    def build_level(parent_text: str, parent_start: int, level: int) -> List[FractalNode]:
        if level >= NUM_LEVELS:
            return []

        chunk_size = FIBONACCI_SIZES[level]
        overlap = FIBONACCI_OVERLAPS[level]

        chunks = chunk_text(parent_text, chunk_size, overlap)
        nodes = []
        for (start, end, chunk) in chunks:
            node = FractalNode(
                level=level,
                text=chunk,
                start=parent_start + start,
                end=parent_start + end
            )
            if level < NUM_LEVELS - 1:
                node.children = build_level(chunk, parent_start + start, level + 1)
            nodes.append(node)
        return nodes

    root.children = build_level(text, 0, 0)
    return root


def get_leaves(node: FractalNode) -> List[FractalNode]:
    """Récupérer toutes les feuilles de l'arbre."""
    if not node.children:
        return [node]
    leaves = []
    for child in node.children:
        leaves.extend(get_leaves(child))
    return leaves


def compute_centroid(embeddings: List[List[float]]) -> Optional[List[float]]:
    """Calculer le centroïde (moyenne) de plusieurs embeddings."""
    if not embeddings:
        return None
    dim = len(embeddings[0])
    centroid = [0.0] * dim
    for emb in embeddings:
        for i in range(min(dim, len(emb))):
            centroid[i] += emb[i]
    n = len(embeddings)
    return [c / n for c in centroid]


async def embed_tree(root: FractalNode, vector_store) -> int:
    """Embedder les feuilles et calculer les centroids bottom-up.
    Retourne le nombre d'embeddings générés."""
    count = 0

    async def embed_node(node: FractalNode):
        nonlocal count
        if not node.children:
            # Feuille : générer embedding
            if node.text and len(node.text) >= 10:
                emb = await vector_store.get_embedding(node.text)
                node.embedding = emb
                if emb:
                    count += 1
            return

        # Noeud interne : embedder les enfants d'abord
        for child in node.children:
            await embed_node(child)

        # Calculer le centroid
        child_embs = []
        for child in node.children:
            if child.embedding:
                child_embs.append(child.embedding)
            elif child.centroid:
                child_embs.append(child.centroid)
        node.centroid = compute_centroid(child_embs)

    for child in root.children:
        await embed_node(child)

    return count


def beam_search(root: FractalNode, query_embedding: List[float],
                beam_width: int = BEAM_WIDTH, top_k: int = TOP_K) -> List[Dict]:
    """Beam search dans l'arbre fractal pour trouver les chunks les plus pertinents.

    À chaque niveau, on garde les `beam_width` meilleurs noeuds et on descend.
    """
    from vector_store import cosine_similarity

    if not root.children:
        if root.embedding:
            score = cosine_similarity(query_embedding, root.embedding)
            return [{"text": root.text, "score": round(score, 4),
                     "level": root.level, "start": root.start, "end": root.end}]
        return []

    # Beam search top-down
    current_beam = root.children[:]
    all_scored = []

    while current_beam:
        scored = []
        for node in current_beam:
            emb = node.centroid or node.embedding
            if emb:
                score = cosine_similarity(query_embedding, emb)
            else:
                score = 0.0
            scored.append((score, node))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_nodes = scored[:beam_width]

        # Collecter les résultats (feuilles ou noeuds terminaux)
        next_beam = []
        for score, node in top_nodes:
            if not node.children:
                # Feuille atteinte
                all_scored.append({
                    "text": node.text,
                    "score": round(score, 4),
                    "level": node.level,
                    "start": node.start,
                    "end": node.end
                })
            else:
                next_beam.extend(node.children)

        if not next_beam:
            # Plus d'enfants, ajouter les noeuds restants
            for score, node in top_nodes:
                if node.children:
                    all_scored.append({
                        "text": node.text[:500],
                        "score": round(score, 4),
                        "level": node.level,
                        "start": node.start,
                        "end": node.end
                    })
            break

        current_beam = next_beam

    all_scored.sort(key=lambda x: x["score"], reverse=True)
    return all_scored[:top_k]


class FractalMemory:
    """Gestionnaire de mémoire fractale pour les sessions."""

    def __init__(self, vector_store):
        self.vector_store = vector_store
        self.trees: Dict[str, FractalNode] = {}

    async def ingest(self, session_id: str, text: str) -> Dict:
        """Ingérer du texte dans la mémoire fractale d'une session."""
        tree = build_fractal_tree(text)
        if tree is None:
            return {"status": "error", "message": "Texte vide"}

        embed_count = await embed_tree(tree, self.vector_store)
        self.trees[session_id] = tree
        leaves = get_leaves(tree)

        return {
            "status": "indexed",
            "session_id": session_id,
            "total_nodes": self._count_nodes(tree),
            "leaf_count": len(leaves),
            "embeddings_generated": embed_count
        }

    async def query(self, session_id: str, query: str, top_k: int = 5) -> List[Dict]:
        """Rechercher dans la mémoire fractale d'une session."""
        tree = self.trees.get(session_id)
        if not tree:
            return []

        query_emb = await self.vector_store.get_embedding(query)
        if not query_emb:
            return []

        return beam_search(tree, query_emb, BEAM_WIDTH, top_k)

    def has_tree(self, session_id: str) -> bool:
        return session_id in self.trees

    def _count_nodes(self, node: FractalNode) -> int:
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count
