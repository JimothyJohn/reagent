# Reagent — Monthly Azure Costs

All resources are in resource group `reagent-rg` in **East US**.

| Resource | SKU / Tier | Monthly Cost (est.) | Notes |
|---|---|---|---|
| Linux VM | Standard_B1s (1 vCPU, 1 GiB RAM) | **~$7.59** | 24/7 running; Ubuntu 24.04 |
| OS Disk | Standard HDD, 30 GiB (P4 managed disk) | **~$1.54** | Default with VM |
| Public IP | Standard SKU, static | **~$3.65** | Static IP with DNS label |
| Azure Bot | F0 (Free) | **$0.00** | Unlimited messages in standard channels |
| Azure AD App Registration | Free | **$0.00** | Single-tenant app |
| Network (egress) | First 100 GB/mo free | **~$0.00** | Text-only Teams messages are negligible |
| **Total** | | **~$12.78/mo** | |

## Cost optimization

- **Deallocate when idle**: `az vm deallocate --resource-group reagent-rg --name reagent-vm` — stops compute billing (disk + IP still ~$5.19/mo)
- **Reserved Instance**: 1-year RI for B1s brings compute to ~$4.75/mo
- **Tear down everything**: `az group delete --name reagent-rg --yes --no-wait` — removes all resources, stops all charges
