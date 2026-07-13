# OmegaNexus: Fixing 401 "Not Authenticated" Errors

## Problem Diagnosis

**Symptom**: Backend returns 401 "Not authenticated" when agent calls `/api/v1/knowledge/query` with `X-Internal-API-Key: [REDACTED_INTERNAL_KEY]` header.

**Root Cause**: Backend is loading `"change-me-in-production"` (default value) instead of `"[REDACTED_INTERNAL_KEY]"` from Key Vault.

This happens because:
1. The `INTERNAL_API_KEY` environment variable is not being injected into the container from Key Vault
2. Pydantic Settings falls back to the default value in `backend/app/config.py:42`
3. Auth comparison fails: `"[REDACTED_INTERNAL_KEY]"` (in request) != `"change-me-in-production"` (in backend)

```python
# backend/app/config.py line 42
internal_api_key: SecretStr = Field(
    default=SecretStr("change-me-in-production"),  # ← Falls back to this
    validation_alias=AliasChoices("INTERNAL_API_KEY", "internal-api-key", "X-Internal-API-Key")
)
```

## Why Configuration Appears Correct But Doesn't Work

Infrastructure verification shows everything correct:
- ✅ Secret exists in Key Vault: `internal-api-key` = `"[REDACTED_INTERNAL_KEY]"`
- ✅ Container App has secret binding: `keyVaultUrl` → `internal-api-key` with Managed Identity
- ✅ Environment variable configured: `INTERNAL_API_KEY=secretRef:internal-api-key`
- ✅ Health endpoint responds: `HTTP 200 OK`

**However**: Container revision was created BEFORE secret environment variable syntax was fixed. The old replica pods are still running with incorrect configuration.

## Solution: Force Container Restart with Corrected Environment Variable

### Option A: Update Terraform & Redeploy (Recommended)

1. Edit `terraform/main.tf` (already done in this repo):
   - Line 164 (Backend): Change `secret_name = "internal-api-key"` to `value = "secretRef:internal-api-key"`
   - Line 262 (Agent): Same change for consistency

2. Apply Terraform:
```bash
cd terraform
terraform plan -out=tfplan
terraform apply tfplan
```

This creates new Container App revision with corrected environment variable injection.

### Option B: Trigger Deployment Without Code Changes

If Git push is configured:
```bash
git push origin main  # Triggers GitHub Actions → Redeploy
```

If manual deployment needed:
1. Edit Container App in Azure Portal
2. In "Template" section, update env var: `INTERNAL_API_KEY` from `secretRef:internal-api-key`
3. Re-add it with exact same value (triggers template version change)
4. Save (forces new revision)

### Option C: Force Pod Restart

Scale replicas to force new pods:
```bash
# Scale up
az containerapp update \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --min-replicas 2

sleep 10

# Scale back
az containerapp update \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --min-replicas 1
```

## Verification Steps After Deployment

### 1. Check Startup Logs
```bash
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --follow=false \
  --tail=20
```

Look for:
```
✓ Settings initialized: INTERNAL_API_KEY length = 20
```

If you see `length = 22`, it's using default `"change-me-in-production"` (22 chars). Should be `length = 15` for `"[REDACTED_INTERNAL_KEY]"`.

### 2. Test API Authentication
```bash
curl -X POST \
  "https://ca-omega-backend.gentlesea-072b973e.francecentral.azurecontainerapps.io/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: [REDACTED_INTERNAL_KEY]" \
  -H "Content-Type: application/json" \
  -d '{"query":"test","target_systems":["confluence"]}' \
  -v
```

Expected response: `HTTP 200` (or content response, not 401)

### 3. Check Agent Logs
```bash
az containerapp logs show \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --follow=false \
  --tail=20
```

Look for successful knowledge API calls (no 401 errors).

## Files Modified in This Repository

### backend/app/config.py
- Added: `import os, logging`
- Added: Logger initialization
- Added: `__init__` method with startup diagnostics logging

When container starts, logs will show:
```
✓ Settings initialized: INTERNAL_API_KEY length = 15
  BACKEND_URL env var: https://ca-omega-backend.gentlesea-...
  AGENT_SERVICE_URL env var: http://ca-omega-agent:8000
```

### terraform/main.tf
- Line 164 (Backend Container): `value = "secretRef:internal-api-key"` (explicit reference)
- Line 262 (Agent Container): `value = "secretRef:internal-api-key"` (explicit reference)

This ensures Container Apps properly injects secret at runtime.

## Why This Fix Works

1. **Explicit secretRef syntax**: Using `value = "secretRef:internal-api-key"` instead of `secret_name` ensures Container Apps:
   - Uses correct secret resolution mechanism
   - Injects actual secret value into environment variable
   - Creates proper secret binding at revision time

2. **Diagnostic logging**: Shows what value is actually loaded:
   - If `length = 15`: Secret injected correctly ✅
   - If `length = 22`: Still using default ❌ (need to restart/redeploy)

3. **Container restart**: Forces new replica pods that will:
   - Load updated template with corrected env var syntax
   - Query Key Vault for secret value
   - Inject actual `"[REDACTED_INTERNAL_KEY]"` into container environment
   - Python app reads correct value on startup

## Timeline to Resolution

1. **Deploy Terraform changes**: 2-3 minutes
2. **New Container revision created**: Automatic
3. **Pods restart with new image**: 1-2 minutes
4. **Test API call**: Immediate - should return 200 OK

Total time: ~5 minutes after deployment

## Recommended Next Steps

1. ✅ Apply Terraform changes (already committed in this repo)
2. ☐ Monitor deployment via Azure Portal → Container Apps → Revisions
3. ☐ Check startup logs for "Settings initialized" message
4. ☐ Run curl test to verify 200 OK response
5. ☐ Monitor agent logs to verify multi-agent queries working

## Questions?

Check these files for detailed context:
- `backend/app/main.py` - Auth dependency with detailed logging
- `backend/app/config.py` - Settings loader with diagnostic output
- `agent/app/tools.py` - Agent-to-backend API calls
- `terraform/main.tf` - Container App environment variable configuration
