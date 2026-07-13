#!/bin/bash
# ── OmegaNexus State Fix Script ──
# Run this to sync your Azure resources with Terraform

SUB_ID="ecc63471-f21a-46af-a01f-2db799285343"
RG="rg-omega-nexus"

echo "Syncing Backend..."
terraform import azurerm_container_app.backend /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/containerApps/ca-omega-backend

echo "Syncing Agent..."
terraform import azurerm_container_app.agent /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/containerApps/ca-omega-agent

echo "Syncing Frontend..."
terraform import azurerm_container_app.frontend /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/containerApps/ca-omega-frontend

echo "State sync complete! You can now run 'terraform apply' safely."
