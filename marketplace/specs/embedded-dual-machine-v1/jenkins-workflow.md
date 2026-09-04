# Jenkins Workflow

Jenkins is a Windows Runtime capability. The AI calls the Windows Agent API;
it does not use an unauthenticated browser session as a fallback.

## Read-Only Checks

```bash
embedded-agent jenkins auth-check --json
embedded-agent jenkins job-inspect --job <job> --json
embedded-agent jenkins parameters --job <job> --build <reference> --json
```

Credentials remain on Windows and are read from the configured local provider.
Never return passwords, tokens, cookies or Authorization headers to the Mac
planner or project repository.

## Artifact Download

Download authenticated build output through the same runtime boundary:

```bash
embedded-agent artifact download \
  --project <project-id> \
  --url <artifact-url> \
  --to artifacts/jenkins/<job>/<build>/<file> \
  --sha256 <expected-sha256> \
  --confirm \
  --json
```

The URL determines the Jenkins/Artifactory credential origin unless an explicit
`--server` is supplied. Cross-origin redirects are rejected. The destination is
relative to the registered Agent workspace. The runtime streams to a temporary
file and publishes it only after SHA-256 verification.

## Normal Build

Use a known successful reference build and override only validated parameter
names:

```bash
embedded-agent jenkins build-start \
  --job <job> \
  --from-build <reference> \
  --set buildBranch=<task-branch> \
  --confirm \
  --json
```

Then wait for the returned build number:

```bash
embedded-agent jenkins build-wait \
  --job <job> \
  --build <number> \
  --json
```

Release, signing, publishing, MES upload and device-operating parameters are
high-risk and require a separate Gate. A normal Debug build is not a hardware
Gate, but still requires explicit task intent and `--confirm`.
