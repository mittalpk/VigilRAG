# Full Deployment & Secret Rotation Guide

## 🚀 Full Deployment Completed

### Deployment Status
**✅ Workflow Triggered**: `workflow_dispatch` event triggered manually  
**Timestamp**: March 27, 2026  
**Branch**: main  
**Commit**: 475184e (Workflow fix)

### What's Being Deployed
- ✅ **Backend Container App** - Full rebuild with corrected Key Vault secrets
- ✅ **Agent Container App** - Full rebuild with corrected Key Vault secrets  
- ✅ **Frontend Container App** - Full rebuild
- ✅ **Terraform** - Secret reference corrections applied

### Deployment Pipeline
```
GitHub Actions Workflow (deploy.yml - workflow_dispatch)
│
├─ Stage 1: Check for file changes
│  └─ (Skipped for manual trigger - deploys everything)
│
├─ Stage 2: Build & Deploy Backend (ca-omega-backend)
│  ├─ Docker build: backend/
│  ├─ Push to ghcr.io/mittalpk/omega-nexus-backend:current-sha
│  ├─ Set secrets: internal-api-key ← internal-api-key (CORRECTED ✅)
│  ├─ Update container: new image + env vars + replicas
│  └─ ETA: ~5 minutes
│
├─ Stage 3: Build & Deploy Agent (ca-omega-agent)
│  ├─ Docker build: agent/
│  ├─ Push to ghcr.io/mittalpk/omega-nexus-agent:current-sha
│  ├─ Set secrets: internal-api-key ← internal-api-key (CORRECTED ✅)
│  ├─ Update container: new image + env vars + replicas
│  └─ ETA: ~5 minutes
│
├─ Stage 4: Build & Deploy Frontend (ca-omega-frontend)
│  ├─ Docker build: frontend/
│  ├─ Push to ghcr.io/mittalpk/omega-nexus-frontend:current-sha
│  ├─ Update container: new image + build args
│  └─ ETA: ~5 minutes
│
└─ TOTAL DEPLOYMENT TIME: ~15-20 minutes
```

### Deployment Verification
Monitor at: **https://github.com/mittalpk/OmegaNexus/actions**

Check Container App status:
```bash
# Backend
az containerapp show -n ca-omega-backend -g rg-omega-nexus --query properties.provisioningState

# Agent
az containerapp show -n ca-omega-agent -g rg-omega-nexus --query properties.provisioningState

# Frontend
az containerapp show -n ca-omega-frontend -g rg-omega-nexus --query properties.provisioningState

# Expected: "Succeeded"
```

---

## 🔐 Secret Rotation Procedures

### Understanding the Current Setup

**Key Vault Name**: `kv-omega-nexus-ecc63471`

**Current Secrets**:
```
├─ internal-api-key           = "[REDACTED_INTERNAL_KEY]"          (Inter-service auth)
├─ X-Internal-API-Key         = "[REDACTED_INTERNAL_KEY]"          (DEPRECATED - Unused)
├─ github-pat                 = "github_pat_11AL..."       (GitHub API)
├─ gemini-api-key             = "***"                      (LLM API)
├─ azure-storage-connection-string = "BlobEndpoint=..."   (Wiki storage)
├─ azurewiki-container        = "omega-wiki"              (Container name)
├─ admin-username             = "admin"                   (Admin user)
├─ admin-password             = "[REDACTED_ADMIN_PASSWORD]"               (Admin pass)
└─ (Others: internal-api-key, etc.)
```

**Managed Identity**: `id-omega-nexus` (Accesses all secrets via RBAC)

---

### Scenario 1: Rotate `internal-api-key` (Inter-Service Auth)

**When**: Quarterly or if compromised  
**Impact**: 🟡 **Medium** - Services will temporarily fail to communicate

#### Step 1: Create New Secret
```bash
NEW_KEY="NewSecureKey2026_$(openssl rand -hex 8)"
echo "$NEW_KEY"  # Save this value!

az keyvault secret set \
  --vault-name kv-omega-nexus-ecc63471 \
  --name internal-api-key \
  --value "$NEW_KEY"
```

#### Step 2: Update All Services (In Parallel)
Backend needs the new key:
```bash
# Option A: Manual update
az containerapp secret set \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --secrets \
    "internal-api-key=keyvaultref:https://kv-omega-nexus-ecc63471.vault.azure.net/secrets/internal-api-key,identityref:/subscriptions/ecc63471-f21a-46af-a01f-2db799285343/resourcegroups/rg-omega-nexus/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-omega-nexus"

# Option B: Revise container app to pick up new secret
az containerapp revision create \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --existing-container backend
```

Agent needs the new key:
```bash
az containerapp secret set \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --secrets \
    "internal-api-key=keyvaultref:https://kv-omega-nexus-ecc63471.vault.azure.net/secrets/internal-api-key,identityref:/subscriptions/ecc63471-f21a-46af-a01f-2db799285343/resourcegroups/rg-omega-nexus/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-omega-nexus"
```

#### Step 3: Verify Communication
```bash
# Check backend logs
az containerapp logs show --name ca-omega-backend --resource-group rg-omega-nexus --tail 50
# Should show: "Internal auth SUCCESS"

# Test knowledge API
curl -X POST 'https://ca-omega-backend.../api/v1/knowledge/query' \
  -H "X-Internal-API-Key: $NEW_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"test","target_systems":["confluence"]}'
# Expected: 200 OK
```

#### Step 4: Document Rotation
```bash
echo "rotated internal-api-key on $(date)" >> SECRET_ROTATION_LOG.md
```

---

### Scenario 2: Rotate `github-pat` (GitHub Personal Access Token)

**When**: Quarterly (GitHub recommends 90 days), after team member leaves, or if exposed  
**Impact**: 🔴 **High** - Code repository access will fail

#### Step 1: Generate New GitHub PAT
1. Go to: `https://github.com/settings/tokens`
2. Click "Generate new token"
3. Scopes needed:
   - `repo` (full control of private repositories)
   - `read:org` (read organization info)
4. Copy token (format: `github_pat_...`)

#### Step 2: Update Key Vault
```bash
NEW_PAT="github_pat_<your_new_token>"

az keyvault secret set \
  --vault-name kv-omega-nexus-ecc63471 \
  --name github-pat \
  --value "$NEW_PAT"
```

#### Step 3: Revise Container Apps
```bash
# Backend (needs GitHub PAT for code search)
az containerapp revision create \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --existing-container backend

# Agent (needs GitHub PAT as backup)
az containerapp revision create \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --existing-container agent
```

#### Step 4: Verify GitHub Access
```bash
# Check if backend can reach GitHub
curl -i "https://api.github.com/repos/mittalpk/repos" \
  -H "Authorization: token $(az keyvault secret show --vault-name kv-omega-nexus-ecc63471 --name github-pat --query value -o tsv)"
# Should return: 200 (not 401)
```

#### Step 5: Delete Old Token
```bash
# Go to https://github.com/settings/tokens and delete the old one
```

---

### Scenario 3: Rotate `gemini-api-key` (LLM API Key)

**When**: If API key is compromised, or per API provider requirements  
**Impact**: 🔴 **High** - All LLM calls will fail

#### Step 1: Get New API Key
- Provider: Google Cloud / Gemini API
- Process: Contact provider or regenerate in their console

#### Step 2: Update Key Vault
```bash
NEW_GEMINI_KEY="your-new-gemini-api-key"

az keyvault secret set \
  --vault-name kv-omega-nexus-ecc63471 \
  --name gemini-api-key \
  --value "$NEW_GEMINI_KEY"
```

#### Step 3: Revise Container Apps
Backend uses Gemini for LLM:
```bash
az containerapp revision create \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --existing-container backend
```

Agent uses Gemini for reasoning:
```bash
az containerapp revision create \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --existing-container agent
```

#### Step 4: Test LLM Functionality
```bash
# Check backend logs for LLM API calls
az containerapp logs show --name ca-omega-backend --resource-group rg-omega-nexus | grep -i gemini
# Should not show 401 errors
```

---

### Scenario 4: Rotate `azure-storage-connection-string` (Wiki Storage)

**When**: If storage account key is rotated, or per security policy  
**Impact**: 🟡 **Medium** - Wiki document retrieval will fail

#### Step 1: Regenerate Storage Key
```bash
STORAGE_ACCOUNT="wikistorageomega"  # Or find from connection string
RESOURCE_GROUP="rg-omega-nexus"

# Rotate primary key
az storage account keys renew \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --key primary

# Get new connection string
NEW_CONN_STR=$(az storage account show-connection-string \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query connectionString -o tsv)
```

#### Step 2: Update Key Vault
```bash
az keyvault secret set \
  --vault-name kv-omega-nexus-ecc63471 \
  --name azure-storage-connection-string \
  --value "$NEW_CONN_STR"
```

#### Step 3: Revise Container Apps
```bash
az containerapp revision create \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --existing-container backend
```

#### Step 4: Verify Storage Access
```bash
# Test Azure storage connection
az storage blob list \
  --account-name wikistorageomega \
  --container-name omega-wiki \
  --query "[].name" | head -5
# Should list blobs without auth errors
```

---

### Scenario 5: Rotate `admin-password` (Admin Account)

**When**: After onboarding/offboarding, quarterly rotation  
**Impact**: 🟢 **Low** - Only affects admin login

#### Step 1: Generate New Password
```bash
NEW_ADMIN_PASS=$(openssl rand -base64 16)
echo "New admin password: $NEW_ADMIN_PASS"  # Save temporarily!
```

#### Step 2: Update Key Vault
```bash
az keyvault secret set \
  --vault-name kv-omega-nexus-ecc63471 \
  --name admin-password \
  --value "$NEW_ADMIN_PASS"
```

#### Step 3: Revise Container Apps
```bash
# Backend uses admin credentials for auth
az containerapp revision create \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --existing-container backend
```

#### Step 4: Test Admin Login
```bash
# Try logging in with new credentials
curl -X POST 'https://ca-omega-backend.../api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"'$NEW_ADMIN_PASS'"}'
# Expected: 200 OK with JWT token
```

---

## 📋 Automated Secret Rotation (Future)

To eliminate manual rotation, implement Azure Key Vault secret rotation:

```bash
# Enable automatic rotation
az keyvault secret set \
  --vault-name kv-omega-nexus-ecc63471 \
  --name internal-api-key \
  --value "..."  \
  --expires 7776000  # 90 days in seconds

# Add Event Grid trigger for Container App revision
az eventgrid event-subscription create \
  --name kv-secret-rotated \
  --source-resource-id /subscriptions/.../kv-omega-nexus-ecc63471 \
  --endpoint-type webhook \
  --endpoint "https://ca-omega-backend.../webhooks/secret-rotated"
```

---

## 🔒 Secret Rotation Best Practices

| Practice | Details |
|----------|---------|
| **Frequency** | Every 90 days minimum + immediate if compromised |
| **Planning** | Schedule during low-traffic windows (off-peak hours) |
| **Testing** | Always test in dev environment first |
| **Verification** | Verify services work with new secrets |
| **Audit Trail** | Log all rotations for compliance |
| **Cleanup** | Delete old secrets after verification period |
| **Backup** | Store previous secret for quick rollback (24 hours) |
| **Monitoring** | Alert on failed auth attempts after rotation |

---

## 🚨 Emergency Rollback

If a rotation causes outages:

```bash
# Quickly rollback to previous secret
PREVIOUS_SECRET="<save this before rotation>"

az keyvault secret set \
  --vault-name kv-omega-nexus-ecc63471 \
  --name internal-api-key \
  --value "$PREVIOUS_SECRET"

# Force container apps to pick up old secret immediately
az containerapp revision create \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --existing-container backend

az containerapp revision create \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --existing-container agent
```

---

## ✅ Post-Deployment Checklist

- [ ] Wait 15-20 minutes for all deployments to complete
- [ ] Check https://github.com/mittalpk/OmegaNexus/actions for successful build
- [ ] Verify all 3 Container Apps show "Succeeded" status
- [ ] Test MultiAgent query execution (no 401 errors expected)
- [ ] Check backend logs show "Internal auth SUCCESS"
- [ ] Verify frontend can communicate with backend
- [ ] Monitor error logs for any authentication issues
- [ ] Document deployment completion with timestamp

---

## 📞 Support

For secret rotation issues:
1. Check Azure Key Vault Access Policies (need Managed Identity permissions)
2. Verify Container App has latest revision with updated secrets
3. Check Container App logs: `az containerapp logs show ...`
4. Test connectivity to each API independently
5. Review GitHub Actions workflow for deployment errors

**Deployment Monitoring**: https://github.com/mittalpk/OmegaNexus/actions/workflows/deploy.yml
