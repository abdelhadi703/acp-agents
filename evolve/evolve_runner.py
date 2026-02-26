#!/usr/bin/env python3
"""
EVOLVE Runner — Évaluateur et optimiseur d'agents GLM
Utilise glm-5:cloud pour scorer les agents Ollama (ports 8002-8010)
Cycle : BENCHMARK → EXÉCUTION → SCORING → ANALYSE → MUTATION → SÉLECTION
"""

import json
import httpx
import asyncio
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# Chemins
EVOLVE_DIR = Path(__file__).parent
BENCHMARKS_FILE = EVOLVE_DIR / "benchmarks.json"
SCORES_FILE = EVOLVE_DIR / "scores.json"
HISTORY_FILE = EVOLVE_DIR / "prompt-history.json"
PROMPTS_DIR = EVOLVE_DIR / "prompts"
AGENTS_DIR = Path.home() / ".claude" / "agents"

OLLAMA_API = "http://localhost:11434/api"
EVOLVE_MODEL = "glm-5:cloud"

# Poids de scoring par agent
WEIGHTS = {
    "default":    {"exactitude": 0.25, "completude": 0.20, "conformite_regles": 0.20, "qualite": 0.15, "securite": 0.10, "format": 0.10},
    "security":   {"exactitude": 0.25, "completude": 0.10, "conformite_regles": 0.20, "qualite": 0.10, "securite": 0.30, "format": 0.05},
    "code":       {"exactitude": 0.20, "completude": 0.15, "conformite_regles": 0.15, "qualite": 0.25, "securite": 0.15, "format": 0.10},
    "i18n":       {"exactitude": 0.30, "completude": 0.25, "conformite_regles": 0.15, "qualite": 0.15, "securite": 0.05, "format": 0.10},
    "legal":      {"exactitude": 0.25, "completude": 0.20, "conformite_regles": 0.30, "qualite": 0.10, "securite": 0.05, "format": 0.10},
    "design":     {"exactitude": 0.15, "completude": 0.20, "conformite_regles": 0.15, "qualite": 0.25, "securite": 0.05, "format": 0.20},
    "frontend":   {"exactitude": 0.20, "completude": 0.15, "conformite_regles": 0.15, "qualite": 0.20, "securite": 0.15, "format": 0.15},
    "backend":    {"exactitude": 0.20, "completude": 0.15, "conformite_regles": 0.15, "qualite": 0.20, "securite": 0.20, "format": 0.10},
    "vision":     {"exactitude": 0.30, "completude": 0.25, "conformite_regles": 0.10, "qualite": 0.15, "securite": 0.05, "format": 0.15},
    "generalist": {"exactitude": 0.25, "completude": 0.20, "conformite_regles": 0.15, "qualite": 0.20, "securite": 0.05, "format": 0.15},
}

# Ports des agents
AGENT_PORTS = {
    "vision": 8002, "code": 8003, "generalist": 8004,
    "frontend": 8005, "backend": 8006, "security": 8007,
    "i18n": 8008, "design": 8009, "legal": 8010,
}

# Couleurs terminal
C = {
    "RESET": "\033[0m", "BOLD": "\033[1m",
    "RED": "\033[1;31m", "GREEN": "\033[1;32m", "YELLOW": "\033[1;33m",
    "BLUE": "\033[1;34m", "MAGENTA": "\033[1;95m", "CYAN": "\033[1;36m",
    "DIM": "\033[2m",
}


def log(msg, color="MAGENTA"):
    """Affiche un message coloré avec timestamp"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{C['DIM']}[{ts}]{C['RESET']} {C[color]}EVOLVE{C['RESET']} {msg}")


def load_json(path):
    """Charger un fichier JSON"""
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    """Sauvegarder un fichier JSON"""
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def call_ollama(prompt, system=None, model=EVOLVE_MODEL):
    """Appeler l'API Ollama"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages, "stream": False}

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(f"{OLLAMA_API}/chat", json=payload)
        response.raise_for_status()
        return response.json()["message"]["content"]


async def call_agent(agent_name, message):
    """Envoyer un message à un agent via son port ACP"""
    port = AGENT_PORTS.get(agent_name)
    if not port:
        return f"Agent '{agent_name}' inconnu"

    payload = {
        "from": "evolve",
        "message": message,
        "timestamp": datetime.now().isoformat()
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"http://localhost:{port}/message", json=payload)
            response.raise_for_status()
            return response.json().get("response", "")
    except Exception as e:
        return f"ERREUR: Agent {agent_name} (port {port}) inaccessible — {e}"


async def check_agents():
    """Vérifier quels agents sont actifs"""
    active = []
    for name, port in AGENT_PORTS.items():
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"http://localhost:{port}/status")
                if r.status_code == 200:
                    active.append(name)
        except Exception:
            pass
    return active


def get_agent_prompt(agent_name):
    """Lire le prompt système d'un agent"""
    path = AGENTS_DIR / f"{agent_name}.md"
    if path.exists():
        return path.read_text()
    return ""


def get_agent_rules(agent_name):
    """Extraire les 10 règles NON NÉGOCIABLES du prompt d'un agent"""
    prompt = get_agent_prompt(agent_name)
    rules = []
    in_rules = False
    for line in prompt.split("\n"):
        if "NON NÉGOCIABLE" in line or "Règles" in line:
            in_rules = True
            continue
        if in_rules and line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.")):
            rules.append(line.strip())
        elif in_rules and line.startswith("##"):
            break
    return rules


async def score_response(agent_name, benchmark, response):
    """Noter la réponse d'un agent via EVOLVE (glm-5)"""
    rules = get_agent_rules(agent_name)
    rules_text = "\n".join(rules) if rules else "Pas de règles trouvées"
    criteria_text = "\n".join(f"- {c}" for c in benchmark["criteria"])

    scoring_prompt = f"""Tu es EVOLVE, l'évaluateur du système multi-agents GLM.

AGENT ÉVALUÉ : {agent_name}
TÂCHE : {benchmark['task']}
DIFFICULTÉ : {benchmark['difficulty']}

CRITÈRES ATTENDUS :
{criteria_text}

RÈGLES DE L'AGENT (NON NÉGOCIABLES) :
{rules_text}

RÉPONSE DE L'AGENT :
{response}

---

Note cette réponse sur 6 dimensions (0 à 10 chacune).
Réponds UNIQUEMENT en JSON valide, sans texte avant ou après :

{{
  "scores": {{
    "exactitude": {{"note": X, "justification": "..."}},
    "completude": {{"note": X, "justification": "..."}},
    "conformite_regles": {{"note": X, "justification": "..."}},
    "qualite": {{"note": X, "justification": "..."}},
    "securite": {{"note": X, "justification": "..."}},
    "format": {{"note": X, "justification": "..."}}
  }},
  "erreurs": [
    {{"categorie": "LOG|OMI|SEC|FMT|RUL|HAL|PRF|COH", "severite": "CRITIQUE|ÉLEVÉ|MOYEN|FAIBLE", "description": "...", "regle_violee": "..."}}
  ]
}}"""

    raw = await call_ollama(scoring_prompt)

    # Parser le JSON depuis la réponse
    try:
        # Essayer de trouver le JSON dans la réponse
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except json.JSONDecodeError:
        pass

    # Fallback si parsing échoue
    return {
        "scores": {
            "exactitude": {"note": 0, "justification": "Erreur de parsing"},
            "completude": {"note": 0, "justification": "Erreur de parsing"},
            "conformite_regles": {"note": 0, "justification": "Erreur de parsing"},
            "qualite": {"note": 0, "justification": "Erreur de parsing"},
            "securite": {"note": 0, "justification": "Erreur de parsing"},
            "format": {"note": 0, "justification": "Erreur de parsing"}
        },
        "erreurs": [{"categorie": "LOG", "severite": "CRITIQUE", "description": "Impossible de parser le scoring", "regle_violee": "N/A"}]
    }


def compute_global_score(agent_name, scores_data):
    """Calculer le score global pondéré"""
    weights = WEIGHTS.get(agent_name, WEIGHTS["default"])
    total = 0
    for dim, weight in weights.items():
        note = scores_data["scores"].get(dim, {}).get("note", 0)
        total += note * weight
    return round(total, 2)


async def run_benchmark_on_agent(agent_name, benchmark, use_acp=True):
    """Exécuter un benchmark sur un agent et le noter"""
    log(f"📋 {agent_name} — {benchmark['id']} ({benchmark['difficulty']})")

    # Exécuter la tâche
    if use_acp:
        response = await call_agent(agent_name, benchmark["task"])
    else:
        # Mode direct Ollama (sans ACP runner)
        agent_prompt = get_agent_prompt(agent_name)
        response = await call_ollama(benchmark["task"], system=agent_prompt, model=get_agent_model(agent_name))

    if response.startswith("ERREUR:"):
        log(f"❌ {agent_name} — {response}", "RED")
        return None

    log(f"📝 Scoring en cours...", "YELLOW")

    # Scorer la réponse
    scoring = await score_response(agent_name, benchmark, response)
    global_score = compute_global_score(agent_name, scoring)

    # Construire le résultat
    result = {
        "id": f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{benchmark['id']}",
        "date": datetime.now().isoformat(),
        "agent": agent_name,
        "model": get_agent_model(agent_name),
        "system": "ollama",
        "benchmark_id": benchmark["id"],
        "scores": {k: v["note"] for k, v in scoring["scores"].items()},
        "justifications": {k: v["justification"] for k, v in scoring["scores"].items()},
        "score_global": global_score,
        "erreurs": scoring.get("erreurs", []),
        "prompt_version": get_current_prompt_version(agent_name)
    }

    # Afficher le score
    color = "GREEN" if global_score >= 7 else "YELLOW" if global_score >= 5 else "RED"
    log(f"{'✅' if global_score >= 7 else '⚠️' if global_score >= 5 else '❌'} {agent_name}/{benchmark['id']} → {global_score}/10", color)

    return result


def get_agent_model(agent_name):
    """Retourne le modèle Ollama d'un agent"""
    models = {
        "vision": "qwen3-vl:235b-cloud", "code": "qwen3-coder-next:cloud",
        "generalist": "minimax-m2.5:cloud", "frontend": "devstral-small-2:24b-cloud",
        "backend": "devstral-2:123b-cloud", "security": "cogito-2.1:671b-cloud",
        "i18n": "qwen3.5:cloud", "design": "kimi-k2.5:cloud", "legal": "gpt-oss:120b-cloud",
    }
    return models.get(agent_name, "unknown")


def get_current_prompt_version(agent_name):
    """Retourne la version actuelle du prompt d'un agent"""
    history = load_json(HISTORY_FILE)
    return history["agents"].get(agent_name, {}).get("current", "v1")


async def evaluate_agent(agent_name, use_acp=True):
    """Évaluer un agent sur tous ses benchmarks"""
    benchmarks_data = load_json(BENCHMARKS_FILE)
    agent_benchmarks = benchmarks_data["benchmarks"].get(agent_name, [])

    if not agent_benchmarks:
        log(f"⚠️ Pas de benchmarks pour {agent_name}", "YELLOW")
        return []

    # Skip les benchmarks vision qui nécessitent des images
    if agent_name == "vision":
        agent_benchmarks = [b for b in agent_benchmarks if "image" not in b.get("note", "").lower()]

    log(f"🚀 Évaluation de {agent_name} — {len(agent_benchmarks)} benchmarks", "CYAN")

    results = []
    for benchmark in agent_benchmarks:
        result = await run_benchmark_on_agent(agent_name, benchmark, use_acp)
        if result:
            results.append(result)

    # Sauvegarder les résultats
    scores_data = load_json(SCORES_FILE)
    scores_data["evaluations"].extend(results)
    save_json(SCORES_FILE, scores_data)

    # Résumé
    if results:
        avg = round(sum(r["score_global"] for r in results) / len(results), 2)
        log(f"📊 {agent_name} — Score moyen : {avg}/10 ({len(results)} benchmarks)", "CYAN")

    return results


async def evaluate_all(use_acp=True):
    """Évaluer tous les agents"""
    log("=" * 60)
    log("🧬 EVOLVE — Cycle d'évaluation complet", "MAGENTA")
    log("=" * 60)

    if use_acp:
        active = await check_agents()
        if not active:
            log("❌ Aucun agent actif ! Lance ./launch-agents.sh d'abord", "RED")
            return
        log(f"✅ Agents actifs : {', '.join(active)}", "GREEN")
        agents_to_eval = active
    else:
        agents_to_eval = list(AGENT_PORTS.keys())

    all_results = {}
    for agent in agents_to_eval:
        results = await evaluate_agent(agent, use_acp)
        if results:
            avg = round(sum(r["score_global"] for r in results) / len(results), 2)
            all_results[agent] = {"score": avg, "count": len(results)}

    # Classement final
    log("\n" + "=" * 60)
    log("📊 CLASSEMENT FINAL", "MAGENTA")
    log("=" * 60)
    sorted_agents = sorted(all_results.items(), key=lambda x: x[1]["score"], reverse=True)
    for rank, (agent, data) in enumerate(sorted_agents, 1):
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "  "
        color = "GREEN" if data["score"] >= 7 else "YELLOW" if data["score"] >= 5 else "RED"
        log(f"{medal} #{rank} {agent:12} → {data['score']}/10 ({data['count']} tests)", color)

    # Identifier l'agent le plus faible
    if sorted_agents:
        weakest = sorted_agents[-1]
        log(f"\n⚠️ Agent le plus faible : {weakest[0]} ({weakest[1]['score']}/10)", "YELLOW")
        log(f"💡 Recommandation : muter le prompt de '{weakest[0]}'", "YELLOW")

    return all_results


async def analyze_errors(agent_name=None):
    """Analyser les patterns d'erreurs"""
    scores_data = load_json(SCORES_FILE)
    evaluations = scores_data["evaluations"]

    if agent_name:
        evaluations = [e for e in evaluations if e["agent"] == agent_name]

    if not evaluations:
        log("Pas de données d'évaluation", "YELLOW")
        return

    # Compter les erreurs par catégorie
    error_counts = {}
    error_by_agent = {}
    for ev in evaluations:
        agent = ev["agent"]
        for err in ev.get("erreurs", []):
            cat = err.get("categorie", "UNKNOWN")
            sev = err.get("severite", "UNKNOWN")
            error_counts[cat] = error_counts.get(cat, 0) + 1
            if agent not in error_by_agent:
                error_by_agent[agent] = {}
            error_by_agent[agent][cat] = error_by_agent[agent].get(cat, 0) + 1

    log("\n📊 ANALYSE DES ERREURS", "MAGENTA")
    log("-" * 40)
    for cat, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
        log(f"  {cat}: {count} occurrences", "YELLOW")

    if error_by_agent:
        log("\n📊 ERREURS PAR AGENT", "MAGENTA")
        for agent, cats in error_by_agent.items():
            top_error = max(cats.items(), key=lambda x: x[1])
            log(f"  {agent}: {sum(cats.values())} erreurs (top: {top_error[0]} x{top_error[1]})", "YELLOW")


async def mutate_prompt(agent_name):
    """Générer une variante améliorée du prompt d'un agent"""
    scores_data = load_json(SCORES_FILE)
    agent_evals = [e for e in scores_data["evaluations"] if e["agent"] == agent_name]

    if not agent_evals:
        log(f"Pas de données pour muter {agent_name}", "YELLOW")
        return

    # Récupérer le prompt actuel
    current_prompt = get_agent_prompt(agent_name)
    current_version = get_current_prompt_version(agent_name)

    # Collecter les erreurs
    all_errors = []
    for ev in agent_evals:
        all_errors.extend(ev.get("erreurs", []))

    # Scores moyens par dimension
    avg_scores = {}
    for dim in ["exactitude", "completude", "conformite_regles", "qualite", "securite", "format"]:
        vals = [e["scores"].get(dim, 0) for e in agent_evals]
        avg_scores[dim] = round(sum(vals) / len(vals), 1) if vals else 0

    errors_text = "\n".join(f"- [{e['categorie']}] {e['severite']}: {e['description']}" for e in all_errors[:10])
    scores_text = "\n".join(f"- {dim}: {score}/10" for dim, score in avg_scores.items())

    mutation_prompt = f"""Tu es EVOLVE, l'optimiseur d'agents du système GLM.

MISSION : Améliorer le prompt système de l'agent '{agent_name}'.

PROMPT ACTUEL (version {current_version}) :
---
{current_prompt}
---

SCORES MOYENS :
{scores_text}

ERREURS RÉCURRENTES :
{errors_text}

CONSIGNES DE MUTATION :
1. Identifie les faiblesses dans le prompt actuel
2. Propose des modifications CIBLÉES (pas de réécriture complète)
3. Ajoute ou reformule des règles pour corriger les erreurs récurrentes
4. Ne supprime RIEN qui fonctionne bien (scores >= 8)
5. Conserve le format exact du prompt (sections, structure markdown)

Retourne le prompt COMPLET modifié (pas juste les changements).
Commence directement par le contenu du prompt, sans explication."""

    log(f"🧬 Mutation du prompt de {agent_name} (version {current_version})...", "MAGENTA")
    new_prompt = await call_ollama(mutation_prompt)

    if not new_prompt or len(new_prompt) < 100:
        log(f"❌ Mutation échouée — réponse trop courte", "RED")
        return None

    # Sauvegarder la nouvelle version
    new_version = f"v{int(current_version[1:]) + 1}"

    # Backup de l'ancienne version
    old_backup = PROMPTS_DIR / f"{agent_name}.{current_version}.md"
    if not old_backup.exists():
        shutil.copy(AGENTS_DIR / f"{agent_name}.md", old_backup)

    # Sauvegarder la nouvelle version
    new_backup = PROMPTS_DIR / f"{agent_name}.{new_version}.md"
    new_backup.write_text(new_prompt)

    log(f"✅ Nouvelle version sauvegardée : {new_backup.name}", "GREEN")
    log(f"⚠️ Pour appliquer : copier {new_backup} → ~/.claude/agents/{agent_name}.md", "YELLOW")

    # Mettre à jour l'historique
    history = load_json(HISTORY_FILE)
    avg_global = round(sum(e["score_global"] for e in agent_evals) / len(agent_evals), 2)
    history["agents"][agent_name]["versions"][current_version] = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "score_moyen": avg_global,
        "file": old_backup.name
    }
    save_json(HISTORY_FILE, history)

    return new_version


async def apply_mutation(agent_name, version):
    """Appliquer une version mutée du prompt"""
    source = PROMPTS_DIR / f"{agent_name}.{version}.md"
    target = AGENTS_DIR / f"{agent_name}.md"

    if not source.exists():
        log(f"❌ Version {version} introuvable pour {agent_name}", "RED")
        return False

    # Backup avant remplacement
    backup = PROMPTS_DIR / f"{agent_name}.{get_current_prompt_version(agent_name)}.md"
    if not backup.exists():
        shutil.copy(target, backup)

    # Appliquer
    shutil.copy(source, target)

    # Mettre à jour l'historique
    history = load_json(HISTORY_FILE)
    history["agents"][agent_name]["current"] = version
    save_json(HISTORY_FILE, history)

    log(f"✅ Prompt de {agent_name} mis à jour → {version}", "GREEN")
    return True


async def rollback(agent_name):
    """Revenir à la version précédente du prompt"""
    history = load_json(HISTORY_FILE)
    current = history["agents"][agent_name]["current"]
    current_num = int(current[1:])

    if current_num <= 1:
        log(f"❌ Impossible de rollback — déjà en v1", "RED")
        return False

    prev_version = f"v{current_num - 1}"
    return await apply_mutation(agent_name, prev_version)


# ─── BENCHMARKS COLLABORATION ────────────────────────────────

async def run_collab_benchmark(benchmark, use_acp=True):
    """Exécuter un benchmark de collaboration multi-agents"""
    agents = benchmark["agents"]
    task = benchmark["task"]
    log(f"🤝 Collab {benchmark['id']} — Agents : {', '.join(agents)}", "CYAN")

    conversation = []
    final_results = {}

    if use_acp:
        # Étape 1 : Envoyer la tâche au premier agent
        first_agent = agents[0]
        log(f"  → {first_agent} reçoit la tâche initiale", "BLUE")
        response1 = await call_agent(first_agent, task)
        conversation.append({"agent": first_agent, "role": "initial", "response": response1})
        final_results[first_agent] = response1

        # Étape 2 : Envoyer le résultat aux agents suivants
        for i, agent in enumerate(agents[1:], 1):
            relay_msg = (
                f"Voici le résultat de {agents[i-1]} pour la tâche suivante :\n\n"
                f"TÂCHE : {task}\n\n"
                f"RÉSULTAT DE {agents[i-1].upper()} :\n{conversation[-1]['response']}\n\n"
                f"TON RÔLE : En tant que {agent}, analyse ce résultat et "
                f"{'corrige/améliore le code selon les recommandations' if agent in ['frontend','backend','code'] else 'donne ton avis expert et tes recommandations'}."
            )
            log(f"  → {agent} reçoit le relais de {agents[i-1]}", "BLUE")
            response = await call_agent(agent, relay_msg)
            conversation.append({"agent": agent, "role": "relay", "response": response})
            final_results[agent] = response

        # Étape 3 (optionnel) : Retour au premier agent pour validation
        if len(agents) >= 2:
            validation_msg = (
                f"Tu avais produit un résultat pour cette tâche : {task}\n\n"
                f"Voici les retours des autres agents :\n"
            )
            for entry in conversation[1:]:
                validation_msg += f"\n--- {entry['agent'].upper()} ---\n{entry['response'][:1000]}\n"
            validation_msg += f"\nIntègre ces retours et produis une version FINALE."

            log(f"  → {first_agent} intègre les retours (version finale)", "BLUE")
            final_response = await call_agent(first_agent, validation_msg)
            conversation.append({"agent": first_agent, "role": "final", "response": final_response})
            final_results[f"{first_agent}_final"] = final_response

    else:
        # Mode direct Ollama (sans ACP)
        for i, agent in enumerate(agents):
            agent_prompt = get_agent_prompt(agent)
            if i == 0:
                msg = task
            else:
                msg = (
                    f"TÂCHE : {task}\n\n"
                    f"RÉSULTAT DE {agents[i-1].upper()} :\n{conversation[-1]['response']}\n\n"
                    f"TON RÔLE : Analyse et améliore ce résultat selon ton expertise de {agent}."
                )
            response = await call_ollama(msg, system=agent_prompt, model=get_agent_model(agent))
            conversation.append({"agent": agent, "role": "relay" if i > 0 else "initial", "response": response})
            final_results[agent] = response

    # Scoring de la collaboration
    log(f"📝 Scoring collaboration...", "YELLOW")
    scoring = await score_collab(benchmark, conversation, final_results)
    global_score = scoring.get("score_global", 0)

    # Construire le résultat
    result = {
        "id": f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{benchmark['id']}",
        "date": datetime.now().isoformat(),
        "agent": "+".join(agents),
        "model": "+".join(get_agent_model(a) for a in agents),
        "system": "ollama",
        "benchmark_id": benchmark["id"],
        "scores": scoring.get("scores", {}),
        "justifications": scoring.get("justifications", {}),
        "score_global": global_score,
        "erreurs": scoring.get("erreurs", []),
        "prompt_version": "v1",
        "collab_details": {
            "agents": agents,
            "turns": len(conversation),
            "agents_responses": {a: len(r) for a, r in final_results.items()}
        }
    }

    color = "GREEN" if global_score >= 7 else "YELLOW" if global_score >= 5 else "RED"
    log(f"{'✅' if global_score >= 7 else '⚠️'} Collab {benchmark['id']} → {global_score}/10 ({len(conversation)} échanges)", color)

    return result


async def score_collab(benchmark, conversation, final_results):
    """Scorer un benchmark de collaboration via EVOLVE (glm-5)"""
    criteria_text = "\n".join(f"- {c}" for c in benchmark["criteria"])
    agents_text = ", ".join(benchmark["agents"])

    # Résumé des échanges (tronqué pour le contexte)
    exchanges = ""
    for entry in conversation:
        truncated = entry["response"][:800] + ("..." if len(entry["response"]) > 800 else "")
        exchanges += f"\n--- {entry['agent'].upper()} ({entry['role']}) ---\n{truncated}\n"

    scoring_prompt = f"""Tu es EVOLVE, l'évaluateur du système multi-agents GLM.

BENCHMARK COLLABORATION : {benchmark['id']}
AGENTS IMPLIQUÉS : {agents_text}
TÂCHE : {benchmark['task']}

CRITÈRES :
{criteria_text}

ÉCHANGES ENTRE AGENTS :
{exchanges}

---

Note cette collaboration sur 6 dimensions + 2 dimensions collab (0 à 10) :
Réponds UNIQUEMENT en JSON valide :

{{
  "scores": {{
    "exactitude": X,
    "completude": X,
    "conformite_regles": X,
    "qualite": X,
    "securite": X,
    "format": X,
    "communication": X,
    "integration": X
  }},
  "justifications": {{
    "exactitude": "...",
    "completude": "...",
    "conformite_regles": "...",
    "qualite": "...",
    "securite": "...",
    "format": "...",
    "communication": "qualité des échanges entre agents",
    "integration": "cohérence du résultat final intégrant les contributions de tous"
  }},
  "score_global": X.X,
  "erreurs": []
}}"""

    raw = await call_ollama(scoring_prompt)

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except json.JSONDecodeError:
        pass

    return {
        "scores": {},
        "justifications": {},
        "score_global": 0,
        "erreurs": [{"categorie": "LOG", "severite": "CRITIQUE", "description": "Parsing scoring collab échoué"}]
    }


async def evaluate_collab(use_acp=True):
    """Évaluer tous les benchmarks de collaboration"""
    benchmarks_data = load_json(BENCHMARKS_FILE)
    collab_benchmarks = benchmarks_data["benchmarks"].get("collab", [])

    if not collab_benchmarks:
        log("⚠️ Pas de benchmarks de collaboration", "YELLOW")
        return []

    log(f"🤝 EVOLVE — {len(collab_benchmarks)} benchmarks de collaboration", "CYAN")

    if use_acp:
        active = await check_agents()
        if len(active) < 2:
            log("❌ Au moins 2 agents actifs nécessaires pour les benchmarks collab", "RED")
            return []

    results = []
    for benchmark in collab_benchmarks:
        # Vérifier que tous les agents requis sont actifs
        if use_acp:
            missing = [a for a in benchmark["agents"] if a not in active]
            if missing:
                log(f"⏭️ {benchmark['id']} — agents manquants : {', '.join(missing)}", "YELLOW")
                continue

        result = await run_collab_benchmark(benchmark, use_acp)
        if result:
            results.append(result)

    # Sauvegarder
    if results:
        scores_data = load_json(SCORES_FILE)
        scores_data["evaluations"].extend(results)
        save_json(SCORES_FILE, scores_data)

        avg = round(sum(r["score_global"] for r in results) / len(results), 2)
        log(f"\n📊 Collaboration — Score moyen : {avg}/10 ({len(results)} tests)", "CYAN")

    return results


# ─── CLI ────────────────────────────────────────────────────

def print_usage():
    """Afficher l'aide"""
    print(f"""
{C['MAGENTA']}{'='*60}
  🧬 EVOLVE Runner — Évaluateur et optimiseur d'agents GLM
{'='*60}{C['RESET']}

{C['BOLD']}Usage :{C['RESET']}
  python3 evolve_runner.py <commande> [options]

{C['BOLD']}Commandes :{C['RESET']}
  {C['GREEN']}eval <agent>{C['RESET']}      Évaluer un agent spécifique
  {C['GREEN']}eval-all{C['RESET']}           Évaluer tous les agents actifs
  {C['GREEN']}eval-direct <agent>{C['RESET']} Évaluer sans ACP (appel Ollama direct)
  {C['GREEN']}eval-collab{C['RESET']}         Évaluer les benchmarks de collaboration
  {C['GREEN']}eval-collab-direct{C['RESET']}   Collab sans ACP (Ollama direct)
  {C['CYAN']}analyze [agent]{C['RESET']}     Analyser les erreurs (global ou par agent)
  {C['YELLOW']}mutate <agent>{C['RESET']}     Générer une mutation du prompt
  {C['YELLOW']}apply <agent> <vN>{C['RESET']}  Appliquer une version mutée
  {C['RED']}rollback <agent>{C['RESET']}   Revenir à la version précédente
  {C['BLUE']}status{C['RESET']}             Vérifier les agents actifs
  {C['BLUE']}scores [agent]{C['RESET']}     Afficher les scores (global ou par agent)

{C['BOLD']}Exemples :{C['RESET']}
  python3 evolve_runner.py eval code
  python3 evolve_runner.py eval-all
  python3 evolve_runner.py analyze security
  python3 evolve_runner.py mutate code
  python3 evolve_runner.py apply code v2
  python3 evolve_runner.py rollback code
""")


async def show_scores(agent_name=None):
    """Afficher les scores"""
    scores_data = load_json(SCORES_FILE)
    evaluations = scores_data["evaluations"]

    if agent_name:
        evaluations = [e for e in evaluations if e["agent"] == agent_name]

    if not evaluations:
        log("Pas de scores disponibles", "YELLOW")
        return

    # Grouper par agent
    by_agent = {}
    for ev in evaluations:
        agent = ev["agent"]
        if agent not in by_agent:
            by_agent[agent] = []
        by_agent[agent].append(ev)

    log("\n📊 SCORES", "MAGENTA")
    log("-" * 50)
    for agent, evals in sorted(by_agent.items()):
        avg = round(sum(e["score_global"] for e in evals) / len(evals), 2)
        color = "GREEN" if avg >= 7 else "YELLOW" if avg >= 5 else "RED"
        log(f"  {agent:12} → {avg}/10 ({len(evals)} tests, version {get_current_prompt_version(agent)})", color)
        for ev in evals:
            log(f"    {ev['benchmark_id']:12} → {ev['score_global']}/10", "DIM")


async def main():
    """Point d'entrée CLI"""
    if len(sys.argv) < 2:
        print_usage()
        return

    cmd = sys.argv[1]

    if cmd == "eval" and len(sys.argv) >= 3:
        await evaluate_agent(sys.argv[2], use_acp=True)

    elif cmd == "eval-direct" and len(sys.argv) >= 3:
        await evaluate_agent(sys.argv[2], use_acp=False)

    elif cmd == "eval-all":
        await evaluate_all(use_acp=True)

    elif cmd == "eval-collab":
        await evaluate_collab(use_acp=True)

    elif cmd == "eval-collab-direct":
        await evaluate_collab(use_acp=False)

    elif cmd == "analyze":
        agent = sys.argv[2] if len(sys.argv) >= 3 else None
        await analyze_errors(agent)

    elif cmd == "mutate" and len(sys.argv) >= 3:
        await mutate_prompt(sys.argv[2])

    elif cmd == "apply" and len(sys.argv) >= 4:
        await apply_mutation(sys.argv[2], sys.argv[3])

    elif cmd == "rollback" and len(sys.argv) >= 3:
        await rollback(sys.argv[2])

    elif cmd == "status":
        active = await check_agents()
        if active:
            log(f"✅ Agents actifs : {', '.join(active)}", "GREEN")
        else:
            log("❌ Aucun agent actif", "RED")

    elif cmd == "scores":
        agent = sys.argv[2] if len(sys.argv) >= 3 else None
        await show_scores(agent)

    else:
        print_usage()


if __name__ == "__main__":
    asyncio.run(main())
