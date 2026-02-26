#!/usr/bin/env python3
"""
Client ACP pour communiquer avec les agents
Usage: python3 client.py <agent_name> "<message>"
"""

import sys
import os
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acp_server import AGENTS

def send_message(agent_name: str, message: str) -> str:
    """Envoyer un message à un agent"""
    if agent_name not in AGENTS:
        return f"Agent '{agent_name}' inconnu. Agents: {list(AGENTS.keys())}"

    port = AGENTS[agent_name]['port']
    url = f"http://localhost:{port}/message"

    try:
        response = requests.post(url, json={
            "message": message,
            "from": "user"
        }, timeout=120)

        result = response.json()
        return result.get('response', 'Pas de réponse')

    except requests.exceptions.ConnectionError:
        return f"❌ Agent '{agent_name}' non disponible (port {port})"
    except Exception as e:
        return f"❌ Erreur: {str(e)}"


def delegate_task(from_agent: str, to_agent: str, message: str) -> str:
    """Déléguer une tâche d'un agent à un autre"""
    if from_agent not in AGENTS:
        return f"Agent source '{from_agent}' inconnu"
    if to_agent not in AGENTS:
        return f"Agent cible '{to_agent}' inconnu"

    port = AGENTS[from_agent]['port']
    url = f"http://localhost:{port}/delegate"

    try:
        response = requests.post(url, json={
            "target": to_agent,
            "message": message
        }, timeout=120)

        result = response.json()
        return result.get('response', 'Pas de réponse')

    except Exception as e:
        return f"❌ Erreur: {str(e)}"


def interactive_mode():
    """Mode interactif"""
    print("\n🤖 Client ACP - Mode Interactif")
    print("="*50)
    print("Commandes:")
    print("  <agent> <message>  - Envoyer un message")
    print("  agents              - Lister les agents")
    print("  quit                - Quitter")
    print("="*50 + "\n")

    while True:
        try:
            user_input = input(">>> ").strip()

            if not user_input:
                continue

            if user_input == "quit":
                print("Au revoir!")
                break

            if user_input == "agents":
                print("\nAgents disponibles:")
                for name, cfg in AGENTS.items():
                    print(f"  - {name} (port {cfg['port']}, {cfg['model']})")
                print()
                continue

            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: <agent> <message>")
                continue

            agent_name = parts[0].lower()
            message = parts[1]

            print(f"\n📨 Envoi à {agent_name}...")
            response = send_message(agent_name, message)
            print(f"\n💬 Réponse:\n{response}\n")

        except KeyboardInterrupt:
            print("\nAu revoir!")
            break


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        # Mode ligne de commande
        agent_name = sys.argv[1].lower()
        message = sys.argv[2]
        print(f"📨 Envoi à {agent_name}: {message[:50]}...")
        response = send_message(agent_name, message)
        print(f"\n💬 Réponse:\n{response}")
    elif len(sys.argv) == 2 and sys.argv[1] == "-i":
        # Mode interactif
        interactive_mode()
    else:
        print("Usage:")
        print("  python3 client.py <agent> '<message>'")
        print("  python3 client.py -i  (mode interactif)")
        print(f"\nAgents: {list(AGENTS.keys())}")