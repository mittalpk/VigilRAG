# Workspace Agent Rules

## Pre-Push Test Verification

Before pushing any git branch or opening a pull request, **always** run full test verification from the repository root to ensure import paths and environment setup exactly match the GitHub Actions CI environment:

```bash
# Backend Test Check (run from repo root)
python3 -m pytest backend/tests -v

# Agent Test Check (run from repo root)
python3 -m pytest agent/tests -v

# Frontend Type-check & Build (run from frontend dir)
cd frontend && npm run build
```
