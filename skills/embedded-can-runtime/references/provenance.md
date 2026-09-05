# Provenance

This Skill was independently written after reviewing `zhinkgit/embeddedskills` at commit
`50d85f2766722ee7d43caa9633c2e9cc8ba6e429`.

Borrowed concepts include backend-neutral CAN terminology, explicit interface selection, bounded monitoring,
ID filters, structured results and separate observe/send operations. Upstream scripts were not copied.

The platform-specific design keeps vendor drivers behind the Windows Runtime Interface, requires an L3 gate
for transmit and UDS operations, does not persist an automatically detected adapter, and publishes only commands
implemented by Runtime contract `1.0.0`.

Sources:

- https://github.com/zhinkgit/embeddedskills/blob/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/can/SKILL.md
- https://github.com/zhinkgit/embeddedskills/tree/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/can/scripts

The source repository declares the MIT License. No substantial source-code portion is included here.
