#!/usr/bin/env python3
"""Bootstrap: apply DNS patch then run target script (used by run.sh)."""

from __future__ import annotations

import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(__file__))

import dns_patch

dns_patch.apply()

if len(sys.argv) < 2:
    print("usage: _run.py <script.py> [args...]", file=sys.stderr)
    raise SystemExit(2)

target = sys.argv[1]
sys.argv = [target, *sys.argv[2:]]
runpy.run_path(target, run_name="__main__")
