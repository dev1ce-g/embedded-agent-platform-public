# Platform Contracts

This directory owns the stable, model-neutral interfaces between calling
Agents, platform clients and Capability Adapters. Contracts describe data,
risk, lifecycle and evidence semantics; they do not prescribe an Agent's
planning workflow or reasoning process.

Published design schemas (current Runtime wiring is called out in the linked
document):

- [Capability Contract v1](capability/v1/README.md): capability discovery,
  preflight, execution, status and evidence receipts.

Contract implementations must retain fixed, typed capability handlers. A
schema must never be used to introduce arbitrary shell or backend argument
pass-through. Within one major version, required fields and their meanings are
stable; compatible additions are optional and consumers must ignore unknown
fields.
