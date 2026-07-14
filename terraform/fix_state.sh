#!/bin/bash
# ── OmegaNexus State Fix Script ──
# Run this to sync your Azure resources with Terraform
# Usage: SUB_ID=<your-subscription-id> ./fix_state.sh

SUB_ID="${SUB_ID:?Set SUB_ID to your Azure subscription ID before running this script}"
RG="rg-omega-nexus"

echo "Syncing Backend..."
terraform import azurerm_container_app.backend /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/containerApps/ca-omega-backend

echo "Syncing Agent..."
terraform import azurerm_container_app.agent /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/containerApps/ca-omega-agent

echo "Syncing Frontend..."
terraform import azurerm_container_app.frontend /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/containerApps/ca-omega-frontend

echo "State sync complete! You can now run 'terraform apply' safely."
