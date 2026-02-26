#!/usr/bin/env python3
"""
tmux-monitor — Met à jour les pane titles avec les stats de chaque agent Ollama
Format: qwen3-coder │ ● 12K/80K (15%) █░░░░░░░░░ │ 📨 5 │ CODE
"""

import subprocess
import json
import time
import sys
import urllib.request

SESSION = "agents"
try:
    INTERVAL = max(1, min(int(sys.argv[1]), 300)) if len(sys.argv) > 1 else 5
except (ValueError, IndexError):
    INTERVAL = 5

# 9 agents Ollama (ports 8002-8010)
AGENTS = [
    {"pane": 0, "port": 8002, "name": "VISION",   "model_short": "qwen3-vl"},
    {"pane": 1, "port": 8003, "name": "CODE",     "model_short": "qwen3-coder"},
    {"pane": 2, "port": 8004, "name": "GENERAL",  "model_short": "minimax"},
    {"pane": 3, "port": 8005, "name": "FRONT",    "model_short": "devstral-s"},
    {"pane": 4, "port": 8006, "name": "BACK",     "model_short": "devstral"},
    {"pane": 5, "port": 8007, "name": "SECURITY", "model_short": "cogito"},
    {"pane": 6, "port": 8008, "name": "I18N",     "model_short": "qwen3.5"},
    {"pane": 7, "port": 8009, "name": "DESIGN",   "model_short": "kimi"},
    {"pane": 8, "port": 8010, "name": "LEGAL",    "model_short": "gpt-oss"},
]


def tmux(*args):
    r = subprocess.run(["tmux"] + list(args), capture_output=True, text=True)
    return r.stdout.strip()


def setup_tmux():
    """Configure les pane borders pour la session agents."""
    tmux("set-option", "-t", SESSION, "pane-border-status", "top")
    tmux("set-option", "-t", SESSION, "pane-border-lines", "heavy")
    tmux("set-option", "-t", SESSION, "pane-active-border-style", "fg=green,bold")
    tmux("set-option", "-t", SESSION, "pane-border-style", "fg=colour240")
    tmux("set-option", "-t", SESSION, "allow-rename", "off")
    tmux("set-option", "-t", SESSION, "automatic-rename", "off")
    tmux("set-option", "-t", SESSION, "pane-border-format",
         " #{?pane_active,#[fg=colour46 bold bg=colour235],#[fg=green bg=colour235]}#{pane_title} ")


def fetch_status(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/status")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_telemetry(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/telemetry")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def format_tokens(t):
    if t >= 1_000_000:
        return f"{t / 1_000_000:.1f}M"
    elif t >= 1_000:
        return f"{t // 1_000}K"
    return str(t)


def make_bar(pct):
    filled = min(max(int(pct / 10), 0), 10)
    return "\u2588" * filled + "\u2591" * (10 - filled)


def indicator(pct):
    if pct >= 80:
        return "\u25cf"  # ● (rouge dans tmux via couleur pane)
    elif pct >= 50:
        return "\u25cf"  # ● (jaune)
    return "\u25cf"       # ● (vert)


def build_title(agent, data, telemetry=None):
    if not data:
        return f"{agent['model_short']} | OFFLINE | {agent['name']}"

    tokens = data.get("total_tokens_used", 0)
    ctx_len = data.get("context_length", 0)
    pct = int(data.get("context_usage_pct", 0))
    msgs = data.get("messages", 0)

    ctx_k = f"{ctx_len // 1000}K" if ctx_len >= 1000 else str(ctx_len)
    tok_d = format_tokens(tokens)
    bar = make_bar(pct)

    # TPS depuis telemetry
    tps_str = ""
    if telemetry:
        tps = telemetry.get("current_tps", 0)
        if tps > 0:
            tps_str = f" | \u26a1{tps:.1f}t/s"

    return f"{agent['model_short']} | {indicator(pct)} {tok_d}/{ctx_k} ({pct}%) {bar}{tps_str} | \U0001f4e8 {msgs} | {agent['name']}"


def main():
    setup_tmux()
    print(f"Monitor actif — 9 agents — refresh {INTERVAL}s — Ctrl+C pour arrêter", flush=True)

    try:
        while True:
            for agent in AGENTS:
                target = f"{SESSION}:0.{agent['pane']}"
                data = fetch_status(agent["port"])
                telemetry = fetch_telemetry(agent["port"])
                title = build_title(agent, data, telemetry)
                tmux("select-pane", "-t", target, "-T", title)

            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nMonitor arrêté.")


if __name__ == "__main__":
    main()
