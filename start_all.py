#!/usr/bin/env python3
"""
Démarre tous les agents ACP en parallèle
"""

import subprocess
import sys
import os
import time
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acp_server import AGENTS, print_banner

processes = []

def signal_handler(sig, frame):
    """Arrêter tous les processus"""
    print("\n\n🛑 Arrêt de tous les agents...")
    for p in processes:
        p.terminate()
    sys.exit(0)

def main():
    print_banner()

    # Démarrer chaque agent
    for name in AGENTS.keys():
        print(f"🚀 Démarrage de {name}...")
        p = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_runner.py'), name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        processes.append(p)
        time.sleep(1)  # Attendre un peu entre chaque démarrage

    print("\n✅ Tous les agents sont en cours d'exécution!")
    print("\n📋 Commandes disponibles:")
    print("   python3 client.py orchestrator 'Bonjour, comment vas-tu?'")
    print("   python3 client.py code 'Écris une fonction Python'")
    print("   python3 client.py vision 'Analyse cette image: [url]'")
    print("   python3 client.py generalist 'Aide-moi avec...'")
    print("\n🛑 Appuyez sur Ctrl+C pour arrêter tous les agents")

    # Attendre
    signal.signal(signal.SIGINT, signal_handler)
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()