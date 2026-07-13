# OmegaNexus Terraform Deployment - Error Resolution Guide

**Status**: 3 critical errors preventing deployment

---

## Error 1: "Resource Already Exists" - Key Vault Secrets

**Root Cause**: Key Vault secrets were created manually, but Terraform doesn't know about them. When you try to create them again, Azure says they already exist.

**Resources Affected**:
- `azure-storage-connection-string`
- `admin-password`
- `X-Internal-API-Key` (newly added)

**Solution: Import Existing Secrets into Terraform State**

```bash
cd terraform/

# Import each existing secret
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
```

**Or use the automated script**:
```bash
cd terraform/
bash import_secrets.sh
```

**Verify import succeeded**:
```bash
terraform state list | grep azurerm_key_vault_secret
# Should show all 6 secrets
```

---

## Error 2: "Unable to get value using Managed Identity" - Access Policy

**Root Cause**: The Managed Identity (`id-omega-nexus`) doesn't have permission to access Key Vault secrets when Container Apps try to use them.

**Reason**: Terraform processes resources in parallel. The access policy was being created AFTER the Container Apps, so permissions weren't in place yet.

**Solution Already Applied**: ✅ Added explicit `depends_on` to Container Apps

**Changes Made to `terraform/main.tf`**:
```hcl
resource "azurerm_container_app" "backend" {
  depends_on = [azurerm_key_vault_access_policy.nexus_kv_policy]
  ...
}

resource "azurerm_container_app" "agent" {
  depends_on = [azurerm_key_vault_access_policy.nexus_kv_policy]
  ...
}
```

This ensures:
1. ✅ Access policy is created FIRST
2. ✅ Managed Identity permissions are granted
3. ✅ THEN Container Apps are created
4. ✅ Container Apps can now access secrets

---

## Error 3: "UNAUTHORIZED: authentication required" - Container Registry

**Root Cause**: Container Apps trying to pull image from GitHub Container Registry (ghcr.io) but no credentials provided.

**Affected Resource**: `ca-omega-frontend` 

**Error Details**:
```
Invalid value: "ghcr.io/mittalpk/omega-nexus-frontend:268c0a6c6340f2afa14c5b559bb225b8f277338f"
GET https: UNAUTHORIZED: authentication required
```

**Solution Options**:

### Option A: Use Azure Container Registry (Recommended for Production)

1. **Build and push image to ACR**:
```bash
az acr build \
  --registry omegaregistry \
  --image omega-nexus-frontend:latest \
  ./frontend
```

2. **Update terraform/main.tf** to use ACR image:
```hcl
image = "omegaregistry.azurecr.io/omega-nexus-frontend:latest"
```

3. **Container Apps will auto-authenticate** using Managed Identity

### Option B: GitHub Container Registry with PAT Token

**Not recommended** - requires additional secrets management

### Option C: Use Public/Test Image Temporarily

For testing, use a simple test image:
```hcl
image = "ghcr.io/gbaeke/hello-world:latest"  # Public image for testing
```

---

## Complete Fix Process

### Step 1: Import Existing Secrets (Fixes Error 1)

```bash
cd terraform/

# Use the provided script
bash import_secrets.sh

# Verify
terraform state list | grep key_vault_secret
```

**Expected Output**:
```
azurerm_key_vault_secret.admin_password
azurerm_key_vault_secret.admin_username
azurerm_key_vault_secret.azure_storage_connection_string
azurerm_key_vault_secret.gemini_api_key
azurerm_key_vault_secret.github_pat
azurerm_key_vault_secret.internal_api_key
```

### Step 2: Update Frontend Image (Fixes Error 3)

**File**: `terraform/main.tf`

Option A - Update to use ACR:
```bash
# Find the frontend container resource around line 390
# Change from:
image = "ghcr.io/mittalpk/omega-nexus-frontend:268c0a6c6340f2afa14c5b559bb225b8f277338f"

# To:
image = "omegaregistry.azurecr.io/omega-nexus-frontend:latest"
```

Option B - Temporarily use public image for testing:
```bash
# To:
image = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
```

### Step 3: Verify Dependencies Are In Place (Error 2 Fix)

Check that both Container Apps have `depends_on`:

```bash
grep -A 5 "resource \"azurerm_container_app\" \"backend\"" terraform/main.tf | grep depends_on
# Should show: depends_on = [azurerm_key_vault_access_policy.nexus_kv_policy]

grep -A 5 "resource \"azurerm_container_app\" \"agent\"" terraform/main.tf | grep depends_on
# Should show: depends_on = [azurerm_key_vault_access_policy.nexus_kv_policy]
```

### Step 4: Plan and Apply

```bash
# Check what will happen
terraform plan

# You should see:
# - 0 secrets to create (they're already imported)
# - Updated Container Apps (with new depends_on)
# - No Key Vault changes

# Actually apply
terraform apply
```

### Step 5: Verify Deployment

```bash
# Check backend is running
az containerapp show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --query "properties.provisioningState"
# Expected: Succeeded

# Check agent is running
az containerapp show \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --query "properties.provisioningState"
# Expected: Succeeded

# Check frontend is running
az containerapp show \
  --name ca-omega-frontend \
  --resource-group rg-omega-nexus \
  --query "properties.provisioningState"
# Expected: Succeeded

# Check logs for errors
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --tail 20
```

---

## Troubleshooting

### Issue: "Failed to import secret" in import script

**Cause**: Secret name doesn't match exactly

**Fix**:
```bash
# List all secrets in Key Vault
az keyvault secret list \
  --vault-name "kv-omega-nexus-ecc63471" \
  --query "[].name" -o table

# Use exact names from output
terraform import azurerm_key_vault_secret.azure_storage_connection_string \
  "kv-omega-nexus-ecc63471/azure-storage-connection-string"
```

### Issue: "Unable to get value using Managed Identity" still appears after fix

**Cause**: Access policy not yet propagated or Managed Identity principal_id is wrong

**Fix**:
```bash
# Verify access policy exists
az keyvault access-policy list \
  --vault-name "kv-omega-nexus-ecc63471" \
  --query "[].objectId"

# Verify Managed Identity object ID
az identity show \
  --name "id-omega-nexus" \
  --resource-group "rg-omega-nexus" \
  --query "principalId"

# If they don't match, delete and recreate the access policy
az keyvault access-policy delete \
  --vault-name "kv-omega-nexus-ecc63471" \
  --object-id "<WRONG_ID>"

# Then run terraform apply again
```

### Issue: Container Apps still failing after fixes

**Check**: 
```bash
# View full error
az containerapp show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  -o json | jq '.properties.provisioningState'

# View provisioning errors
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --follow
```

---

## Summary of Changes

| File | Change | Status |
|------|--------|--------|
| `terraform/main.tf` | Added `depends_on` to backend Container App | ✅ Done |
| `terraform/main.tf` | Added `depends_on` to agent Container App | ✅ Done |
| `terraform/import_secrets.sh` | Created import script | ✅ Done |

**Manual Actions Required**:
1. ✅ Run `terraform import` commands (or script)
2. ⏳ Update frontend image reference
3. ⏳ Run `terraform plan`
4. ⏳ Run `terraform apply`

---

## Expected Result After Fix

```bash
# All services running
az containerapp list \
  --resource-group rg-omega-nexus \
  --query "[].{name:name, state:properties.provisioningState}"

# Expected output:
# Name                    State
# ca-omega-frontend       Succeeded
# ca-omega-backend        Succeeded
# ca-omega-agent          Succeeded

# All services can access Key Vault secrets
az containerapp show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  -o json | jq '.properties.template.containers[0].env[] | select(.name == "INTERNAL_API_KEY")'

# Expected: Shows secret is properly injected
```

---

## Next Steps

1. **Import secrets** (first priority)
2. **Fix frontend image** (choose ACR or public image)
3. **Run terraform apply**
4. **Verify all services are running**
5. **Test authentication**: Verify 401 errors are gone

**Time estimate**: 10-15 minutes
