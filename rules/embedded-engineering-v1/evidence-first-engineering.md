# Evidence-First Embedded Engineering

Use this rule for design, diagnosis, review and implementation where the
repository contains multiple targets, generated variants, reference projects,
prebuilt libraries or logs from different clocks.

## Active Target Gate

Before writing code or freezing a design, identify the artifact that actually
controls the target behavior. Acceptable evidence includes:

- CI or repository manifest membership;
- Keil/CMake/build project source membership and active target;
- linked library or generated configuration source;
- deployed service/package manifest;
- runtime registration and call chain;
- exact Git revision used by Windows or Jenkins.

A matching directory name, newer-looking copy, sibling platform or reference
project does not satisfy this gate. Record the selected target and evidence in
the active context. If the gate fails, continue read-only discovery.

## Design Proportionality

Start from the required behavior, precision, platform capability and existing
contract. Keep a stable seam for expected variation, but add generalized
selection, quality scoring, transaction phases, retries or policy objects only
when one of these exists:

- a second concrete project or source with different behavior;
- a written public contract that requires the variation;
- a demonstrated failure that the abstraction prevents;
- an acceptance test that cannot be expressed with the simpler design.

Document speculative extensions as future decisions rather than implementing
them in the current path.

## Correction Gate

When the user or new repository evidence invalidates a path, target, timing
semantics or scope:

1. Mark the old statement as invalid in the active context.
2. Update target paths, contracts, acceptance criteria and plan.
3. Search current changes and pending actions for dependencies on the old
   statement.
4. Continue only after those dependencies are removed or explicitly retained
   with evidence.

## Log Evidence Protocol

Before computing a duration or causal sequence:

1. Identify every timestamp source and unit.
2. Detect boot/reset boundaries, counter wrap, timezone changes and logger
   buffering.
3. Choose observable start and end anchors and quote their artifact line IDs.
4. Calculate measured intervals separately for each clock domain.
5. Label cross-domain alignment, missing intervals and causal explanations as
   inference with uncertainty.
6. Preserve the imported log artifact ID or source path and hash when the
   Runtime provides them.

Do not infer time spent in an unobserved state from the gap between unrelated
clocks without an explicit alignment event.

## Completion Matrix

Report each applicable layer separately:

| Layer | Minimum evidence |
| --- | --- |
| Static | exact check command and exit code |
| Host/unit | test command, counts and result |
| Windows build | project/background ID, command, exit code, success/failure marker and log |
| Artifact | path, fresh timestamp, size and SHA-256 |
| Jenkins | job, build number, terminal result and relevant console/artifact evidence |
| Device | authorized operation, exact artifact hash, target and probe identity, interface/speed, operation markers and runtime/RTT/CAN evidence |

A passed lower layer does not imply a higher layer. State unverified layers and
the risk they leave open.
