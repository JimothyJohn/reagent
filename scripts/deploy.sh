#!/usr/bin/env bash
# Deploy or update OpenClaw config on the reagent VM
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load env
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a; source "$PROJECT_DIR/.env"; set +a
fi

VM="${VM_USER:-reagent}@${VM_HOST:-reagent-bot.eastus.cloudapp.azure.com}"

echo "Deploying OpenClaw config to $VM..."

# Push updated config
scp "$PROJECT_DIR/openclaw.json" "$VM:~/.openclaw/openclaw.json"

# Restart the service
ssh "$VM" "sudo systemctl restart openclaw && sleep 2 && sudo systemctl status openclaw --no-pager"

echo "Deploy complete."
