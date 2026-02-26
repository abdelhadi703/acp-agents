#!/usr/bin/env python3
"""
Telemetry pour ACP Agents
Calcule tokens/sec, historique rolling, peak/avg TPS.
Données récupérées depuis les réponses Ollama (eval_count, eval_duration).
"""

import time
import threading
import logging
from typing import Dict, List
from collections import deque

logger = logging.getLogger("telemetry")

MAX_SAMPLES = 60  # Rolling window


class AgentTelemetry:
    """Télémétrie pour un agent individuel."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.samples: deque = deque(maxlen=MAX_SAMPLES)
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_requests = 0
        self.peak_tps = 0.0
        self._lock = threading.Lock()

    def record(self, eval_count: int, eval_duration_ns: int,
               prompt_eval_count: int = 0, prompt_eval_duration_ns: int = 0):
        """Enregistrer un sample depuis une réponse Ollama.

        eval_count: nombre de tokens générés
        eval_duration_ns: durée de génération en nanosecondes
        prompt_eval_count: nombre de tokens du prompt
        prompt_eval_duration_ns: durée d'évaluation du prompt
        """
        tps = 0.0
        if eval_duration_ns > 0:
            tps = eval_count / (eval_duration_ns / 1e9)

        prompt_tps = 0.0
        if prompt_eval_duration_ns > 0:
            prompt_tps = prompt_eval_count / (prompt_eval_duration_ns / 1e9)

        sample = {
            "timestamp": time.time(),
            "eval_count": eval_count,
            "eval_duration_ns": eval_duration_ns,
            "tps": round(tps, 2),
            "prompt_eval_count": prompt_eval_count,
            "prompt_tps": round(prompt_tps, 2)
        }

        with self._lock:
            self.samples.append(sample)
            self.total_tokens_out += eval_count
            self.total_tokens_in += prompt_eval_count
            self.total_requests += 1
            if tps > self.peak_tps:
                self.peak_tps = tps

    def get_stats(self) -> Dict:
        """Retourner les statistiques de télémétrie."""
        with self._lock:
            if not self.samples:
                return {
                    "agent": self.agent_name,
                    "samples": 0,
                    "avg_tps": 0.0,
                    "peak_tps": 0.0,
                    "current_tps": 0.0,
                    "total_tokens_in": self.total_tokens_in,
                    "total_tokens_out": self.total_tokens_out,
                    "total_requests": self.total_requests
                }

            tps_values = [s["tps"] for s in self.samples if s["tps"] > 0]
            avg_tps = sum(tps_values) / len(tps_values) if tps_values else 0.0
            current_tps = self.samples[-1]["tps"] if self.samples else 0.0

            return {
                "agent": self.agent_name,
                "samples": len(self.samples),
                "avg_tps": round(avg_tps, 2),
                "peak_tps": round(self.peak_tps, 2),
                "current_tps": round(current_tps, 2),
                "total_tokens_in": self.total_tokens_in,
                "total_tokens_out": self.total_tokens_out,
                "total_requests": self.total_requests,
                "last_sample": dict(self.samples[-1]) if self.samples else None
            }

    def get_tps_display(self) -> str:
        """Retourner le TPS formaté pour tmux (court)."""
        with self._lock:
            if not self.samples:
                return "0.0"
            return f"{self.samples[-1]['tps']:.1f}"


class TelemetryRegistry:
    """Registre global de télémétrie pour tous les agents."""

    def __init__(self):
        self.agents: Dict[str, AgentTelemetry] = {}
        self._lock = threading.Lock()

    def get_or_create(self, agent_name: str) -> AgentTelemetry:
        """Obtenir ou créer la télémétrie pour un agent."""
        with self._lock:
            if agent_name not in self.agents:
                self.agents[agent_name] = AgentTelemetry(agent_name)
            return self.agents[agent_name]

    def record(self, agent_name: str, eval_count: int, eval_duration_ns: int,
               prompt_eval_count: int = 0, prompt_eval_duration_ns: int = 0):
        """Enregistrer un sample pour un agent."""
        telemetry = self.get_or_create(agent_name)
        telemetry.record(eval_count, eval_duration_ns,
                        prompt_eval_count, prompt_eval_duration_ns)

    def get_all_stats(self) -> Dict:
        """Retourner les stats de tous les agents."""
        with self._lock:
            return {
                "agents": {
                    name: tel.get_stats()
                    for name, tel in self.agents.items()
                },
                "total_agents": len(self.agents)
            }


# Singleton global
telemetry_registry = TelemetryRegistry()
