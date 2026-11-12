# Release GitHub App

Stable and Nightly release writers use a short-lived, repository-scoped GitHub
App installation token. This fixes Release creation for an exact historical
build commit when `.github/workflows/` has changed on the default branch while
the build was running. `contents: write` on `GITHUB_TOKEN` is insufficient in that
case; that token cannot receive Workflows write permission.

The target remains the validated build commit. Do not switch it to current main,
rewrite a tag, reuse another batch's qualification or publish a release to avoid
an authentication failure.

## One-time account setup

1. Register a dedicated App at <https://github.com/settings/apps/new>. Set its
   homepage to this repository. A user authorization callback is unnecessary;
   disable webhooks unless you separately need them. Restrict installation to
   this account and install it only on `billradar/rustdesk-custom`.
2. Grant repository permissions **Contents: Read and write**, **Workflows: Read
   and write**, and **Actions: Read-only**. Metadata read is implicit. No account,
   administration or production-signing permissions are needed.
3. Install the App on this repository. If changing an existing App's permissions,
   approve the updated installation permissions too.
4. Save its **Client ID** as repository Actions Variable `RELEASE_APP_CLIENT_ID`.
5. Generate an App private key and save the PEM as repository Actions Secret
   `RELEASE_APP_PRIVATE_KEY`. Do not put it in chat, repository files, Variables,
   workflow logs or artifacts. Use the GitHub settings UI or, locally:

   ```sh
   gh variable set RELEASE_APP_CLIENT_ID --repo billradar/rustdesk-custom --body 'YOUR_CLIENT_ID'
   gh secret set RELEASE_APP_PRIVATE_KEY --repo billradar/rustdesk-custom < /secure/path/release-app.private-key.pem
   ```

Variable and Secret settings:
<https://github.com/billradar/rustdesk-custom/settings/secrets/actions>
and <https://github.com/billradar/rustdesk-custom/settings/variables/actions>.

## Scope and execution

`actions/create-github-app-token` v3.2.0 is pinned by full SHA and runs on Node.js
24. The local `.github/actions/release-app-token` explicitly requests only this
repository and the three permission levels above. Default post-job token
revocation remains enabled. The private key is passed only to that Action;
installation tokens are masked and passed only to the final release script step,
not to compilers, artifact downloads, package-manager steps or signing jobs.
Actions read is required because release validation reads same-run job evidence.

Only the existing protected-main, manual Stable/Nightly release-writing jobs can
mint a token. Their release mode, aggregate/qualification, signatures and
publication gates remain unchanged. CI, builds and Android hardware signing do
not receive the App private key or installation token.

For non-dry-run modes, resolution checks that the Client ID and Secret exist
before expensive builds. The checker receives only a Boolean for key presence;
it cannot validate the private key, installation or granted permissions. Those
are checked when the Action mints the token. Dry-run does not require this App.
No fallback to the insufficient `GITHUB_TOKEN` or a personal token is provided.

## Existing failed runs

Re-running an old run uses that run's old workflow/code, so it does not pick up
this fix. Do not rerun the entire historical build merely to test authentication.
After configuration and integration, use a fresh eligible workflow for future
builds. Recovering an older qualified batch requires a separately reviewed path
that preserves its locked commit, run, artifact hashes and selected patch
revision. No old release or artifact is overwritten by this change.

## Validation

Run the production, Stable channel, Nightly, repository and Action runtime
contracts. PR CI verifies workflow structure and existing Rust/Flutter behavior;
it deliberately does not mint a privileged App token or create a release.
A successful live authenticated release operation still requires the one-time
App configuration and an authorized eligible release workflow.

References:
- <https://docs.github.com/en/rest/releases/releases#create-a-release>
- <https://github.com/actions/create-github-app-token/tree/bcd2ba49218906704ab6c1aa796996da409d3eb1>

The separate manual `publish-stable.yml` requests Contents write and
Actions/Attestations/Administration read directly from the same installed App.
Administration read must be granted on the App and approved on its installation
before use; it is only for checking immutable-release policy, never changing it.
The shared Draft/build App action is not broadened. Its native-proof verification
uses a checksum-pinned CLI, installed before minting the token. See
[Manual publication](manual-stable-publication.md).
