#!/usr/bin/env python3
"""Tests for premarket_jobs entry script."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestPremarketJobs(unittest.TestCase):

    def test_status_exits_zero(self):
        proc = subprocess.run(
            [str(ROOT / "scripts/premarket_jobs.sh"), "status"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("evening", proc.stdout)
        self.assertIn("09:35", proc.stdout)


if __name__ == "__main__":
    unittest.main()
