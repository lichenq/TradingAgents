#!/usr/bin/env python3
"""HTTP helpers for Cursor Agent: curl-first option, no proxy, requests fallback."""

from __future__ import annotations

import json
import os

try:
    from dns_patch import apply as _apply_dns_patch

    _apply_dns_patch()
except Exception:
    pass
import shutil
import subprocess
import urllib.parse
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def prefer_curl() -> bool:
    return os.environ.get("A_SHARE_PREFER_CURL", "1").strip().lower() not in ("0", "false", "no")


def curl_env() -> dict:
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
        "SOCKS_PROXY", "SOCKS5_PROXY", "socks_proxy", "socks5_proxy",
        "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def build_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": DEFAULT_UA})
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _curl_get(url: str, timeout: int, headers: Optional[Dict[str, str]] = None) -> str:
    curl_bin = shutil.which("curl")
    if not curl_bin:
        raise RuntimeError("curl not found")
    cmd = [
        curl_bin,
        "-fsS",
        "--max-time",
        str(max(5, timeout)),
        "-H",
        f"User-Agent: {DEFAULT_UA}",
    ]
    for key, value in (headers or {}).items():
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=curl_env(),
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"curl exit {proc.returncode}"
        raise RuntimeError(err)
    return proc.stdout


def _requests_get_text(
    url: str,
    params: Optional[dict] = None,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    session = build_session()
    if headers:
        session.headers.update(headers)
    resp = session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def get_text(
    url: str,
    params: Optional[dict] = None,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    full_url = url
    if params:
        full_url = f"{url}?{urllib.parse.urlencode(params)}"
    errors = []
    order = ("curl", "requests") if prefer_curl() else ("requests", "curl")
    for mode in order:
        try:
            if mode == "curl":
                return _curl_get(full_url, timeout, headers=headers)
            return _requests_get_text(url, params=params, timeout=timeout, headers=headers)
        except Exception as exc:
            errors.append(f"{mode}: {exc}")
    raise RuntimeError("; ".join(errors))


def get_json(
    url: str,
    params: Optional[dict] = None,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    text = get_text(url, params=params, timeout=timeout, headers=headers)
    return json.loads(text)
