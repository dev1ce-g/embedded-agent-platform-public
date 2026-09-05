# Jenkins Capabilities

Jenkins is a Windows Runtime capability. The caller uses the fixed Runtime API;
it does not use an unauthenticated browser session as a fallback.

## Read-Only Checks

```bash
embedded-agent jenkins --connection-id <connection-id> auth-check --json
embedded-agent jenkins --connection-id <connection-id> job-inspect --job <job> --json
embedded-agent jenkins --connection-id <connection-id> parameters --job <job> --build <reference> --json
```

Credentials remain on Windows and are read from the configured local provider.
Never return passwords, tokens, cookies, or Authorization headers to the calling
Agent or project repository. The caller selects only an opaque `connection_id`.
The machine-owned registry binds that id to one server origin and one absolute
credential-file path; task input cannot override either value.

## Artifact Download

Download authenticated build output through the same runtime boundary:

```bash
embedded-agent artifact download \
  --connection-id <connection-id> \
  --project <project-id> \
  --url <artifact-url> \
  --to artifacts/jenkins/<job>/<build>/<file> \
  --sha256 <expected-sha256> \
  --confirm \
  --json
```

The selected connection determines the only Jenkins/Artifactory origin that may
receive its credentials. A URL on another origin and every cross-origin redirect
are rejected before credentials are sent. The destination is relative to the
registered Agent workspace. The runtime streams to a temporary file and
publishes it only after SHA-256 verification.

## Normal Build

Use a known successful reference build and override only validated parameter
names:

```bash
embedded-agent jenkins --connection-id <connection-id> build-start \
  --job <job> \
  --from-build <reference> \
  --set buildBranch=<task-branch> \
  --confirm \
  --json
```

Then wait for the returned build number:

```bash
embedded-agent jenkins --connection-id <connection-id> build-wait \
  --job <job> \
  --build <number> \
  --json
```

Release, signing, publishing, MES upload and device-operating parameters are
high-risk and require a separate Gate. A normal Debug build is not a hardware
Gate, but still requires explicit task intent and `--confirm`.
