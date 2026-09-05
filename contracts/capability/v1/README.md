# Capability Contract v1

Capability Contract v1 defines the model-neutral target boundary between an
engineering Agent and a controlled embedded Runtime. The current Runtime wires
the additive result envelope and typed persistent Job requests. Catalog,
persisted preflight, normalized execution/status, and terminal receipt schemas
are the next lifecycle slice; they are normative designs, not yet public
Runtime handlers.

The completed lifecycle must not expose an arbitrary shell. Every capability id
will resolve to a Runtime-owned handler with a versioned input schema, bounded
output, declared side effects and a fixed evidence policy.

## Target lifecycle

1. **Discover** returns capability descriptors and current availability. It
   may inspect configuration but must not change a project or device.
2. **Preflight** validates normalized inputs, project background, exact source
   revision, tools, artifacts and device selectors. It returns an opaque
   `preflight_id` bound to an `input_digest` and an expiry time.
3. **Execute** consumes the same normalized input and, for L2-L4 operations, a
   matching preflight and scoped approval. A synchronous execution is terminal;
   an asynchronous execution returns `accepted` or `running` plus a `job_id`.
4. **Status** reads an existing execution. State transitions are monotonic:
   `accepted -> running -> succeeded|failed|canceled`.
5. **Evidence** returns a write-once receipt for every terminal execution,
   including blocked, failed and canceled attempts.

Preflight is not authorization. Approval must be bound to the capability id,
normalized-input digest, project/background, target or device, and an expiry.
Execution must repeat volatile checks and fail closed if that scope changed.

## Risk levels

| Level | Meaning | Examples |
| --- | --- | --- |
| L0 | Observation only | status, bounded reads, inventory |
| L1 | Bounded local/runtime state | build, evidence import, start a read-only wait job |
| L2 | Workspace or non-production service mutation | Git switch/commit, SDK materialization, artifact download |
| L3 | Device, bus or host-process mutation | flash, reset, CAN transmit, process stop |
| L4 | Irreversible, release or production mutation | eFuse, production signing/deploy, destructive workspace removal |

Risk level is independent from availability. A capability can be available but
blocked pending approval. L3 and L4 always require explicit human approval; L4
must not accept a legacy boolean confirmation as proof of approval.

## Schemas

- `schemas/result.schema.json`: additive envelope used by the current fixed CLI.
- `schemas/catalog.schema.json`: Runtime and capability discovery document.
- `schemas/preflight.schema.json`: immutable preflight decision.
- `schemas/execution.schema.json`: synchronous result or asynchronous state.
- `schemas/status.schema.json`: observation of one asynchronous execution.
- `schemas/receipt.schema.json`: terminal evidence receipt.
- `schemas/job-request.schema.json`: typed persistent Runtime Job request.
- `schemas/common.schema.json`: shared context, Gate, error and evidence types.

All JSON timestamps are timezone-qualified ISO-8601 strings. Digests are
lowercase SHA-256. JSON mode writes exactly one result object to stdout;
diagnostics and progress belong on stderr or in referenced logs.

## Compatibility with Runtime 0.x

The v1 result envelope is additive. Existing `ok`, `operation`, `exit_code`,
`timestamp`, `first_failure`, `gate`, `backend` and command-specific top-level
fields remain available throughout v1. New consumers should use
`schema_version`, `contract_version`, `capability_id`, `phase`, `state`,
`error` and `evidence`; unknown top-level fields must be ignored. The optional
`platform_version` identifies the installed platform release and is independent
from `contract_version`.

`ok` and `error` describe whether the requested Runtime command was processed.
For Job status/output commands, `state` describes the referenced execution, so
an `ok: true` status query can legitimately report `state: failed`.

The legacy `gate` field is intentionally not part of the normalized result
schema because existing commands use both strings and objects. New lifecycle
documents use the single Gate type from `common.schema.json`. A future Runtime
adapter should expose the normalized Gate while retaining the old field as a
deprecated alias for v1.

Existing command names remain ergonomic aliases for registered capabilities.
Removing or changing a required field, capability id, risk meaning or state
transition requires a new contract major. Adding an optional field or a new
capability is compatible.

Persistent Runtime Jobs use `embedded-runtime-job-request/v2`. The request
contains only an allowlisted `kind` and typed `parameters`; it never persists
an executable, shell string, working directory or environment. The runner
revalidates the request and rebuilds the fixed `embedded_agent.py` argument
vector. Queued legacy v1 requests containing `command` fail closed, while
existing v1 terminal status and evidence remain readable.

Jenkins Job parameters contain only a `connection_id`, never a server or
credential-file path. The Windows Runtime resolves that id through its
machine-owned registry at execution time. The binding is enforced for every
authenticated request and artifact download, including redirects.

## Receipt integrity

A receipt records normalized/redacted input, context identity, Gate decision,
outcome, producer and evidence references. `payload_sha256` detects accidental
or uncoordinated modification; it is not proof of authenticity. Signed or
externally anchored receipts can be added later without changing the v1
lifecycle.
