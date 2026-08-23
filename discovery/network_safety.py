"""Network-scope checks for controlled public website crawling."""

import ipaddress
import socket
from urllib.parse import urlsplit


def static_public_hostname(hostname: str) -> bool:
    host = str(hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    # Business discovery requires a stable public domain, not a literal address.
    return False


def resolve_addresses(hostname: str):
    return [
        item[4][0]
        for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    ]


def public_web_url(url: str, resolver=resolve_addresses) -> bool:
    parsed = urlsplit(str(url or ""))
    if parsed.scheme.lower() not in {"http", "https"} or not static_public_hostname(parsed.hostname or ""):
        return False
    try:
        addresses = list(resolver(parsed.hostname))
        return bool(addresses) and all(ipaddress.ip_address(item).is_global for item in addresses)
    except (OSError, ValueError, TypeError):
        return False
