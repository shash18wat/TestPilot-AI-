"""Outbound URL validation for user-authorized API test targets."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

from aiohttp.abc import AbstractResolver


class TargetRejected(ValueError):
    """Raised when a test target is not explicitly safe and permitted."""


class PinnedResolver(AbstractResolver):
    """Return only the already-validated IP address for one approved hostname."""

    def __init__(self, hostname: str, address: str):
        self.hostname = hostname.lower().rstrip(".")
        self.address = str(ipaddress.ip_address(address))

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if host.lower().rstrip(".") != self.hostname:
            raise OSError("Unvalidated hostname blocked")
        parsed_address = ipaddress.ip_address(self.address)
        return [{
            "hostname": host,
            "host": self.address,
            "port": port,
            "family": socket.AF_INET6 if parsed_address.version == 6 else socket.AF_INET,
            "proto": 0,
            "flags": 0,
        }]

    async def close(self):
        return None


def allowed_hosts() -> set[str]:
    values = os.getenv("TESTPILOT_ALLOWED_HOSTS", "")
    return {item.strip().rstrip(".").encode("idna").decode("ascii").lower() for item in values.split(",") if item.strip()}


def configured_target_hosts() -> list[str]:
    return sorted(allowed_hosts())


def _public_addresses(host: str, port: int) -> list[str]:
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise TargetRejected("The target hostname could not be resolved.") from exc
        addresses = []
        for answer in answers:
            try:
                addresses.append(ipaddress.ip_address(answer[4][0].split("%", 1)[0]))
            except ValueError:
                continue
    if not addresses:
        raise TargetRejected("The target hostname did not resolve to an IP address.")
    if any(not address.is_global for address in addresses):
        raise TargetRejected("Targets resolving to private, local, or reserved IP addresses are blocked.")
    return [str(address) for address in addresses]


def validate_target_url(url: str) -> tuple[str, list[str]]:
    """Require an exact allowlisted public host and return its canonical URL and IPs.

    Every DNS answer must be globally routable. Callers must disable redirects so an
    approved host cannot redirect the request to a different destination.
    """
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise TargetRejected("Enter a valid target URL (up to 2048 characters).")
    try:
        parsed = urlsplit(url.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise TargetRejected("The target URL is malformed.") from exc
    if parsed.scheme not in {"https", "http"} or not host:
        raise TargetRejected("Target URLs must include an http:// or https:// scheme and a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise TargetRejected("Credentials embedded in target URLs are blocked. Use a request header instead.")
    if parsed.query:
        raise TargetRejected("Query values are not allowed in the target base URL. Add them in the query parameters field instead.")
    if parsed.fragment:
        raise TargetRejected("URL fragments are not sent to APIs and are not allowed in a target URL.")
    if parsed.scheme == "http" and os.getenv("TESTPILOT_ALLOW_HTTP", "false").lower() not in {"1", "true", "yes"}:
        raise TargetRejected("HTTP targets are disabled. Use HTTPS or explicitly enable TESTPILOT_ALLOW_HTTP for a trusted test environment.")

    try:
        canonical_host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise TargetRejected("The target hostname is invalid.") from exc
    permitted = allowed_hosts()
    if not permitted:
        raise TargetRejected("No test targets are enabled. Add the exact hostname to TESTPILOT_ALLOWED_HOSTS first.")
    if canonical_host not in permitted:
        raise TargetRejected(f"Target host '{canonical_host}' is not in TESTPILOT_ALLOWED_HOSTS.")

    effective_port = port or (443 if parsed.scheme == "https" else 80)
    if effective_port not in ({443} if parsed.scheme == "https" else {80}):
        raise TargetRejected("Only the standard HTTPS port 443 or HTTP port 80 is allowed.")
    addresses = _public_addresses(canonical_host, effective_port)
    rendered_host = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    canonical = f"{parsed.scheme}://{rendered_host}"
    if port:
        canonical += f":{port}"
    canonical += parsed.path.rstrip("/")
    return canonical, addresses

