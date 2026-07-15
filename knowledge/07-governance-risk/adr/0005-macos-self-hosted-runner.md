# ADR-0005: Move self-hosted CI to a dedicated MacBook (Intel)

**Status:** Accepted
**Date:** 2026-07-15
**Deciders:** Repository owner

## Context

[ADR-0004](0004-remove-self-hosted-runner.md) removed self-hosted CI from the WSL machine and reverted to GitHub-hosted runners. That removal was itself the correct fix to a real problem: the WSL runner was registered on the repository owner's **daily-use development machine**, not a dedicated box — meaning any compromised dependency in `pip install`/`npm ci` ran with the full privileges of that machine's primary account (mitigated partially by [ADR-0003](0003-dedicated-runner-user.md)'s unprivileged `gha-runner` user, but the machine itself still held the owner's SSH keys, other projects, and daily work).

A generalized runbook exists (`~/docs/self-hosted-github-runner-setup.md`, written from a real self-hosted runner build for the NexVocab repo) whose first principle is exactly this: **use a dedicated machine, not your daily-use dev box.** The repository owner has a MacBook (Intel) available to serve as that dedicated machine, which resolves the actual problem ADR-0004 worked around by removing self-hosting entirely — GitHub Actions minute consumption returns as a live constraint the moment development activity picks back up, since ADR-0004 didn't solve that, only deferred it.

## Decision

Stand up a self-hosted runner on the dedicated MacBook, following the hardened pattern from the generalized runbook, adapted for macOS:

- **Dedicated OS account** (`gha-runner-omeganexus`), created via `sysadminctl`/`dscl`, password-login disabled (`AuthenticationAuthority ";DisabledUser;"`), hidden from the login window, no SSH access, not in `admin`.
- **No Docker** — `ci.yml` doesn't use Docker in any step, so the Docker-group root-equivalence caveat from the runbook doesn't apply here; skipped entirely rather than installed unnecessarily.
- **Python 3.12 and Node 20 via Homebrew**, installed once under the admin account (shared, executable by any user under `/usr/local`, consistent with the runbook's "one-time, shared" guidance for language runtimes) — unlike the Linux Mint case in the runbook, macOS *is* in `actions/setup-python`'s/`actions/setup-node`'s version manifest, so those actions remain usable rather than needing to be routed around.
- **`.path` reset applied proactively** at initial setup (not discovered after a failure this time) — `runsvc.sh` replaces `PATH` entirely from this file's contents, a gotcha already paid for once on the WSL machine ([ISSUE-013](../../08-roadmap/ISSUE_LOG.md#issue-013)) and documented in the runbook (§6) specifically so it doesn't have to be rediscovered per machine.
- **`ci.yml` updated again**: `backend-test`, `agent-test`, `frontend-validate` target `runs-on: [self-hosted, omeganexus-macbook]`; the fork-PR execution guard from [ADR-0002](0002-self-hosted-ci-runner.md) is restored (still applicable — this is a self-hosted machine again); `cache: 'pip'`/`cache: 'npm'` inputs removed again for the same reason as [ISSUE-012](../../08-roadmap/ISSUE_LOG.md#issue-012) — this runner is persistent, so those local caches survive between jobs without GitHub's remote cache round-trip.
- **Keep-awake and network hardening** per the runbook (§8–9): `pmset` sleep disabled on AC power, SSH restricted to LAN-only if remote access to the Mac is needed at all, dedicated runner account confirmed to have no SSH access.

## Alternatives considered

- **Stay on GitHub-hosted (ADR-0004's end state).** Rejected as a long-term answer, not because it was wrong at the time — it correctly removed an actively-worse setup — but because it doesn't address the underlying minute-consumption constraint that motivated self-hosting in the first place ([ADR-0002](0002-self-hosted-ci-runner.md)'s original context). Revisiting self-hosting on genuinely dedicated hardware, rather than assuming "self-hosted" and "runs on my daily driver" are the same thing, resolves the actual objection.
- **Repeat the WSL setup exactly, just accept the daily-driver risk.** Rejected — this is precisely the anti-pattern the generalized runbook opens with, and precisely what [ADR-0004](0004-remove-self-hosted-runner.md) was written to undo. Doing it again on the same machine would be reverting the reversal for no reason.
- **Always-on cloud VM** (documented as the graduation trigger in [ADR-0002](0002-self-hosted-ci-runner.md)). Still not chosen — a MacBook already owned and available is lower-cost than provisioning cloud infrastructure, and the graduation-trigger criteria in that ADR (queue wait time, external contributors, real uptime SLA) haven't been met.

## Consequences

- **Easier:** CI minute consumption is off the table again, this time without the daily-driver security tradeoff — a compromised dependency's blast radius is contained to a machine with nothing else of value on it, not the owner's primary dev environment.
- **Harder:** a second physical machine now needs to stay powered on, network-reachable, and patched. `ci.yml` now depends on the MacBook's availability the same way it depended on the WSL machine's — the same 24-hour job-queue-timeout tradeoff from ADR-0002 applies, just relocated.
- **Commits us to:** keeping the MacBook's dedicated status meaningful — no installing unrelated personal software on it, no reusing `gha-runner-omeganexus` for anything but this runner, and applying the same account-isolation discipline from ADR-0003 if this machine is ever extended to serve a second repo's runner too (per the runbook's "Multi-repo pattern" — a fresh dedicated user per repo, not a shared one).

## Verification

Post-setup checklist (per the runbook's own checklist, restated here so it's checked against this specific instance, not assumed from the general doc):
- [ ] Runner shows `online` in `mittalpk/OmegaNexus` → Settings → Actions → Runners
- [ ] A real `workflow_dispatch` run completes successfully end-to-end on the new runner
- [ ] SSH access (if enabled at all) verified working with keys before password auth is disabled
- [ ] `gha-runner-omeganexus` confirmed to have no SSH access and no admin group membership
- [ ] Sleep/power settings confirmed to keep the machine online while plugged in

## Related

[ADR-0002](0002-self-hosted-ci-runner.md) · [ADR-0003](0003-dedicated-runner-user.md) · [ADR-0004](0004-remove-self-hosted-runner.md) · `~/docs/self-hosted-github-runner-setup.md` (generalized runbook, outside this repo) · [Issue Log — ISSUE-012, ISSUE-013](../../08-roadmap/ISSUE_LOG.md)
