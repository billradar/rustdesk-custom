# Phase 5.2B-1.2 GitHub Authorization Report

Date: 2026-10-03 (Asia/Shanghai)

## Result

**PHASE 5.2B-1.2: PASS**

The owner explicitly selected a single-maintainer authorization model for `billradar/rustdesk-custom`. The Environment's required-reviewer rule was removed through GitHub's environment update API. The Environment's `main`-only deployment branch policy was preserved, and the active `main` ruleset remains in force. No second account was created or added.

```text
AUTHORIZATION MODEL: SINGLE-MAINTAINER
INDEPENDENT REVIEWER: NOT REQUIRED BY DESIGN
INDEPENDENT HUMAN APPROVAL: NOT REQUIRED BY DESIGN
READY FOR PHASE 5.2B-2: YES (separate user authorization is still required to start it)
```

The authorization update follows GitHub's documented environment API: the update set `reviewers` to an empty list and retained `deployment_branch_policy` with custom branch patterns enabled ([GitHub environment API](https://docs.github.com/en/rest/deployments/environments?apiVersion=2022-11-28)).

## Main ruleset

Live API readback verified:

- Ruleset `main-production-trust-path`, ID `24412604`, enforcement `active`, targets exactly `refs/heads/main`.
- PR required: **YES**.
- Required approving reviews: **0**.
- Force push: **BLOCKED** (`non_fast_forward`).
- Branch deletion: **BLOCKED** (`deletion`).
- Review thread resolution: **REQUIRED**.
- Bypass actors: **NONE** (`current_user_can_bypass: never`).
- Stale approvals dismissed on push.
- Required status checks: **NONE**. The existing CI has failing recent runs and ignores documentation-only paths; requiring those contexts could leave applicable changes with pending checks.

The effective `GET /repos/billradar/rustdesk-custom/rules/branches/main` response contained the deletion, non-fast-forward, and pull-request rules from ruleset `24412604`.

## Signing Environment

Live API readback after the update verified:

- Environment: `android-production-signing`.
- Required Environment reviewer: **NONE**; the `required_reviewers` protection rule is absent.
- Deployment branch policy: custom branch policy enabled, protected-branch-only mode disabled; the sole configured branch pattern is **`main`**.
- Admin bypass: **disabled** (`can_admins_bypass: false`).
- `YUBIKEY_PIV_PIN`: **PRESENT**, confirmed only by secret metadata (`updated_at`).
- Secret value accessed: **NO**. The secret was not modified or recreated.

## Single-maintainer security boundaries

Production signing remains constrained by these existing controls and trust dependencies:

1. Active `main` ruleset: PR required; force pushes and branch deletion blocked; no bypass actor.
2. Environment `android-production-signing`: deployments limited to `main`.
3. Reusable signing workflow checks the repository (`billradar/rustdesk-custom`), exact `refs/heads/main`, caller workflow path on `main`, and allowed event/channel before using the runner. PR and fork events do not meet those gates.
4. The signing job targets the dedicated self-hosted runner labels `rustdesk-signing`, `android-signing`, and `yubikey`, with serialized signing concurrency.
5. Signing command is the installed `/usr/local/bin/rustdesk-sign`; installation verification passed. The prior runner-hardening evidence records the root-owned installation and verifies the runner cannot modify it.
6. The prior runner-hardening evidence records PC/SC socket group and mode restrictions, authorized runner access, and denial for an unauthorized account.
7. The YubiKey PIV 9C hardware key is not modified in this phase. Historical Phase 5.1 evidence remains frozen; it is not evidence of a production APK signing run.
8. The workflow's post-sign verification checks the production certificate SHA-256, package, ABI, and Android v2/v3 signature before assembling the output artifact.

These controls do not supply independent second-person review. The owner has accepted that risk as part of the single-maintainer model. The production signing step remains disabled pending Phase 5.2B-2 authorization.

## Workflow and operation status

- Production hardware-signing step: **DISABLED** (`if: ${{ false }}`).
- Workflow triggered: **NO**.
- PIN used: **NO**.
- Private-key operation: **NO**.
- YubiKey modified: **NO**.
- APK signed: **NO**.
- Release/tag: **NO**.
- Workflow file modified: **NO**.
- Commit/push: **NO**.
- `/usr/local/bin/rustdesk-sign --verify-install`: **PASS** (`INSTALLED BRIDGE INTEGRITY: PASS`).
- `git diff --check`: **PASS** after report and README update.

## Final state

```text
PHASE 5.2B-1.2: PASS
AUTHORIZATION MODEL: SINGLE-MAINTAINER
MAIN RULESET: PASS
ENVIRONMENT BRANCH POLICY: MAIN ONLY
REQUIRED ENVIRONMENT REVIEWER: NONE
INDEPENDENT HUMAN APPROVAL: NOT REQUIRED BY DESIGN
YUBIKEY_PIV_PIN: PRESENT
SECRET VALUE ACCESSED: NO
PRODUCTION SIGNING STEP: DISABLED
PIN USED: NO
PRIVATE KEY OPERATION: NO
WORKFLOW TRIGGERED: NO
APK SIGNED: NO
COMMIT: NO
PUSH: NO
READY FOR PHASE 5.2B-2: YES
```

`READY FOR PHASE 5.2B-2: YES` records that the authorization prerequisite is satisfied. Phase 5.2B-2 was **not** started in this task. APK production signing remains **NOT VALIDATED**.
