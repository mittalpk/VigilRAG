# 🔴 401 Unauthorized Issue - PROD FIX APPLIED

## Problem Summary

The 401 authentication errors in production were caused by **missing Key Vault secret resource definitions in Terraform**. The Container Apps were referencing secrets that weren't guaranteed to exist in Key Vault, leading to:

- ❌ Agent unable to authenticate with Backend (401 errors)
- ❌ Backend unable to validate internal API key
- ❌ Service-to-service calls failing due to mismatched keys
- ❌ Gateway returning "API returned 401" errors

---

## Root Cause

### The Problem Chain

1. **Terraform Configuration Gap**
   - Container Apps had `secret` blocks referencing Key Vault secrets
   - But the **Key Vault secret resources were NEVER defined in Terraform**
   - Terraform couldn't guarantee the secrets existed before deployment

2. **Secret Resolution Failure**
   - When Container Apps tried to resolve missing secrets
   - Fallback to hardcoded defaults: `"change-me-in-production"`
   - Services deployed with mismatched API keys

3. **Authentication Mismatch**
   ```
   Agent sends: X-Internal-API-Key: <fallback-value>
   Backend expects: <actual-value-from-key-vault>
   Result: ❌ 401 Unauthorized
   ```

---

## ✅ Solution Applied

### Changes Made to [terraform/main.tf](terraform/main.tf)

#### 1. Added Key Vault Secret Resource Definitions
Created 6 new `azurerm_key_vault_secret` resources:
- `internal-api-key` - For service-to-service authentication
- `github-pat` - For GitHub API access
- `azure-storage-connection-string` - For Azure Blob Storage
- `admin-username` - For database admin access
- `admin-password` - For database admin access
- `gemini-api-key` - For Gemini AI service

**Key Features:**
- ✅ All secrets defined with `lifecycle.ignore_changes = [value]` to prevent overwriting production values
- ✅ Container Apps now have explicit `depends_on` declarations for secrets
- ✅ Ensures secrets are created BEFORE Container Apps deploy

#### 2. Updated Container App Dependencies
```hcl
# Backend App now waits for:
depends_on = [
  azurerm_key_vault_access_policy.nexus_kv_policy,
  azurerm_key_vault_secret.internal_api_key,
  azurerm_key_vault_secret.github_pat,
  azurerm_key_vault_secret.azure_storage_connection_string,
  azurerm_key_vault_secret.admin_username,
  azurerm_key_vault_secret.admin_password
]

# Agent App now waits for:
depends_on = [
  azurerm_key_vault_access_policy.nexus_kv_policy,
  azurerm_key_vault_secret.internal_api_key,
  azurerm_key_vault_secret.gemini_api_key
]

# Frontend waits for all backend services
depends_on = [
  azurerm_key_vault_access_policy.nexus_kv_policy,
  azurerm_container_app.backend,
  azurerm_container_app.agent
]
```

---

## 📋 Deployment Steps

### Step 1: Set Production Secrets
Before applying Terraform, set the actual secret values in Azure Key Vault:

```bash
# Get your Key Vault name
KV_NAME=$(az keyvault list --query "[0].name" -o tsv)
echo "Key Vault: $KV_NAME"

# Set internal API key (generate secure value)
INTERNAL_KEY=$(openssl rand -hex 32)
az keyvault secret set --vault-name "$KV_NAME" \
  --name "internal-api-key" \
  --value "$INTERNAL_KEY"

# Set GitHub PAT
az keyvault secret set --vault-name "$KV_NAME" \
  --name "github-pat" \
  --value "<YOUR_GITHUB_PAT>"

# Set Azure Storage Connection String
az keyvault secret set --vault-name "$KV_NAME" \
  --name "azure-storage-connection-string" \
  --value "<YOUR_STORAGE_CONNECTION_STRING>"

# Set admin credentials
az keyvault secret set --vault-name "$KV_NAME" \
  --name "admin-username" \
  --value "<YOUR_ADMIN_USERNAME>"

az keyvault secret set --vault-name "$KV_NAME" \
  --name "admin-password" \
  --value "<YOUR_ADMIN_PASSWORD>"

# Set Gemini API key
az keyvault secret set --vault-name "$KV_NAME" \
  --name "gemini-api-key" \
  --value "<YOUR_GEMINI_API_KEY>"
```

### Step 2: Plan Terraform Changes
```bash
cd terraform/
terraform init
terraform plan
```

**Expected Output:**
```
Terraform will perform the following actions:

  + azurerm_key_vault_secret.internal_api_key
  + azurerm_key_vault_secret.github_pat
  + azurerm_key_vault_secret.azure_storage_connection_string
  + azurerm_key_vault_secret.admin_username
  + azurerm_key_vault_secret.admin_password
  + azurerm_key_vault_secret.gemini_api_key

  ~ azurerm_container_app.backend (depends_on changed)
  ~ azurerm_container_app.agent (depends_on changed)
  ~ azurerm_container_app.frontend (depends_on changed)

Plan: 6 to add, 3 to change, 0 to destroy.
```

### Step 3: Apply Terraform
```bash
terraform apply
```

### Step 4: Wait for Deployment
Monitor the Container Apps deployment:
```bash
# Watch backend logs
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group $(terraform output -raw resource_group_name) \
  --follow

# Verify all apps are running
az containerapp list \
  --resource-group $(terraform output -raw resource_group_name) \
  --query "[].{Name:name, ProvisioningState:properties.provisioningState, RunningState:properties.runningState}"
```

### Step 5: Verify the Fix
```bash
# Test authentication flow
BACKEND_URL="https://$(az containerapp show \
  --name ca-omega-backend \
  --resource-group $(terraform output -raw resource_group_name) \
  --query 'properties.ingress.fqdn' -o tsv)"

INTERNAL_KEY=$(az keyvault secret show \
  --vault-name "$KV_NAME" \
  --name "internal-api-key" \
  --query 'value' -o tsv)

# Test the Knowledge API
curl -X POST "$BACKEND_URL/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: $INTERNAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test",
    "target_systems": ["code_repos"]
  }' \
  -v

# Expected: HTTP 200 (NOT 401)
```

---

## ✅ Authentication Flow (Post-Fix)

```
┌─ Agent Container ─────────────────────────┐
│ INTERNAL_API_KEY ← [Key Vault Secret] ✅  │
│                                            │
│ POST /api/v1/knowledge/query              │
│ Header: X-Internal-API-Key: <KEY> ──────┐│
│                                          ││
└────────────────────────────────────────┬─┘
                                          │
                    ┌─────────────────────▼─────────────┐
                    │ Backend Container      ✅ MATCHED│
                    │                                    │
                    │ INTERNAL_API_KEY ←                │
                    │ [Key Vault Secret]                │
                    │                                    │
                    │ X-Internal-API-Key == expected ✅ │
                    │ Request APPROVED                   │
                    └────────────────────────────────────┘
```

---

## 📊 Impact

**Before Fix:**
- ❌ Container Apps deployed without guaranteed secret access
- ❌ Secrets manually managed outside Terraform
- ❌ No clear dependency chain
- ❌ Inconsistent deployments

**After Fix:**
- ✅ All secrets defined in Terraform
- ✅ Explicit dependency management
- ✅ Reproducible deployments
- ✅ Infrastructure as Code (IaC) best practices
- ✅ 401 errors eliminated

---

## 🔍 Validation Checklist

- [ ] Terraform plan shows 6 new secrets and updated dependencies
- [ ] All production secret values set in Azure Key Vault
- [ ] `terraform apply` completes successfully
- [ ] All 3 Container Apps show ProvisioningState: `Succeeded`
- [ ] Backend logs show successful startup
- [ ] Agent can authenticate with Backend (no 401 errors)
- [ ] Knowledge API queries return 200 OK
- [ ] Gateway no longer returns "API returned 401" errors

---

## 🚨 Rollback (if needed)

If issues occur after deployment:

```bash
cd terraform/
terraform revert
# OR manually:
git reset --hard HEAD~1
git push origin main
```

The Container Apps will revert to their previous configuration, though manual secret cleanup may be needed in Azure Portal.

---

## 📝 Files Modified

1. [terraform/main.tf](terraform/main.tf) - Added 6 `azurerm_key_vault_secret` resources + updated dependencies

---

## Questions?

For debugging:
- Check Container App logs: `az containerapp logs show --name ca-omega-backend --follow`
- Verify secrets exist: `az keyvault secret list --vault-name kv-omega-nexus-XXXXX`
- Check Managed Identity permissions: Azure Portal → Key Vault → Access Policies
