#!/usr/bin/env python3
"""Windows-local embedded agent compatibility entry point.

The implementation is split by runtime domain. Keep this file stable because
the Windows Python launcher and existing Python callers import it directly.
"""

from __future__ import annotations

from embedded_runtime_common import *
from embedded_runtime_aboot import *
from embedded_runtime_git import *
from embedded_runtime_sdk import *
from embedded_runtime_device import *
from embedded_runtime_diagnose import *
from embedded_runtime_can import *
from embedded_runtime_knowledge import *
from embedded_runtime_jenkins import *
from embedded_runtime_tools import *
from embedded_runtime_operations import *
from embedded_runtime_cli import build_parser, main


if __name__ == "__main__":
    raise SystemExit(main())
