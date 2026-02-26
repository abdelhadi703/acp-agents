#!/usr/bin/env python3
"""
Graph Correlation pour ACP Agents
Stocke les relations agents/tâches/fichiers/concepts comme noeuds et arêtes.
Export compatible D3.js/Cytoscape.js.
"""

import json
import os
import time
import re
import threading
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("graph")

GRAPH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
GRAPH_PATH = os.path.join(GRAPH_DIR, "graph.json")
MAX_NODES = 5000
MAX_EDGES = 20000

# Types valides
VALID_NODE_TYPES = {"agent", "prompt", "file", "concept", "session"}
VALID_EDGE_TYPES = {"DELEGATE", "USES", "PRODUCES", "REFERENCES", "RESPONDS_TO"}
VALID_ID_RE = re.compile(r'^[a-zA-Z0-9_\-:.]{1,128}$')


class Graph:
    """Graphe de corrélations agents/tâches."""

    def __init__(self, graph_path: str = GRAPH_PATH):
        self.graph_path = graph_path
        self._lock = threading.Lock()
        self.nodes: Dict[str, Dict] = {}
        self.edges: List[Dict] = []
        self._load()

    def _load(self):
        """Charger le graphe depuis le disque."""
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, 'r') as f:
                    data = json.load(f)
                for node in data.get("nodes", []):
                    self.nodes[node["id"]] = node
                self.edges = data.get("edges", [])
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Erreur chargement graph: {e}")

    def _save(self):
        """Sauvegarder le graphe atomiquement."""
        os.makedirs(os.path.dirname(self.graph_path), exist_ok=True)
        data = {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "stats": {
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "updated_at": time.time()
            }
        }
        tmp = self.graph_path + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.graph_path)

    def add_node(self, node_id: str, node_type: str, label: str,
                 properties: Optional[Dict] = None) -> Optional[Dict]:
        """Ajouter un noeud au graphe."""
        if not VALID_ID_RE.match(node_id):
            return None
        if node_type not in VALID_NODE_TYPES:
            return None
        if len(self.nodes) >= MAX_NODES:
            return None

        node = {
            "id": node_id,
            "type": node_type,
            "label": label[:200],
            "properties": properties or {},
            "created_at": time.time()
        }

        with self._lock:
            self.nodes[node_id] = node
            self._save()

        return node

    def add_edge(self, source: str, target: str, edge_type: str,
                 properties: Optional[Dict] = None) -> Optional[Dict]:
        """Ajouter une arête entre deux noeuds."""
        if edge_type not in VALID_EDGE_TYPES:
            return None
        # Auto-créer les noeuds agents si délégation
        if source not in self.nodes or target not in self.nodes:
            if edge_type == "DELEGATE":
                if source not in self.nodes:
                    self.add_node(source, "agent", source)
                if target not in self.nodes:
                    self.add_node(target, "agent", target)
            else:
                return None
        if len(self.edges) >= MAX_EDGES:
            return None

        edge = {
            "source": source,
            "target": target,
            "type": edge_type,
            "properties": properties or {},
            "created_at": time.time()
        }

        with self._lock:
            self.edges.append(edge)
            self._save()

        return edge

    def record_delegation(self, from_agent: str, to_agent: str,
                          message_preview: str = ""):
        """Enregistrer automatiquement une délégation inter-agents."""
        if from_agent not in self.nodes:
            self.add_node(from_agent, "agent", from_agent, {"role": "agent"})
        if to_agent not in self.nodes:
            self.add_node(to_agent, "agent", to_agent, {"role": "agent"})

        self.add_edge(from_agent, to_agent, "DELEGATE", {
            "message_preview": message_preview[:200],
            "timestamp": time.time()
        })

    def get_graph(self) -> Dict:
        """Retourner le graphe complet (format D3.js/Cytoscape compatible)."""
        with self._lock:
            return {
                "nodes": list(self.nodes.values()),
                "edges": self.edges,
                "stats": {
                    "node_count": len(self.nodes),
                    "edge_count": len(self.edges)
                }
            }

    def get_node_connections(self, node_id: str) -> Dict:
        """Retourner les connexions d'un noeud spécifique."""
        outgoing = [e for e in self.edges if e["source"] == node_id]
        incoming = [e for e in self.edges if e["target"] == node_id]
        return {
            "node": self.nodes.get(node_id),
            "outgoing": outgoing,
            "incoming": incoming,
            "degree": len(outgoing) + len(incoming)
        }
