#!/bin/bash
set -euo pipefail

for pyname in python3 python py; do
    if command -v "$pyname" >/dev/null 2>&1; then
        break
    fi
done

if ! command -v "$pyname" >/dev/null 2>&1; then
    echo "No python3 binary found on PATH." >&2
    exit 1
fi

if ! command -v "ollama" >/dev/null 2>&1; then
    read -p "Ollama not found. Install it now? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        curl -fsSL https://ollama.com/install.sh | sh
    else
        echo "Ollama is required for AgentGuard, please install it." >&2
        exit 1
    fi
fi

$pyname -m venv venv
venv/bin/$pyname -m pip install -r requirements.txt

ollama pull qwen2.5:7b

sleep 1; clear

BANNER=$(cat << 'EOF'

    _                    _    ____                     _
   / \   __ _  ___ _ __ | |_ / ___|_   _  __ _ _ __ __| |
  / _ \ / _` |/ _ \ '_ \| __| |  _| | | |/ _` | '__/ _` |
 / ___ \ (_| |  __/ | | | |_| |_| | |_| | (_| | | | (_| |
/_/   \_\__, |\___|_| |_|\__|\____|\__,_|\__,_|_|  \__,_|
        |___/
EOF
)

printf "%s\n\n" "$BANNER"
venv/bin/$pyname main.py -h
printf "\n\033[0;31mRemember to source venv/bin/activate!\n\033[0m"
