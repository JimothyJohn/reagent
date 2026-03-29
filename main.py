"""Reagent — OpenClaw Teams bot provisioning and management CLI."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "openclaw.json"
ENV_PATH = PROJECT_DIR / ".env"

SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new"]


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def load_env():
    """Load .env file into os.environ."""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def require_env(*keys: str):
    missing = [k for k in keys if not env(k)]
    if missing:
        print(f"ERROR: Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        print("Set them in .env and retry.", file=sys.stderr)
        sys.exit(1)


def save_env(updates: dict[str, str]):
    """Merge updates into .env, preserving comments and order."""
    lines: list[str] = []
    existing_keys: set[str] = set()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, _ = stripped.partition("=")
                key = key.strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    existing_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)
    for key, value in updates.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def bot_name() -> str:
    return env("BOT_NAME", "reagent-teams-bot")


def resource_group() -> str:
    return env("RESOURCE_GROUP", "reagent-rg")


def vm_name() -> str:
    return bot_name() + "-vm"


def vm_user() -> str:
    return env("VM_USER", "reagent")


def location() -> str:
    return env("LOCATION", "eastus")


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if check and result.returncode != 0:
        stderr = result.stderr if capture else ""
        print(f"Command failed: {' '.join(cmd)}\n{stderr}", file=sys.stderr)
        sys.exit(1)
    return result


def az(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["az", *args], check=check)


def az_json(*args: str, check: bool = True):
    r = az(*args, "-o", "json", check=check)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def ssh_target() -> str:
    return f"{vm_user()}@{env('VM_HOST')}"


def ssh_cmd(cmd: str) -> str:
    if not env("VM_HOST"):
        print("ERROR: VM_HOST not set.", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run(
        ["ssh", *SSH_OPTS, ssh_target(), cmd],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"SSH error: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def scp_to(local: str, remote: str):
    run(["scp", *SSH_OPTS, local, f"{ssh_target()}:{remote}"])


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

NGINX_CONF = r"""
server {
    listen 80 default_server;
    server_name _;

    location /api/messages {
        proxy_pass http://127.0.0.1:3978;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        return 404;
    }
}
""".strip()


SYSTEMD_UNIT = """[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory=/home/{user}
ExecStart=/usr/bin/openclaw
Restart=always
RestartSec=5
Environment=ANTHROPIC_API_KEY={anthropic_key}

[Install]
WantedBy=multi-user.target
"""


def step(msg: str):
    print(f"\n=> {msg}")


def setup():
    """Full first-time Azure infrastructure provisioning + VM setup."""

    # ---- Prerequisites ----------------------------------------------------
    step("Checking prerequisites")

    # az cli logged in?
    acct = az_json("account", "show")
    if not acct:
        print("ERROR: Not logged in to Azure CLI. Run 'az login' first.", file=sys.stderr)
        sys.exit(1)
    print(f"   Azure account: {acct.get('user', {}).get('name', 'unknown')}")
    az_email = acct.get("user", {}).get("name", "admin@example.com")
    tenant_id = acct.get("tenantId", "")

    # SSH key
    ssh_key = Path.home() / ".ssh" / "id_rsa.pub"
    if not ssh_key.exists():
        ssh_key = Path.home() / ".ssh" / "id_ed25519.pub"
    if not ssh_key.exists():
        print("ERROR: No SSH public key found (~/.ssh/id_rsa.pub or id_ed25519.pub).", file=sys.stderr)
        print("Generate one with: ssh-keygen", file=sys.stderr)
        sys.exit(1)
    print(f"   SSH key: {ssh_key}")

    # ANTHROPIC_API_KEY — prompt if not already set
    anthropic_key = env("ANTHROPIC_API_KEY")
    if not anthropic_key:
        anthropic_key = input("Enter your Anthropic API key: ").strip()
        if not anthropic_key:
            print("ERROR: Anthropic API key is required.", file=sys.stderr)
            sys.exit(1)
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key

    rg = resource_group()
    loc = location()
    bn = bot_name()
    vn = vm_name()
    user = vm_user()
    dns_label = bn  # DNS label derived from BOT_NAME

    # ---- Resource Group ---------------------------------------------------
    step(f"Creating resource group '{rg}' in {loc}")
    existing = az_json("group", "show", "--name", rg, check=False)
    if existing and existing.get("name"):
        print("   Already exists, skipping.")
    else:
        az("group", "create", "--name", rg, "--location", loc)
        print("   Created.")

    # ---- VM ---------------------------------------------------------------
    step(f"Creating VM '{vn}'")
    vm_info = az_json("vm", "show", "--resource-group", rg, "--name", vn, check=False)
    if vm_info and vm_info.get("name"):
        print("   VM already exists, skipping creation.")
    else:
        az("vm", "create",
           "--resource-group", rg,
           "--name", vn,
           "--image", "Canonical:ubuntu-24_04-lts:server:latest",
           "--size", "Standard_B1s",
           "--admin-username", user,
           "--ssh-key-values", str(ssh_key),
           "--public-ip-address-dns-name", dns_label,
           "--output", "none")
        print("   Created.")

    # Fetch VM public IP + DNS
    step("Fetching VM network info")
    ip_info = az_json("vm", "list-ip-addresses",
                       "--resource-group", rg, "--name", vn)
    ip_config = ip_info[0]["virtualMachine"]["network"]["publicIpAddresses"][0]
    vm_ip = ip_config["ipAddress"]
    vm_dns = ip_config.get("dnsSettings", {}).get("fqdn", "")
    if not vm_dns:
        vm_dns = f"{dns_label}.{loc}.cloudapp.azure.com"
    print(f"   IP: {vm_ip}")
    print(f"   DNS: {vm_dns}")

    # Store early so SSH commands work
    os.environ["VM_HOST"] = vm_dns

    # ---- NSG Ports --------------------------------------------------------
    step("Opening NSG ports (22, 80, 443, 3978)")
    nsg_name = f"{vn}NSG"
    ports = [
        ("AllowSSH", "22", 100),
        ("AllowHTTP", "80", 110),
        ("AllowHTTPS", "443", 120),
        ("AllowBotWebhook", "3978", 130),
    ]
    for rule_name, port, priority in ports:
        existing_rule = az_json("network", "nsg", "rule", "show",
                                 "--resource-group", rg,
                                 "--nsg-name", nsg_name,
                                 "--name", rule_name,
                                 check=False)
        if existing_rule and existing_rule.get("name"):
            print(f"   {rule_name} (port {port}) already exists.")
        else:
            az("network", "nsg", "rule", "create",
               "--resource-group", rg,
               "--nsg-name", nsg_name,
               "--name", rule_name,
               "--priority", str(priority),
               "--destination-port-ranges", port,
               "--access", "Allow",
               "--protocol", "Tcp",
               "--output", "none")
            print(f"   Opened port {port} ({rule_name}).")

    # ---- Azure AD App Registration ----------------------------------------
    step("Creating Azure AD app registration")
    # Check if app already exists by display name
    apps = az_json("ad", "app", "list", "--display-name", bn, check=False)
    if apps and len(apps) > 0:
        app_id = apps[0]["appId"]
        print(f"   App already exists: {app_id}")
    else:
        app_result = az_json("ad", "app", "create",
                              "--display-name", bn,
                              "--sign-in-audience", "AzureADMyOrg")
        app_id = app_result["appId"]
        print(f"   Created app: {app_id}")

    # Generate credential (password)
    step("Generating app credential")
    cred = az_json("ad", "app", "credential", "reset",
                    "--id", app_id, "--years", "2")
    app_password = cred["password"]
    print("   Credential generated.")

    # ---- Service Principal ------------------------------------------------
    step("Creating service principal")
    sp_exists = az_json("ad", "sp", "show", "--id", app_id, check=False)
    if sp_exists and sp_exists.get("appId"):
        print("   Service principal already exists.")
    else:
        az("ad", "sp", "create", "--id", app_id, "--output", "none")
        print("   Created.")

    # ---- Azure Bot Service ------------------------------------------------
    step(f"Creating Azure Bot Service '{bn}'")
    bot_exists = az_json("bot", "show",
                          "--resource-group", rg, "--name", bn, check=False)
    if bot_exists and bot_exists.get("name"):
        print("   Bot already exists, skipping creation.")
    else:
        az("bot", "create",
           "--resource-group", rg,
           "--name", bn,
           "--app-type", "SingleTenant",
           "--appid", app_id,
           "--tenant-id", tenant_id,
           "--sku", "F0",
           "--output", "none")
        print("   Created.")

    # ---- Teams Channel ----------------------------------------------------
    step("Enabling Teams channel")
    channels = az_json("bot", "channel", "list",
                        "--resource-group", rg, "--name", bn, check=False)
    teams_exists = False
    if channels:
        for ch in channels.get("value", channels if isinstance(channels, list) else []):
            ch_name = ch.get("name", "") if isinstance(ch, dict) else ""
            if "MsTeamsChannel" in ch_name:
                teams_exists = True
    if teams_exists:
        print("   Teams channel already enabled.")
    else:
        az("bot", "channel", "create",
           "--resource-group", rg, "--name", bn,
           "--channel-name", "MsTeamsChannel",
           "--output", "none")
        print("   Enabled.")

    # ---- VM Software Install ----------------------------------------------
    step("Installing software on VM (Node.js 22, OpenClaw, nginx, certbot)")
    ssh_cmd(
        "set -e && "
        # Node.js 22
        "if ! node --version 2>/dev/null | grep -q 'v22'; then "
        "  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && "
        "  sudo apt-get install -y nodejs; "
        "fi && "
        # OpenClaw
        "sudo npm install -g openclaw@latest && "
        # nginx + certbot
        "sudo apt-get install -y nginx certbot python3-certbot-nginx"
    )
    print("   Done.")

    # ---- Nginx Config -----------------------------------------------------
    step("Configuring nginx reverse proxy")
    # Write config via heredoc over SSH
    ssh_cmd(
        f"cat << 'NGINXEOF' | sudo tee /etc/nginx/sites-available/default > /dev/null\n"
        f"{NGINX_CONF}\n"
        f"NGINXEOF"
    )
    ssh_cmd("sudo nginx -t && sudo systemctl reload nginx")
    print("   Configured and reloaded.")

    # ---- TLS Certificate --------------------------------------------------
    step(f"Obtaining Let's Encrypt TLS certificate for {vm_dns}")
    ssh_cmd(
        f"sudo certbot --nginx -d {vm_dns} --non-interactive --agree-tos -m {az_email}"
    )
    print("   Certificate obtained.")

    # ---- Systemd Service --------------------------------------------------
    step("Setting up OpenClaw systemd service")
    unit_content = SYSTEMD_UNIT.format(user=user, anthropic_key=anthropic_key)
    ssh_cmd(
        f"cat << 'UNITEOF' | sudo tee /etc/systemd/system/openclaw.service > /dev/null\n"
        f"{unit_content}\n"
        f"UNITEOF"
    )
    ssh_cmd("sudo systemctl daemon-reload && sudo systemctl enable openclaw")
    print("   Service installed and enabled.")

    # ---- Create .openclaw directory on VM ---------------------------------
    ssh_cmd(f"mkdir -p /home/{user}/.openclaw")

    # ---- Deploy Config ----------------------------------------------------
    step("Deploying openclaw.json config")
    config = json.loads(CONFIG_PATH.read_text())
    config["channels"]["msteams"]["appId"] = app_id
    config["channels"]["msteams"]["appPassword"] = app_password
    config["channels"]["msteams"]["tenantId"] = tenant_id

    tmp = PROJECT_DIR / ".openclaw-deploy.json"
    tmp.write_text(json.dumps(config, indent=2))
    scp_to(str(tmp), f"/home/{user}/.openclaw/openclaw.json")
    tmp.unlink()
    print("   Config deployed.")

    # ---- Start OpenClaw ---------------------------------------------------
    ssh_cmd("sudo systemctl restart openclaw")
    print("   OpenClaw started.")

    # ---- Update Bot Endpoint ----------------------------------------------
    step("Updating Azure Bot messaging endpoint")
    endpoint = f"https://{vm_dns}/api/messages"
    az("bot", "update",
       "--resource-group", rg, "--name", bn,
       "--endpoint", endpoint,
       "--output", "none")
    print(f"   Endpoint set to {endpoint}")

    # ---- Save .env --------------------------------------------------------
    step("Saving discovered values to .env")
    save_env({
        "ANTHROPIC_API_KEY": anthropic_key,
        "MSTEAMS_APP_ID": app_id,
        "MSTEAMS_APP_PASSWORD": app_password,
        "MSTEAMS_TENANT_ID": tenant_id,
        "VM_HOST": vm_dns,
        "VM_IP": vm_ip,
        "VM_USER": user,
        "RESOURCE_GROUP": rg,
        "BOT_NAME": bn,
    })
    print("   .env updated.")

    # ---- Summary ----------------------------------------------------------
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print(f"  Resource Group:  {rg}")
    print(f"  VM:              {vn} ({vm_ip})")
    print(f"  DNS:             {vm_dns}")
    print(f"  Bot Name:        {bn}")
    print(f"  App ID:          {app_id}")
    print(f"  Tenant ID:       {tenant_id}")
    print(f"  Bot Endpoint:    {endpoint}")
    print()
    print("Next steps:")
    print("  1. Package the Teams app:  ./scripts/package-teams-app.sh")
    print("  2. Sideload the .zip in Teams Admin Center or directly in Teams")
    print("  3. Check status:           uv run python main.py status")
    print("  4. View logs:              uv run python main.py logs")


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------

def deploy():
    """Push config changes to existing VM and restart OpenClaw."""
    require_env("MSTEAMS_APP_ID", "MSTEAMS_APP_PASSWORD", "MSTEAMS_TENANT_ID", "ANTHROPIC_API_KEY")

    app_id = env("MSTEAMS_APP_ID")
    app_password = env("MSTEAMS_APP_PASSWORD")
    tenant_id = env("MSTEAMS_TENANT_ID")
    anthropic_key = env("ANTHROPIC_API_KEY")
    user = vm_user()

    if not env("VM_HOST"):
        print("ERROR: VM_HOST not set in .env. Run setup first.", file=sys.stderr)
        sys.exit(1)

    # Build config with secrets
    step("Building config with secrets")
    config = json.loads(CONFIG_PATH.read_text())
    config["channels"]["msteams"]["appId"] = app_id
    config["channels"]["msteams"]["appPassword"] = app_password
    config["channels"]["msteams"]["tenantId"] = tenant_id

    tmp = PROJECT_DIR / ".openclaw-deploy.json"
    tmp.write_text(json.dumps(config, indent=2))

    # Push config
    step("Uploading openclaw.json to VM")
    scp_to(str(tmp), f"/home/{user}/.openclaw/openclaw.json")
    tmp.unlink()
    print("   Done.")

    # Update ANTHROPIC_API_KEY in systemd service if changed
    step("Updating ANTHROPIC_API_KEY in systemd service")
    ssh_cmd(
        f"sudo sed -i 's|^Environment=ANTHROPIC_API_KEY=.*|Environment=ANTHROPIC_API_KEY={anthropic_key}|' "
        f"/etc/systemd/system/openclaw.service && sudo systemctl daemon-reload"
    )
    print("   Done.")

    # Restart
    step("Restarting OpenClaw")
    ssh_cmd("sudo systemctl restart openclaw")
    print("   Restarted.")

    # Verify
    step("Verifying service is running")
    time.sleep(3)
    output = ssh_cmd("sudo systemctl is-active openclaw")
    if output == "active":
        print("   OpenClaw is running.")
    else:
        print(f"   WARNING: Service status is '{output}'. Check logs with: uv run python main.py logs",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def status():
    """Check if OpenClaw gateway is running on the VM."""
    if not env("VM_HOST"):
        print("ERROR: VM_HOST not set in .env. Run setup first.", file=sys.stderr)
        sys.exit(1)
    print("Checking OpenClaw status on VM...")
    print(ssh_cmd("sudo systemctl status openclaw --no-pager"))


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

def logs():
    """Tail recent OpenClaw gateway logs."""
    if not env("VM_HOST"):
        print("ERROR: VM_HOST not set in .env. Run setup first.", file=sys.stderr)
        sys.exit(1)
    print(ssh_cmd("sudo journalctl -u openclaw -n 50 --no-pager"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    commands = {
        "setup": setup,
        "deploy": deploy,
        "status": status,
        "logs": logs,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(f"Usage: uv run python main.py <{'|'.join(commands)}>")
        print()
        print("Commands:")
        print("  setup   Full first-time Azure infrastructure provisioning + VM setup")
        print("  deploy  Push config changes to existing VM and restart OpenClaw")
        print("  status  Check if OpenClaw gateway is running")
        print("  logs    Tail gateway logs")
        sys.exit(1)

    load_env()
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
