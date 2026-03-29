# reagent

<p align="center">
  <img src="docs/hero.svg" alt="reagent architecture" width="700">
</p>

Self-hosted AI assistant for Microsoft Teams, powered by [OpenClaw](https://docs.openclaw.ai). Deploys on an Azure B1s Linux VM with nginx + Let's Encrypt for HTTPS, using Anthropic Claude as the AI model.

## Prerequisites

- **Azure subscription** with permissions to create resources
- **Azure CLI** (`az`) installed and logged in (`az login`)
- **SSH key** at `~/.ssh/id_ed25519` or `~/.ssh/id_rsa`
- **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com))
- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)**

## Quick start

```bash
git clone https://github.com/nkuhn-vmw/reagent.git
cd reagent
uv run python main.py setup    # provisions Azure infra + VM (~5 min)
./scripts/package-teams-app.sh  # builds Teams app zip
```

Then sideload `reagent-teams-app.zip` in Teams: **Apps > Manage your apps > Upload a custom app** > select `reagent-teams-app.zip`.

> **Note:** Requires a Microsoft 365 Business or Education account. Custom app uploading must be enabled in [Teams Admin Center](https://admin.teams.microsoft.com) > Teams apps > Setup policies > Global > Upload custom apps > On.

## CLI

```bash
uv run python main.py setup    # provision Azure infra + VM
uv run python main.py deploy   # push config & secrets to VM, restart gateway
uv run python main.py status   # check if gateway is running
uv run python main.py logs     # tail gateway logs
```

## Configuration

- **`openclaw.json`** — OpenClaw gateway config (model, system prompt, Teams channel settings)
- **`.env`** — secrets (API keys, bot credentials); copy from `.env.example`
- On `deploy`, secrets from `.env` are injected into the gateway config on the VM

## Costs

~$12.78/mo for the Azure VM + static IP. Bot Service is free. See [COSTS.md](COSTS.md) for a full breakdown.

## License

MIT
