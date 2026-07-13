# OmegaNexus Authentication Fix - Quick Reference & Runbook

## 🔴 Problem
```
MultiAgent Query Error:
"Access to both the code repositories and Confluence was denied (API returned 401 Unauthorized)"
```

## 🟢 Fix Status
**✅ COMPLETED** - Terraform updated to include missing Key Vault secret resource

---

## ⚡ Quick Action Items (In Order)

### 1️⃣ Apply Terraform Changes
```bash
cd terraform/
terraform init
terraform plan
terraform apply
```
**Expected**: `azurerm_key_vault_secret.internal_api_key` resource created

---

### 2️⃣ Set Secret Value in Azure Key Vault

**Option A - Azure CLI:**
```bash
# Generate a secure random key
SECRET_VALUE=$(openssl rand -hex 32)

# Set it in Key Vault
az keyvault secret set \
  --vault-name "kv-omega-nexus-$(az account show --query 'id' -o tsv | cut -c1-8)" \
  --name "X-Internal-API-Key" \
  --value "$SECRET_VALUE"

# Verify it was set
az keyvault secret show \
  --vault-name "kv-omega-nexus-$(az account show --query 'id' -o tsv | cut -c1-8)" \
  --name "X-Internal-API-Key"
```

**Option B - Azure Portal:**
1. Open Azure Portal → Key Vaults
2. Find: `kv-omega-nexus-*`
3. Secrets → `X-Internal-API-Key`
4. Click Edit → Paste secure value → Save

---

### 3️⃣ Redeploy Services

**Option A - Force Container App Update:**
```bash
RESOURCE_GROUP="<YOUR_RG_NAME>"

# Redeploy backend
az containerapp update \
  --name ca-omega-backend \
  --resource-group "$RESOURCE_GROUP"

# Redeploy agent  
az containerapp update \
  --name ca-omega-agent \
  --resource-group "$RESOURCE_GROUP"

# Monitor deployment
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group "$RESOURCE_GROUP" \
  --follow
```

**Option B - Via Terraform:**
```bash
terraform apply -auto-approve
# Then redeploy revisions via portal or CLI
```

---

### 4️⃣ Verify the Fix

```bash
# 1. Check environment variables are set
BACKEND_URL="https://ca-omega-backend.<DOMAIN>"

# 2. Test the Knowledge API
curl -X POST "$BACKEND_URL/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: $(az keyvault secret show --vault-name kv-omega-nexus-* --name X-Internal-API-Key -o tsv --query value)" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "find authentication issues",
    "target_systems": ["code_repos"]
  }'

# 3. Expected: HTTP 200 with facts (NOT 401)

# 4. Check logs for auth errors
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group "$RESOURCE_GROUP" \
  --tail 50 | grep -i "api key\|unauthorized"
```

---

## 📋 Verification Checklist

- [ ] Terraform plan shows `azurerm_key_vault_secret.internal_api_key` resource
- [ ] `terraform apply` completes successfully
- [ ] Key Vault secret `X-Internal-API-Key` has non-default value
- [ ] Container Apps redeployed
- [ ] Knowledge API returns 200 (not 401) with sample query
- [ ] Backend logs show NO "API Key mismatch" warnings
- [ ] Agent logs show NO "401 Unauthorized" errors
- [ ] MultiAgent query completes successfully
- [ ] Can search code repositories
- [ ] Can search Confluence

---

## 🔧 Troubleshooting

### Still Getting 401 After Fix?

```bash
# 1. Check Backend Config
az containerapp show \
  --name ca-omega-backend \
  --resource-group "$RESOURCE_GROUP" \
  -o json | jq '.properties.template.containers[0].env[] | select(.name == "INTERNAL_API_KEY")'

# Expected output should show the secret reference

# 2. Check Agent Config
az containerapp show \
  --name ca-omega-agent \
  --resource-group "$RESOURCE_GROUP" \
  -o json | jq '.properties.template.containers[0].env[] | select(.name == "INTERNAL_API_KEY")'

# 3. Verify Key Vault Secret Exists
az keyvault secret list \
  --vault-name "kv-omega-nexus-*" \
  --query "[?name=='X-Internal-API-Key']"

# 4. Check Managed Identity has access
az roleassignment list \
  --scope "/subscriptions/*/resourceGroups/*/providers/Microsoft.KeyVault/vaults/kv-omega-nexus-*" \
  --query "[].principalName" -o table
```

### Key Vault Secret Not Found?

```bash
# If Terraform apply failed:
terraform plan 2>&1 | head -30

# If Key Vault doesn't exist:
az keyvault list --query "[?name | contains('omega')]"

# Manually create secret:
az keyvault secret set \
  --vault-name "kv-omega-nexus-<HASH>" \
  --name "X-Internal-API-Key" \
  --value "<SECURE_VALUE>"
```

---

## 📊 What Changed (Technical Details)

### Files Modified

**terraform/main.tf** - Added missing resource:
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

### Why This Fixes It

| Before | After |
|--------|-------|
| Key Vault secret doesn't exist | Secret exists with secure value |
| Container Apps env var not set | Env var properly injected |
| Both services use default "change-me-in-production" | Both use actual secret value |
| Agent → Backend: 401 Unauthorized | Agent → Backend: 200 OK ✅ |

---

## 🔐 Security Best Practices

After deploying this fix:

1. **Rotate secrets regularly**
   ```bash
   # Every 90 days:
   NEW_SECRET=$(openssl rand -hex 32)
   az keyvault secret set \
     --vault-name "kv-omega-nexus-*" \
     --name "X-Internal-API-Key" \
     --value "$NEW_SECRET"
   # Redeploy apps with new secret
   ```

2. **Monitor secret access**
   ```bash
   # Enable audit logging
   az monitor diagnostic-settings create \
     --name "keyvault-audit" \
     --resource "/subscriptions/*/resourcegroups/*/providers/Microsoft.KeyVault/vaults/kv-omega-nexus-*" \
     --logs '[{"category":"AuditEvent","enabled":true}]'
   ```

3. **Alert on auth failures**
   - Set up Azure Monitor alert for 401 errors
   - Track "Internal API Key mismatch" log entries
   - Alert when secret fails to load

---

## 🧪 Test Commands

**Full Integration Test:**
```bash
# 1. Query code repositories
curl -X POST "https://ca-omega-backend.<DOMAIN>/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: $(SECRET)" \
  -H "Content-Type: application/json" \
  -d '{"query":"search for sensitive data patterns","target_systems":["code_repos"]}'

# 2. Query Confluence  
curl -X POST "https://ca-omega-backend.<DOMAIN>/api/v1/knowledge/query" \
  -H "X-Internal-API-Key: $(SECRET)" \
  -H "Content-Type: application/json" \
  -d '{"query":"policy documentation","target_systems":["confluence"]}'

# 3. Run MultiAgent Query
curl -X POST "https://ca-omega-agent.<DOMAIN>/run" \
  -H "X-Internal-API-Key: $(SECRET)" \
  -H "Content-Type: application/json" \
  -d '{"task":"analyze codebase for hardcoded credentials","max_iterations":5}'
```

---

## 📞 Support

For further issues:
- Check [AUTHENTICATION_FIX.md](./AUTHENTICATION_FIX.md) for detailed analysis
- Review [ARCHITECTURE.md](./ARCHITECTURE.md) for system design
- Enable debug logging in backend: set `LOG_LEVEL=DEBUG`
