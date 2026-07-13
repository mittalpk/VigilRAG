# OmegaNexus Terraform Fix - IMMEDIATE ACTION

## ⏱️ Quick Fix (5 minutes)

```bash
cd ~/MyProjects/SecureAgentRuntime/OmegaNexus/terraform/

# 1. Import existing secrets into Terraform state
terraform import azurerm_key_vault_secret.github_pat \
  "kv-omega-nexus-ecc63471/github-pat"
  
terraform import azurerm_key_vault_secret.gemini_api_key \
  "kv-omega-nexus-ecc63471/gemini-api-key"
  
terraform import azurerm_key_vault_secret.azure_storage_connection_string \
  "kv-omega-nexus-ecc63471/azure-storage-connection-string"
  
terraform import azurerm_key_vault_secret.admin_username \
  "kv-omega-nexus-ecc63471/admin-username"
  
terraform import azurerm_key_vault_secret.admin_password \
  "kv-omega-nexus-ecc63471/admin-password"
  
terraform import azurerm_key_vault_secret.internal_api_key \
  "kv-omega-nexus-ecc63471/X-Internal-API-Key"

# 2. Verify all imports succeeded
terraform state list | grep key_vault_secret

# 3. Plan the changes
terraform plan

# 4. Apply changes
terraform apply -auto-approve
```

---

## 🔧 Or Use The Import Script

```bash
cd ~/MyProjects/SecureAgentRuntime/OmegaNexus/terraform/
bash import_secrets.sh
terraform plan
terraform apply
```

---

## 📝 Frontend Image - Choose One Option

**BEFORE running `terraform apply`, update the frontend image**:

### Option A: Use Azure Container Registry (Best for Production)

```bash
# Check if ACR exists
az acr show --name omegaregistry

# Build and push frontend
cd ~/MyProjects/SecureAgentRuntime/OmegaNexus/frontend/
az acr build --registry omegaregistry --image omega-nexus-frontend:latest .

# Update terraform/main.tf line ~420:
# Change:
#   image = "ghcr.io/mittalpk/omega-nexus-frontend:268c0a6c6340f2afa14c5b559bb225b8f277338f"
# To:
#   image = "omegaregistry.azurecr.io/omega-nexus-frontend:latest"
```

### Option B: Use Public Test Image (Quick Testing)

```bash
# Just update terraform/main.tf line ~420:
# image = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
```

---

## ✅ Verify the Fix

```bash
# Check all services running
az containerapp list \
  --resource-group rg-omega-nexus \
  --query "[].{name:name, state:properties.provisioningState}" \
  -o table

# Check backend logs (should have NO "API Key mismatch" errors)
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --tail 50 | grep -i "key\|auth\|error"

# Test the Knowledge API
INTERNAL_KEY=$(az keyvault secret show \
  --vault-name "kv-omega-nexus-ecc63471" \
  --name "X-Internal-API-Key" \
  -o tsv --query value)

curl -X POST "https://ca-omega-backend.<DOMAIN>/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: $INTERNAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"test","target_systems":["code_repos"]}'

# Expected: HTTP 200 (not 401)
```

---

## 📊 What's Changed

| Issue | Root Cause | Fix Applied |
|-------|-----------|------------|
| "Resource already exists" | Secrets created manually, not in Terraform state | Import secrets via `terraform import` |
| "Unable to get value using Managed Identity" | Access policy created AFTER Container Apps | Added `depends_on` to ensure proper ordering |
| "UNAUTHORIZED authentication required" | Container Registry credentials missing | Update frontend image to ACR or test image |

---

## 🚨 If Something Goes Wrong

```bash
# Destroy and start fresh (⚠️ deletes everything)
terraform destroy -auto-approve

# Or just rollback the Container Apps
az containerapp update \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --image "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"

# Check Terraform state
terraform state list
terraform state show azurerm_key_vault_secret.internal_api_key

# Remove a specific resource from state (if needed)
terraform state rm azurerm_key_vault_secret.internal_api_key
```

---

## 📞 Get Help

For detailed explanations:
- See [TERRAFORM_FIX.md](./TERRAFORM_FIX.md) - Full troubleshooting guide
- See [AUTHENTICATION_FIX.md](./AUTHENTICATION_FIX.md) - Auth setup details  
- See [ARCHITECTURE.md](./ARCHITECTURE.md) - System design

**Time to complete**: 5-10 minutes
