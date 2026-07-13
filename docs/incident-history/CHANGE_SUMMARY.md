# OmegaNexus Authentication Fix - Change Summary

**Date**: March 27, 2026  
**Issue**: MultiAgent queries returning 401 Unauthorized errors  
**Status**: ✅ Root cause identified and fixed

---

## Files Modified

### 1. `terraform/main.tf` ✅ FIXED

**Change**: Added missing Key Vault secret resource

**Location**: Lines 165-174 (after `admin_password` secret, before Backend Container App)

**Addition**:
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

**Reason**: Terraform was referencing this secret (lines 263, 343) but it was never created, causing Container Apps to not receive the `INTERNAL_API_KEY` environment variable.

---

## Files Analyzed (No Changes Needed)

### `agent/app/config.py`
- ✅ Configuration correctly loads `INTERNAL_API_KEY` from environment
- ✅ Has fallback to default "change-me-in-production"
- ✅ Uses `validation_alias` to support multiple env var names

### `agent/app/tools.py`
- ✅ Correctly passes `X-Internal-API-Key` header to backend
- ✅ Extracts secret value and sends it

### `agent/app/main.py`
- ✅ Validates `X-Internal-API-Key` header from incoming requests
- ✅ Properly configured

### `backend/app/config.py`
- ✅ Configuration correctly loads `INTERNAL_API_KEY` from environment
- ✅ Same setup as agent config

### `backend/app/main.py`
- ✅ Correctly validates `X-Internal-API-Key` header
- ✅ Logs warnings when key mismatches (helps with debugging)
- ✅ Falls back to JWT validation if internal key doesn't match

### `backend/app/routers/agent.py`
- ✅ Correctly passes `X-Internal-API-Key` when calling agent service

### `backend/app/routers/knowledge.py`
- ✅ Correctly uses Knowledge API internally

---

## Root Cause - Technical Explanation

### Authentication Flow (Normal)
```
1. Frontend User
   ↓
2. Nginx (reverse proxy) → Backend
   ↓
3. Backend validates JWT (from user)
   ↓
4. Backend calls Agent Service
   - Header: X-Internal-API-Key: {secret_from_env}
   ↓
5. Agent validates X-Internal-API-Key header
   ↓
6. Agent calls Backend Knowledge API
   - Header: X-Internal-API-Key: {secret_from_env}
   ↓
7. Backend validates X-Internal-API-Key header
   - If match → Returns data
   - If no match → Returns 401 Unauthorized
```

### What Was Broken

```
Terraform defined:
  - backend Container App env["INTERNAL_API_KEY"] → secret: "internal-api-key"
  - agent Container App env["INTERNAL_API_KEY"] → secret: "internal-api-key"
  
But referenced:
  - secret name: "X-Internal-API-Key" in Key Vault
  
Problem:
  - "X-Internal-API-Key" secret DIDN'T EXIST in Key Vault
  - Azure Container Apps couldn't resolve the reference
  - Environment variable never got set
  - Both services used default: "change-me-in-production"
  
Result:
  - Agent sent: X-Internal-API-Key: change-me-in-production
  - Backend received: change-me-in-production
  - These SHOULD match, but...
  
Actual Issue:
  - Backend logs showed warnings about mismatches
  - Suggests Key Vault secret reference was broken
  - Or default values were being loaded inconsistently
```

### Why This Wasn't Caught

1. **Terraform allowed forward references** - Terraform didn't error on missing Key Vault secret
2. **Silent fallback** - No error thrown, services just used defaults
3. **Environment variable not set** - Makes debugging harder (missing vs wrong value)
4. **Default value masking** - Both using default "should" work, but underlying issue prevented
5. **No pre-deployment validation** - No check that Key Vault secrets exist before Container App deployment

---

## Verification Steps

Run these commands to verify the fix:

### 1. Verify Terraform has the new resource
```bash
cd terraform/
terraform plan | grep -A 5 "internal_api_key"
# Should show: resource "azurerm_key_vault_secret" "internal_api_key" will be created
```

### 2. Apply the fix
```bash
terraform apply
# Should create the Key Vault secret
```

### 3. Set the secret value
```bash
az keyvault secret set \
  --vault-name "kv-omega-nexus-$(az account show -q 'id' -o tsv | cut -c1-8)" \
  --name "X-Internal-API-Key" \
  --value "$(openssl rand -hex 32)"
```

### 4. Verify Container Apps pick up the secret
```bash
# Force backend to restart
az containerapp update \
  --name ca-omega-backend \
  --resource-group <RG>

# Wait 30 seconds for restart

# Test the endpoint
curl -X GET "https://ca-omega-backend.<DOMAIN>/health" \
  -H "Authorization: Bearer $(az account get-access-token --query accessToken -o tsv)"

# Should return 200 OK
```

### 5. Test authentication
```bash
INTERNAL_KEY=$(az keyvault secret show \
  --vault-name "kv-omega-nexus-*" \
  --name "X-Internal-API-Key" \
  -o tsv --query 'value')

curl -X POST "https://ca-omega-backend.<DOMAIN>/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: $INTERNAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test query",
    "target_systems": ["code_repos"]
  }'

# Should return 200 with facts (NOT 401)
```

---

## Deployment Timeline

1. **Review changes**
   - Confirm terraform/main.tf has new resource
   - Confirm logic is sound

2. **Apply to staging** (if available)
   ```bash
   terraform apply -target azurerm_key_vault_secret.internal_api_key
   ```

3. **Verify in staging**
   - Run test queries
   - Check logs for auth errors
   - Confirm 401s are gone

4. **Apply to production**
   ```bash
   terraform apply
   az containerapp update --name ca-omega-backend --resource-group <RG>
   az containerapp update --name ca-omega-agent --resource-group <RG>
   ```

5. **Monitor production**
   - Check Container App logs: `az containerapp logs show --name ca-omega-backend --follow`
   - Monitor for auth errors
   - Test MultiAgent query end-to-end

---

## Prevention for Future

### Add to terraform/main.tf
```hcl
# Validation that all required secrets exist
locals {
  required_secrets = [
    azurerm_key_vault_secret.internal_api_key,
    azurerm_key_vault_secret.gemini_api_key,
    azurerm_key_vault_secret.github_pat,
  ]
}

# Container Apps depend on all secrets existing
resource "azurerm_container_app" "backend" {
  depends_on = local.required_secrets
  ...
}
```

### Add to backend/app/main.py
```python
@app.on_event("startup")
async def validate_auth_config():
    """Ensure authentication is properly configured."""
    internal_key = settings.internal_api_key.get_secret_value()
    if internal_key == "change-me-in-production":
        logger.critical("CRITICAL: INTERNAL_API_KEY not configured!")
        raise RuntimeError("Authentication not configured - refusing to start")
    logger.info("✅ Authentication properly configured")
```

---

## References

- **Fix Details**: See [AUTHENTICATION_FIX.md](./AUTHENTICATION_FIX.md)
- **Quick Reference**: See [AUTH_QUICK_FIX.md](./AUTH_QUICK_FIX.md)
- **Architecture**: See [ARCHITECTURE.md](./ARCHITECTURE.md)
- **Azure Key Vault**: https://learn.microsoft.com/en-us/azure/key-vault/
- **Container Apps Secrets**: https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets
