"""Writable storage path defaults (home vs project-local fallback)."""

from __future__ import annotations

import importlib
import os
import unittest
from unittest.mock import patch

import tradingagents.default_config as default_config_module


class TestStoragePaths(unittest.TestCase):
    def test_falls_back_to_cwd_when_home_not_writable(self):
        real_makedirs = os.makedirs
        home = default_config_module._TRADINGAGENTS_HOME

        def guarded_makedirs(path, *args, **kwargs):
            if path.startswith(home):
                raise PermissionError("sandbox")
            return real_makedirs(path, *args, **kwargs)

        with patch.object(os, "makedirs", side_effect=guarded_makedirs):
            path = default_config_module._default_storage_dir("cache", env_var=None)

        self.assertIn(".tradingagents", path)
        self.assertTrue(os.path.isdir(path))

    def test_explicit_env_overrides_home(self):
        with patch.dict(os.environ, {"TRADINGAGENTS_CACHE_DIR": "/tmp/ta-test-cache"}, clear=False):
            importlib.reload(default_config_module)
            path = default_config_module._default_storage_dir(
                "cache", env_var="TRADINGAGENTS_CACHE_DIR"
            )
        self.assertEqual(path, "/tmp/ta-test-cache")


if __name__ == "__main__":
    unittest.main()
