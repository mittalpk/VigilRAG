# Deployment Skip Issue & Resolution

## 🔴 Problem: Deployment Skipped for Backend, Frontend & Agent

### Why Deployments Were Skipped

The GitHub Actions workflow uses **path-based filtering** to determine which services to deploy:

```yaml
jobs:
  filter:
    steps:
      - name: Check for Changes
        uses: dorny/paths-filter@v3
        with:
          filters: |
            backend:
              - 'backend/**'
              - 'agent/**'           # ⚠️ Note: agent also triggers backend deploy
              - 'terraform/**'
              - '.github/workflows/deploy.yml'
            agent:
              - 'backend/**'          # ⚠️ Note: backend also triggers agent deploy
              - 'agent/**'
              - 'terraform/**'
              - '.github/workflows/deploy.yml'
            frontend:
              - 'frontend/**'
              - 'terraform/**'
              - '.github/workflows/deploy.yml'
```

**If your changes didn't touch these specific paths, the jobs were skipped.**

---

## ✅ Solution Applied

### Method 1: Manual Workflow Dispatch (APPLIED NOW ✅)

Triggered deployment using GitHub workflow_dispatch:

```bash
gh workflow run deploy.yml --ref main
```

**Result**: All 3 services deploy regardless of path changes

**Advantages**:
- ✅ Forces full deployment immediately
- ✅ No code changes needed
- ✅ Can be triggered anytime
- ✅ Useful for force-rescanning secrets

**When to use**:
- After secret rotation
- Terraform-only changes don't trigger rebuilds
- Documentation-only changes
- Debugging deployment issues
- Emergency redeployment

---

### Method 2: Force Rebuild by Editing Trigger File

To make commit push automatically trigger full deployment:

```bash
# Touch workflow file to trigger all jobs
touch .github/workflows/deploy.yml
git add .github/workflows/deploy.yml
git commit -m "chore: trigger full deployment"
git push origin main
```

**Why it works**: Workflow file changes trigger all conditional jobs  
**Drawback**: Creates unnecessary commit noise

---

### Method 3: Environment Variable Cache-Busting

Add a build-time environment variable that changes every deploy:

```dockerfile
# backend/Dockerfile
ARG BUILD_ID="default"
ENV BUILD_ID=$BUILD_ID
RUN echo "Build ID: $BUILD_ID"
```

Set in workflow:
```yaml
- name: Build and Push Backend
  run: |
    docker build \
      -t ghcr.io/mittalpk/omega-nexus-backend:${{ github.sha }} \
      --build-arg BUILD_ID="$(date +%s)" \
      ./backend
```

---

## 📊 Path Filter Analysis

### What Triggers Backend Deploy

✅ **Deploys**:
- Changes in `backend/` directory
- Changes in `agent/` directory (also triggers backend!)
- Changes in `terraform/` directory
- Changes to `.github/workflows/deploy.yml`

❌ **Does NOT Deploy**:
- Changes to `.md` documentation files
- Changes to `.github/workflows/` (only deploy.yml counts)
- Changes to `mock_data/`
- Changes to `scripts/`
- Changes to `Testing/`
- Changes to `.gitignore`, root-level files

### What Triggers Agent Deploy

✅ **Deploys**:
- Changes in `agent/` directory
- Changes in `backend/` directory (also triggers agent!)
- Changes in `terraform/` directory
- Changes to `.github/workflows/deploy.yml`

### What Triggers Frontend Deploy

✅ **Deploys**:
- Changes in `frontend/` directory
- Changes in `terraform/` directory
- Changes to `.github/workflows/deploy.yml`

---

## 🔧 Why Documentation Changes Don't Trigger Deployment

**Reason**: Documentation files (`.md`, `.txt`) are NOT in the filter paths

**Implications**:
- Adding `API_KEY_401_FIX.md` = ❌ No deployment
- Adding `TROUBLESHOOTING_COMPLETE.md` = ❌ No deployment
- Adding `SECRET_ROTATION_GUIDE.md` = ❌ No deployment
- Modifying `terraform/main.tf` = ✅ Full deployment triggered

**Solution**: Commit docs separately from code changes, or manually trigger with `workflow_dispatch`

---

## 🚀 Manual Deployment Procedures

### Option A: Using GitHub CLI (Automated)

```bash
# Install GitHub CLI first
# https://cli.github.com

# Authenticate
gh auth login

# Trigger workflow
gh workflow run deploy.yml --ref main

# Monitor execution
gh run list --workflow=deploy.yml --limit 3
gh run view <run-id> --log
```

### Option B: Using Azure CLI (Direct)

Directly update Container Apps without waiting for CI/CD:

```bash
# Get latest image sha
LATEST_SHA=$(git log -1 --format=%H)

# Manual update backend
az containerapp update \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --image "ghcr.io/mittalpk/omega-nexus-backend:${LATEST_SHA}"

# Manual update agent
az containerapp update \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --image "ghcr.io/mittalpk/omega-nexus-agent:${LATEST_SHA}"

# Manual update frontend
az containerapp update \
  --name ca-omega-frontend \
  --resource-group rg-omega-nexus \
  --image "ghcr.io/mittalpk/omega-nexus-frontend:${LATEST_SHA}"
```

**Requirements**:
- Azure CLI installed
- Authenticated to Azure (`az login`)
- Container images already pushed to registry

### Option C: GitHub UI (Manual)

1. Go to: `https://github.com/mittalpk/OmegaNexus/actions/workflows/deploy.yml`
2. Click "Run workflow" dropdown (top-right)
3. Select branch: `main`
4. Click "Run workflow" button
5. Monitor progress in "Actions" tab

---

## 📈 Deployment Status Monitoring

### Check Build Status
```bash
# Via GitHub CLI
gh run list --workflow=deploy.yml --limit 5

# Output shows: Status, Trigger, Branch, etc.
```

### Check Container App Deployment
```bash
# Backend
az containerapp show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --query "properties.provisioningState"
# Expected: "Succeeded"

# Agent
az containerapp show \
  --name ca-omega-agent \
  --resource-group rg-omega-nexus \
  --query "properties.provisioningState"

# Frontend
az containerapp show \
  --name ca-omega-frontend \
  --resource-group rg-omega-nexus \
  --query "properties.provisioningState"
```

### Check Recent Revisions
```bash
az containerapp revision list \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --query "sort_by([], &properties.createdTime) | [-3:].[name, properties.createdTime, properties.active]" \
  -o table
```

### Monitor Container Logs
```bash
# Last 50 lines
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --tail 50

# Follow logs (stream)
az containerapp logs show \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --follow
```

---

## 🛡️ Preventing Future Deployment Skips

### Solution 1: Always Include Code Changes

When making infrastructure changes, include a small code change:

```bash
# In your code (backend/app/main.py, agent/app/main.py, etc.)
# Add a comment or version bump
APP_VERSION = "1.0.4"  # Cache buster for deployment

git add -A
git commit -m "feat: feature-name; infra: update terraform"
git push
```

### Solution 2: Modify Path Filter

Update `.github/workflows/deploy.yml` to include documentation:

```yaml
backend:
  - 'backend/**'
  - 'agent/**'
  - 'terraform/**'
  - '.github/workflows/deploy.yml'
  - '*.md'  # ← Add this line to include markdown changes
```

### Solution 3: Separate Documentation & Code Branches

Use dedicated branches:
- `main` = Code and infrastructure changes only
- `docs` = Documentation changes (no auto-deploy)
- Create PR to merge docs into main after code reviewed

### Solution 4: Always Manual Trigger

For non-code changes, always use `workflow_dispatch`:

```bash
# After committing documentation
git push origin main

# Manually trigger deployment
gh workflow run deploy.yml --ref main
```

---

## 📝 Best Practices Going Forward

| Scenario | Action |
|----------|--------|
| Code changes | Push normally → Auto-deploys ✅ |
| Terraform changes | Push normally → Auto-deploys ✅ |
| Documentation only | Push + manual trigger with `gh workflow run` |
| Emergency redeploy | Use `gh workflow run` or Azure CLI |
| Secret rotation | Push code changes OR manual trigger |
| Testing path filters | Check `dorny/paths-filter@v3` docs |

---

## ⚙️ Current Deployment (Now Active)

**Status**: ✅ Manual workflow_dispatch triggered  
**Services**: Backend, Agent, Frontend  
**Secrets**: Using corrected `internal-api-key` reference  
**ETA**: 15-20 minutes to completion  
**Monitor**: https://github.com/mittalpk/OmegaNexus/actions

---

## 🔍 Troubleshooting Deployment Issues

### Build Failed?
```bash
# Check recent build logs
gh run list --workflow=deploy.yml --limit 1
gh run view <run-id> --log

# Common issues:
# - Docker build error: Check Dockerfile syntax
# - Azure login failed: Check AZURE_CREDENTIALS secret
# - GHCR push failed: Check GHCR_PAT perssion
```

### Deployment Succeeded But Container Shows Old Version?
```bash
# Force container app to pull latest image
az containerapp update \
  --name ca-omega-backend \
  --resource-group rg-omega-nexus \
  --image "ghcr.io/mittalpk/omega-nexus-backend:475184e"
```

### Secret References Not Working?
```bash
# Verify secret exists in Key Vault
az keyvault secret show \
  --vault-name kv-omega-nexus-ecc63471 \
  --name internal-api-key

# Verify Managed Identity has access
az keyvault show \
  --name kv-omega-nexus-ecc63471 \
  --query properties.accessPolicies[]
```

---

## 📞 Next Steps

1. ⏳ **Wait 15-20 minutes** for deployment to complete
2. 🧪 **Verify**: Check all 3 services show "Succeeded" status
3. ✅ **Test**: Run Multi Agent query to verify 401 errors are fixed
4. 📊 **Monitor**: Keep eye on container logs for errors
5. 📋 **Document**: Add any lessons learned to team wiki

Current deployment live at: **https://github.com/mittalpk/OmegaNexus/actions**
