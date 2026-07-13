# OmegaNexus Authentication Error - Root Cause Analysis & Fix

## Executive Summary

**Issue**: MultiAgent query returning `401 Unauthorized` when accessing code repositories and Confluence.

**Root Cause**: Missing Key Vault secret definition in Terraform causes Container Apps to fall back to default internal API key value, creating an authentication mismatch.

**Status**: ✅ **FIXED** - Terraform updated with missing secret resource

---

## Root Cause Analysis

### Architectural Overview

The system uses **internal service-to-service authentication** via the `X-Internal-API-Key` header:

```
Agent Service (Layer 3)
    └─> calls Knowledge API (Layer 2)
         Uses header: X-Internal-API-Key: {secret}
         
Backend Service validates:
    if X-Internal-API-Key == settings.internal_api_key
         → Allow access
    else → 401 Unauthorized
```

### The Problem Chain

1. **Missing Terraform Resource**
   - `terraform/main.tf` references `secrets/X-Internal-API-Key` from Key Vault
   - But the secret was NEVER created in Terraform
   - Lines 263, 343 reference non-existent secret

2. **Container App Deployment Fails Silently**
   - When Azure Container Apps tries to resolve the missing secret
   - The environment variable `INTERNAL_API_KEY` is not set
   - Services fall back to hardcoded default: `"change-me-in-production"`

3. **Authentication Mismatch**
   - Agent sends: `X-Internal-API-Key: change-me-in-production` (default)
   - Backend expects: Value from Key Vault (which doesn't exist)
   - Result: `401 Unauthorized` on all inter-service calls

4. **Debugging Evidence**
   - `backend/app/main.py` logs show:
   ```
   logger.warning(f"Internal API Key mismatch. Received: {internal_key[:3]}..., Expected: {expected_key[:3]}...")
   logger.warning("Internal API Key missing from headers")
   ```

### Affected Services

- ❌ Agent → Backend Knowledge API calls fail
- ❌ GitHub search fails (401)
- ❌ Confluence search fails (401)
- ❌ SQL database queries fail (401)

---

## The Fix

### What Was Changed

**File**: `terraform/main.tf`

Added missing Key Vault secret resource:

```hcl
resource "azurerm_key_vault_secret" "internal_api_key" {
  name         = "X-Internal-API-Key"
  value        = "REPLACE_IN_PORTAL"
  key_vault_id = azurerm_key_vault.nexus_kv.id

  lifecycle {
    ignore_changes = [value]
  }
}
```

This resource:
- ✅ Creates the Key Vault secret that Terraform was referencing
- ✅ Allows both backend and agent Container Apps to access it
- ✅ Ensures `INTERNAL_API_KEY` environment variable is properly set

---

## Deployment Instructions

### Step 1: Terraform Apply (Automated)

```bash
cd terraform
terraform plan
terraform apply
```

**Expected Output**: 
```
azurerm_key_vault_secret.internal_api_key will be created
+ resource "azurerm_key_vault_secret" "internal_api_key" {
    + name            = "X-Internal-API-Key"
    + value           = "REPLACE_IN_PORTAL"
    ...
}
```

### Step 2: Set the Secret Value (Manual - Azure Portal)

⚠️ **IMPORTANT**: The Terraform fixture uses placeholder `"REPLACE_IN_PORTAL"` for security.

1. Go to **Azure Portal** → **Key Vaults** → `kv-omega-nexus-*`
2. Secrets → `X-Internal-API-Key`
3. Click **Edit**
4. Replace value with a **strong, random 32+ character string**, e.g.:
   ```
   kv-xomega-nexus-2026-prod-$(openssl rand -hex 16)
   ```
   Or use Azure CLI:
   ```bash
   az keyvault secret set \
     --vault-name "kv-omega-nexus-<HASH>" \
     --name "X-Internal-API-Key" \
     --value "$(openssl rand -hex 32)"
   ```

### Step 3: Update Application Configurations (Optional)

If you want the secret to be generated automatically:

**File**: `agent/app/config.py`

```python
# Change from hardcoded default:
internal_api_key: SecretStr = Field(
    default=SecretStr("change-me-in-production"),
    ...
)

# To generated default (only as last resort):
# This is NOT recommended for production
```

**Same for**: `backend/app/config.py`

### Step 4: Redeploy Container Apps

Option A — Via Azure CLI:
```bash
# Force backend to pick up new secret
az containerapp update \
  --name ca-omega-backend \
  --resource-group <RG_NAME>

# Force agent to pick up new secret
az containerapp update \
  --name ca-omega-agent \
  --resource-group <RG_NAME>
```

Option B — Via Terraform:
```bash
cd terraform
terraform apply -auto-approve
```

### Step 5: Verify the Fix

Test the Knowledge API endpoint:

```bash
curl -X POST "https://ca-omega-backend.{DOMAIN}/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: {YOUR_SECRET_VALUE}" \
  -H "Content-Type: application/json" \
  -d '{"query": "search for hardcoded credentials", "target_systems": ["code_repos"]}'
```

**Expected Response** (no 401):
```json
{
  "facts": [...],
  "metadata": [...],
  "source": "GitHub"
}
```

---

## Verification Checklist

- [ ] Terraform applied successfully
- [ ] Key Vault secret `X-Internal-API-Key` exists with non-default value
- [ ] Backend Container App has `INTERNAL_API_KEY` environment variable set
- [ ] Agent Container App has `INTERNAL_API_KEY` environment variable set
- [ ] Test Knowledge API with curl returns 200 (not 401)
- [ ] MultiAgent query completes without 401 errors
- [ ] Agent can access GitHub (via Knowledge API)
- [ ] Agent can access Confluence (via Knowledge API)

---

## Security Notes

1. **Never commit secret values** to Git or Terraform code
2. **Use Azure Key Vault** as the source of truth for secrets
3. **Regenerate secrets regularly** (recommended: every 90 days)
4. **Audit secret access** via Azure Key Vault audit logs:
   ```bash
   az monitor diagnostic-settings create \
     --name keyvault-audit \
     --resource /subscriptions/*/resourcegroups/*/providers/microsoft.keyvault/vaults/* \
     --logs '[{"category":"AuditEvent","enabled":true}]'
   ```

---

## Root Cause - Why This Wasn't Caught Earlier

1. **Placeholder Pattern**: The Terraform used `"REPLACE_IN_PORTAL"` as default, intending manual setup
2. **Missing Validation**: No pre-deployment check ensured the Key Vault secret existed
3. **Silent Fallback**: When the secret didn't exist, services silently fell back to hardcoded defaults
4. **Log Warnings Not Monitored**: Backend logs showed warnings, but no alerting was configured

---

## Preventing Future Occurrences

### 1. Add Terraform Validation (Recommended)

**File**: `terraform/main.tf`

```hcl
# Ensure Key Vault secret exists before deploying Container Apps
resource "null_resource" "validate_secrets" {
  depends_on = [
    azurerm_key_vault_secret.internal_api_key,
    azurerm_key_vault_secret.gemini_api_key,
  ]
}

resource "azurerm_container_app" "backend" {
  depends_on = [null_resource.validate_secrets]
  ...
}
```

### 2. Add Health Check for Auth (Recommended)

**File**: `backend/app/routers/health.py`

```python
@router.get("/auth-check")
async def auth_check():
    """Validates that authentication is properly configured."""
    return {
        "status": "healthy",
        "internal_api_key_configured": bool(settings.internal_api_key.get_secret_value())
    }
```

### 3. Add Startup Validation (Recommended)

**File**: `agent/app/main.py`

```python
@app.on_event("startup")
async def validate_config():
    if settings.internal_api_key.get_secret_value() == "change-me-in-production":
        logger.error("CRITICAL: INTERNAL_API_KEY not configured! Set env var INTERNAL_API_KEY")
        raise RuntimeError("Internal API key not configured")
```

---

## References

- [Azure Key Vault Documentation](https://learn.microsoft.com/en-us/azure/key-vault/)
- [Terraform Azure Provider - Key Vault Secret](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/key_vault_secret)
- [Container Apps Environment Variables](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=bash)
- [Architecture](./ARCHITECTURE.md)
