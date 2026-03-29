"""Reagent — OpenClaw Teams bot management CLI."""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "openclaw.json"
ENV_PATH = PROJECT_DIR / ".env"


def load_env():
    """Load .env file into os.environ."""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


load_env()

VM_HOST = os.environ.get("VM_HOST", "")
VM_USER = os.environ.get("VM_USER", "reagent")


def ssh(cmd: str) -> str:
    """Run a command on the remote VM via SSH."""
    if not VM_HOST:
        print("ERROR: VM_HOST not set. Copy .env.example to .env and fill in your values.", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run(
        ["ssh", f"{VM_USER}@{VM_HOST}", cmd],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"SSH error: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def status():
    """Check if OpenClaw gateway is running on the VM."""
    print("Checking OpenClaw status on VM...")
    print(ssh("sudo systemctl status openclaw --no-pager"))


def deploy():
    """Build config from env vars, push to VM, and restart."""
    app_id = os.environ.get("MSTEAMS_APP_ID", "")
    app_password = os.environ.get("MSTEAMS_APP_PASSWORD", "")
    tenant_id = os.environ.get("MSTEAMS_TENANT_ID", "")

    if not all([app_id, app_password, tenant_id]):
        print("ERROR: Set MSTEAMS_APP_ID, MSTEAMS_APP_PASSWORD, and MSTEAMS_TENANT_ID in .env", file=sys.stderr)
        sys.exit(1)

    # Build full config with secrets injected
    config = json.loads(CONFIG_PATH.read_text())
    config["channels"]["msteams"]["appId"] = app_id
    config["channels"]["msteams"]["appPassword"] = app_password
    config["channels"]["msteams"]["tenantId"] = tenant_id

    tmp = PROJECT_DIR / ".openclaw-deploy.json"
    tmp.write_text(json.dumps(config, indent=2))

    print("Deploying config...")
    subprocess.run(
        ["scp", str(tmp), f"{VM_USER}@{VM_HOST}:~/.openclaw/openclaw.json"],
        check=True,
    )
    tmp.unlink()
    print(ssh("sudo systemctl restart openclaw && echo 'Restarted OK'"))


def logs():
    """Tail recent OpenClaw gateway logs."""
    print(ssh("sudo journalctl -u openclaw -n 50 --no-pager"))


def main():
    commands = {"status": status, "deploy": deploy, "logs": logs}

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(f"Usage: python main.py <{'|'.join(commands)}>")
        sys.exit(1)

    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
