import socket
from unittest.mock import patch

import pytest

from app.security import TargetRejected, validate_target_url
from app.security import PinnedResolver


def dns_answer(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def test_no_targets_allowed_by_default(monkeypatch):
    monkeypatch.delenv("TESTPILOT_ALLOWED_HOSTS", raising=False)
    with pytest.raises(TargetRejected, match="No test targets are enabled"):
        validate_target_url("https://api.example.com")


def test_host_must_match_allowlist_exactly(monkeypatch):
    monkeypatch.setenv("TESTPILOT_ALLOWED_HOSTS", "api.example.com")
    with pytest.raises(TargetRejected, match="not in TESTPILOT_ALLOWED_HOSTS"):
        validate_target_url("https://example.com")


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1"])
def test_blocks_private_or_local_dns_answers(monkeypatch, ip):
    monkeypatch.setenv("TESTPILOT_ALLOWED_HOSTS", "api.example.com")
    with patch("app.security.socket.getaddrinfo", return_value=dns_answer(ip)):
        with pytest.raises(TargetRejected, match="private, local, or reserved"):
            validate_target_url("https://api.example.com")


def test_accepts_only_public_dns_answers(monkeypatch):
    monkeypatch.setenv("TESTPILOT_ALLOWED_HOSTS", "API.EXAMPLE.COM")
    with patch("app.security.socket.getaddrinfo", return_value=dns_answer("93.184.216.34")):
        url, ips = validate_target_url("https://api.example.com/v1/")
    assert url == "https://api.example.com/v1"
    assert ips == ["93.184.216.34"]


def test_blocks_embedded_credentials(monkeypatch):
    monkeypatch.setenv("TESTPILOT_ALLOWED_HOSTS", "api.example.com")
    with pytest.raises(TargetRejected, match="Credentials embedded"):
        validate_target_url("https://user:secret@api.example.com")


def test_blocks_nonstandard_ports(monkeypatch):
    monkeypatch.setenv("TESTPILOT_ALLOWED_HOSTS", "api.example.com")
    with pytest.raises(TargetRejected, match="standard HTTPS port"):
        validate_target_url("https://api.example.com:8443")


def test_blocks_target_base_query_string(monkeypatch):
    monkeypatch.setenv("TESTPILOT_ALLOWED_HOSTS", "api.example.com")
    with pytest.raises(TargetRejected, match="Query values are not allowed"):
        validate_target_url("https://api.example.com?api_key=secret")


def test_pinned_resolver_is_bound_to_a_single_public_ip():
    resolver = PinnedResolver("api.example.com", "93.184.216.34")
    assert resolver.hostname == "api.example.com"
    assert resolver.address == "93.184.216.34"
