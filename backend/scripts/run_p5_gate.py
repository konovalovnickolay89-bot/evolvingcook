#!/usr/bin/env python3
"""Thin runner: import phase5 gate main without shell-path recursion traps."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "phase5_gate_mod",
    ROOT / "scripts" / "phase5_gate.py",
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
raise SystemExit(mod.main())
