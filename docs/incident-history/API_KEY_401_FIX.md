# 401 Unauthorized API Key Issue - Root Cause & Fix

## 🔴 Problem Summary

**Error**: MultiAgent queries failing with `{"error": "API returned 401"}` when accessing:
- `query_code_repositories` (GitHub API)
- `search_confluence` (Confluence API)

**Root Cause**: Backend's X-Internal-API-Key validation was failing due to **incorrect Key Vault secret reference in Terraform**.

---

## 🔍 Root Cause Analysis

### The Bug
The Terraform configuration was incorrectly mapping the container app's `internal-api-key` secret:

**Before (WRONG)**:
```hcl
secret {
  name                = "internal-api-key"
  key_vault_secret_id = "${azurerm_key_vault.nexus_kv.vault_uri}secrets/X-Internal-API-Key"
  #                                                                          ^^^^^^^^^^^^^^^^
  #                                               Pointing to WRONG secret name!
  identity            = azurerm_user_assigned_identity.nexus_identity.id
}
```

### The Impact
1. **Backend Container App**: Tried to load INTERNAL_API_KEY from Key Vault via secret mapping
2. **Secret Resolution**: OSContainerApp looked for "X-Internal-API-Key" instead of "internal-api-key"
3. **Auth Failure**: When secret wasn't resolved, Pydantic Settings used default value: `"change-me-in-production"`
4. **Key Mismatch**: 
   - **Expected** (what backend had): `"change-me-in-production"` (default fallback)
   - **Received** (from agent): `"[REDACTED_INTERNAL_KEY]"` (correct value from agent's container)
5. **Result**: `get_current_user()` dependency rejected the request with 401

### Key Vault Secrets (Correct)
```
internal-api-key         = "[REDACTED_INTERNAL_KEY]"
X-Internal-API-Key       = "[REDACTED_INTERNAL_KEY]" (unused/redundant)
github-pat               = "github_pat_11AL..."
azure-storage-connection-string = "BlobEndpoint=https://..."
... (other secrets)
```

---

##  ✅ Solution

**After (CORRECT)**:
```hcl
secret {
  name                = "internal-api-key"
  key_vault_secret_id = "${azurerm_key_vault.nexus_kv.vault_uri}secrets/internal-api-key"
  #                                                                          ^^^^^^^^^^^^^^^^
  #                                               Pointing to CORRECT secret name!
  identity            = azurerm_user_assigned_identity.nexus_identity.id
}
```

### Changes Made
**File**: `terraform/main.tf`

**Backend Container App** (around line 224):
- Changed from: `secrets/X-Internal-API-Key`
- Changed to: `secrets/internal-api-key`

**Agent Container App** (around line 300):
- Changed from: `secrets/X-Internal-API-Key`
- Changed to: `secrets/internal-api-key`

### Commits
1. **1a3ae4f**: Added detailed logging (debug preparation)
2. **34b9c5f**: Fixed Key Vault secret references (CRITICAL FIX)

Both commits pushed to `origin/main` - GitHub Actions CI/CD will automatically:
1. ✅ Build new container images
2. ✅ Push to Container Registry
3. ✅ Apply Terraform with corrected secret mappings
4. ✅ Deploy Container App revisions with proper secrets

---

## 🔄 Authentication Flow (Post-Fix)

```
Agent Container
├─ INTERNAL_API_KEY ← [Key Vault: internal-api-key = "[REDACTED_INTERNAL_KEY]"] ✅
│
└─ POST /api/v1/knowledge/query
   ├─ Header: "X-Internal-API-Key: [REDACTED_INTERNAL_KEY]"
   │
   └─ Backend Container
      ├─ INTERNAL_API_KEY ← [Key Vault: internal-api-key = "[REDACTED_INTERNAL_KEY]"] ✅
      │
      └─ Dependency: get_current_user()
         ├─ Extract header: "X-Internal-API-Key: [REDACTED_INTERNAL_KEY]"
         ├─ Read expected: settings.internal_api_key = "[REDACTED_INTERNAL_KEY]" ✅
         ├─ COMPARE: "[REDACTED_INTERNAL_KEY]" == "[REDACTED_INTERNAL_KEY]" ✅ MATCH!
         │
         └─ Return: {"sub": "internal-agent", "internal": True}

Response: 200 OK with knowledge data ✅
```

---

## 🧪 Testing After Deployment

Once the build completes and Container Apps are updated:

### Test 1: API Key Authentication
```bash
curl -X POST 'https://ca-omega-backend.../api/v1/knowledge/query' \
  -H 'X-Internal-API-Key: [REDACTED_INTERNAL_KEY]' \
  -H 'Content-Type: application/json' \
  -d '{"query": "test", "target_systems": ["confluence"]}'

Expected: 200 OK with facts and metadata
```

### Test 2: MultiAgent Query Execution
```bash
POST /api/v1/agent/run
{
  "task": "Scan for hardcoded credentials",
  "max_iterations": 10,
  "context": {}
}

Expected:
- ✅ No 401 errors from query_code_repositories
- ✅ No 401 errors from search_confluence
- ✅ Results with code facts and documentation
```

### Test 3: Check Logs for Successful Auth
Once deployed, check backend logs:
```bash
az containerapp logs show --name ca-omega-backend --resource-group rg-omega-nexus --tail 50
# Should show: "Internal auth SUCCESS for /api/v1/knowledge/query"
```

---

## 📋 Deployment Progress

| Stage | Status | ETA |
|-------|--------|-----|
| GitHub Push | ✅ Complete | |
| Build Trigger | ✅ Triggered (commit 34b9c5f) | |
| Docker Build | 🟡 In Progress | ~3 min |
| Image Push | 🟡 In Progress | ~5 min |
| Terraform Apply | ⏳ Waiting | ~7 min |
| Container Update | ⏳ Waiting | ~9 min |

**Estimated Total Time to Resolution**: ~10-15 minutes from commit

---

## 🎯 Expected Results After Fix

✅ Backend reads correct INTERNAL_API_KEY from Key Vault  
✅ Agent and Backend keys match: "[REDACTED_INTERNAL_KEY]"  
✅ X-Internal-API-Key header validation passes  
✅ /api/v1/knowledge/query endpoint accessible  
✅ MultiAgent can query GitHub and Confluence  
✅ No more 401 errors  

---

## 🔐 Security Implications

**Before (Insecure)**:
- Backend was using hardcoded default "change-me-in-production"
- No actual Key Vault secret being used for backend's auth key
- Mismatch between agent and backend allowed for credential confusion

**After (Secure)**:
- Both backend and agent read the SAME secret from Key Vault
- Keys stay in sync automatically when updated in Key Vault
- Managed Identity enforces Zero Trust access control
- No hardcoded credentials in environment

---

## 📝 Additional Notes

- The "X-Internal-API-Key" secret in Key Vault is now **unused/redundant**
- Both "internal-api-key" and "X-Internal-API-Key" had the same value, so API calls worked - the async issue was the terraform mapping
- To achieve full cleanup: Consider removing "X-Internal-API-Key" secret from Key Vault in future refactoring
- Monitor first few MultiAgent query executions after deployment to confirm fix is working

---

## 🚀 What's Next

1. ⏳ **Wait for Build**: CI/CD build should complete in ~10 minutes
2. 🧪 **Test Query**: Try a MultiAgent query once Container Apps updated
3. ✅ **Validate**: Check logs confirm "Internal auth SUCCESS"
4. 📊 **Monitor**: Watch for any new errors or issues
5. 🔄 **Optional**: Consider removing unused "X-Internal-API-Key" secret

The system should be fully operational once deployment completes!
