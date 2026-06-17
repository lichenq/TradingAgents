"""Bypass broken sandbox/corporate DNS for China finance API hosts (akshare/requests)."""

from __future__ import annotations

import socket

_SUFFIXES = (
    "eastmoney.com",
    "sina.com.cn",
    "sinajs.cn",
)

_STATIC_IPS = {
    "datacenter.eastmoney.com": "223.95.60.19",
}


def _needs_patch(host: str) -> bool:
    if host in _STATIC_IPS:
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in _SUFFIXES)


def apply() -> None:
    if getattr(socket, "_a_share_dns_patched", False):
        return

    import dns.resolver as _dns_resolver

    _original_getaddrinfo = socket.getaddrinfo

    def _resolve_public(host: str, port: int | str) -> list:
        resolver = _dns_resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        resolver.timeout = 3
        resolver.lifetime = 5
        answers = resolver.resolve(host, "A")
        port_int = int(port) if port else 443
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (str(answers[0]), port_int))
        ]

    def _patched_getaddrinfo(
        host, port, family=0, type=0, proto=0, flags=0
    ):
        if not isinstance(host, str) or not _needs_patch(host):
            return _original_getaddrinfo(host, port, family, type, proto, flags)

        static_ip = _STATIC_IPS.get(host)
        if static_ip:
            try:
                port_int = int(port) if port else 443
                return [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        6,
                        "",
                        (static_ip, port_int),
                    )
                ]
            except Exception:
                pass

        try:
            return _resolve_public(host, port)
        except Exception:
            return _original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = _patched_getaddrinfo
    socket._a_share_dns_patched = True  # type: ignore[attr-defined]
