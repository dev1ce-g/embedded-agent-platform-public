"""Shared Capability Contract v1 result helpers.

The public Runtime and its fixed Python backends use this module so their JSON
envelopes cannot drift independently.  Command-specific fields remain at the
top level for v0.x compatibility; v1 consumers should rely on the fields added
here and treat other fields as capability payload.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


CAPABILITY_CONTRACT_VERSION = "1.0.0"
CAPABILITY_RESULT_SCHEMA_VERSION = "embedded-capability-result/v1"

_ERRORS_BY_EXIT_CODE: dict[int, tuple[str, str, bool]] = {
    2: ("INVALID_REQUEST", "invalid_request", False),
    3: ("APPROVAL_REQUIRED", "authorization", False),
    4: ("OPERATION_FAILED", "execution", False),
    5: ("POLICY_BLOCKED", "policy", False),
    6: ("PRECONDITION_FAILED", "precondition", False),
    124: ("TIMEOUT", "timeout", True),
    126: ("ADAPTER_INVALID", "availability", False),
    127: ("CAPABILITY_UNAVAILABLE", "availability", True),
    130: ("CANCELED", "canceled", False),
    255: ("TRANSPORT_UNAVAILABLE", "transport", True),
}


def contract_now_iso() -> str:
    """Return the contract timestamp format: UTC ISO-8601 with seconds."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def capability_id_for_operation(operation: str) -> str:
    """Derive a stable machine id while legacy commands still own routing."""
    normalized = re.sub(r"[^a-z0-9]+", ".", operation.strip().lower()).strip(".")
    return normalized or "unknown"


def _failure_state(exit_code: int, fields: dict[str, Any]) -> str:
    if exit_code == 130:
        return "canceled"
    if exit_code == 3:
        return "approval_required"
    if fields.get("blocked"):
        return "blocked"
    return "failed"


def _structured_error(exit_code: int, fields: dict[str, Any]) -> dict[str, Any]:
    default_code, category, default_retryable = _ERRORS_BY_EXIT_CODE.get(
        exit_code,
        ("OPERATION_FAILED", "execution", False),
    )
    error_code = str(fields.get("error_code") or default_code)
    message = str(fields.get("first_failure") or "Capability operation failed")
    value: dict[str, Any] = {
        "code": error_code,
        "category": category,
        "message": message,
        "retryable": bool(fields.get("retryable", default_retryable)),
    }
    next_hint = fields.get("next_hint")
    if next_hint:
        value["next_hint"] = str(next_hint)
    return value


def capability_result(
    ok: bool,
    operation: str,
    exit_code: int = 0,
    *,
    timestamp: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build an additive, legacy-compatible Capability Contract v1 envelope."""
    explicit_capability_id = fields.pop("capability_id", None)
    explicit_phase = fields.pop("phase", None)
    explicit_state = fields.pop("state", None)
    capability_id = str(explicit_capability_id or capability_id_for_operation(operation))
    phase = str(explicit_phase or "execute")
    state = str(explicit_state or ("succeeded" if ok else _failure_state(exit_code, fields)))
    evidence = fields.pop("evidence", [])
    explicit_error = fields.pop("error", None)
    error = None if ok else explicit_error or _structured_error(exit_code, fields)
    value: dict[str, Any] = {
        "schema_version": CAPABILITY_RESULT_SCHEMA_VERSION,
        "contract_version": CAPABILITY_CONTRACT_VERSION,
        "capability_id": capability_id,
        "phase": phase,
        "state": state,
        "ok": ok,
        "operation": operation,
        "exit_code": exit_code,
        "timestamp": timestamp or contract_now_iso(),
        "evidence": evidence,
        "error": error,
    }
    value.update(fields)
    return value
