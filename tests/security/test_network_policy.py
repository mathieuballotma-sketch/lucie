"""Tests unitaires — NetworkPolicy + décorateur @network_restricted (SEC-QW-02)."""

import textwrap
from pathlib import Path

import pytest

from app.security.network_policy import (
    NetworkPolicy,
    NetworkPolicyViolation,
    network_restricted,
    _host_matches,
    _parse_target,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_policy(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "network_policies.yaml"
    f.write_text(textwrap.dedent(content), encoding="utf-8")
    return f


_SAMPLE_YAML = """
    policies:
      default:
        allow_localhost: true
        allow_ollama: true
        allowed_hosts: []
        allowed_ports: []
      strict_agent:
        allow_localhost: false
        allow_ollama: false
        allowed_hosts:
          - "api.example.com"
          - "*.trusted.org"
        allowed_ports: [443]
      open_agent:
        allow_localhost: true
        allow_ollama: true
        allowed_hosts:
          - "anything.com"
        allowed_ports: []
"""


# ---------------------------------------------------------------------------
# _host_matches
# ---------------------------------------------------------------------------

class TestHostMatches:
    def test_exact_match(self):
        assert _host_matches("example.com", "example.com")

    def test_no_match(self):
        assert not _host_matches("evil.com", "example.com")

    def test_wildcard_subdomain(self):
        assert _host_matches("api.trusted.org", "*.trusted.org")

    def test_wildcard_root_also_matches(self):
        assert _host_matches("trusted.org", "*.trusted.org")

    def test_wildcard_no_match_different_domain(self):
        assert not _host_matches("api.evil.org", "*.trusted.org")

    def test_case_insensitive(self):
        assert _host_matches("API.EXAMPLE.COM", "api.example.com")


# ---------------------------------------------------------------------------
# _parse_target
# ---------------------------------------------------------------------------

class TestParseTarget:
    def test_https_url(self):
        host, port = _parse_target("https://api.example.com/data", None)
        assert host == "api.example.com"
        assert port == 443

    def test_http_url_explicit_port(self):
        host, port = _parse_target("http://localhost:8080/path", None)
        assert host == "localhost"
        assert port == 8080

    def test_bare_host(self):
        host, port = _parse_target("example.com", None)
        assert host == "example.com"
        assert port is None

    def test_host_with_port(self):
        host, port = _parse_target("example.com:9000", None)
        assert host == "example.com"
        assert port == 9000

    def test_explicit_port_used_when_url_has_no_port(self):
        # https://example.com n'a pas de port explicite dans l'URL → explicit_port utilisé
        host, port = _parse_target("https://example.com", 8443)
        assert port == 8443


# ---------------------------------------------------------------------------
# NetworkPolicy.check_access — politique default
# ---------------------------------------------------------------------------

class TestNetworkPolicyDefault:
    def setup_method(self):
        self.policy = NetworkPolicy(
            agent_name="test_agent",
            rules={"allow_localhost": True, "allow_ollama": True, "allowed_hosts": [], "allowed_ports": []},
        )

    def test_localhost_allowed(self):
        self.policy.check_access("http://localhost/api")  # no raise

    def test_127_allowed(self):
        self.policy.check_access("http://127.0.0.1:8000/")  # no raise

    def test_ollama_allowed(self):
        self.policy.check_access("http://localhost:11434/api/generate")  # no raise

    def test_external_denied(self):
        with pytest.raises(NetworkPolicyViolation):
            self.policy.check_access("https://google.com")

    def test_is_allowed_returns_false(self):
        assert not self.policy.is_allowed("https://evil.com")

    def test_is_allowed_returns_true(self):
        assert self.policy.is_allowed("http://localhost:8000")


# ---------------------------------------------------------------------------
# NetworkPolicy.for_agent — chargement YAML
# ---------------------------------------------------------------------------

class TestNetworkPolicyForAgent:
    def test_strict_agent_blocks_external(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)
        policy = NetworkPolicy.for_agent("strict_agent", policies_file=pf)
        with pytest.raises(NetworkPolicyViolation):
            policy.check_access("https://untrusted.com")

    def test_strict_agent_allows_listed_host(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)
        policy = NetworkPolicy.for_agent("strict_agent", policies_file=pf)
        policy.check_access("https://api.example.com/endpoint")  # no raise

    def test_strict_agent_allows_wildcard(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)
        policy = NetworkPolicy.for_agent("strict_agent", policies_file=pf)
        policy.check_access("https://sub.trusted.org/path")  # no raise

    def test_strict_agent_blocks_localhost(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)
        policy = NetworkPolicy.for_agent("strict_agent", policies_file=pf)
        with pytest.raises(NetworkPolicyViolation):
            policy.check_access("http://localhost:8000")

    def test_unknown_agent_falls_back_to_default(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)
        policy = NetworkPolicy.for_agent("unknown_agent", policies_file=pf)
        # default allows localhost
        policy.check_access("http://localhost")  # no raise

    def test_missing_file_uses_deny_all(self, tmp_path):
        policy = NetworkPolicy.for_agent("anything", policies_file=tmp_path / "nope.yaml")
        with pytest.raises(NetworkPolicyViolation):
            policy.check_access("https://example.com")


# ---------------------------------------------------------------------------
# Décorateur @network_restricted
# ---------------------------------------------------------------------------

class TestNetworkRestrictedDecorator:
    def test_blocked_url_raises_before_function(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)
        called = []

        @network_restricted("strict_agent", policies_file=pf)
        def fetch(url: str) -> str:
            called.append(url)
            return "response"

        with pytest.raises(NetworkPolicyViolation):
            fetch("https://evil.com/steal")
        assert called == [], "La fonction ne doit pas être appelée si l'URL est bloquée"

    def test_allowed_url_calls_function(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)

        @network_restricted("strict_agent", policies_file=pf)
        def fetch(url: str) -> str:
            return "ok"

        result = fetch("https://api.example.com/data")
        assert result == "ok"

    def test_no_url_arg_passes_through(self, tmp_path):
        """Quand aucune URL n'est détectée, la fonction s'exécute sans vérification."""
        pf = _write_policy(tmp_path, _SAMPLE_YAML)

        @network_restricted("strict_agent", policies_file=pf)
        def process(data: dict) -> str:
            return "processed"

        assert process({"key": "value"}) == "processed"

    def test_policy_attached_to_wrapper(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)

        @network_restricted("strict_agent", policies_file=pf)
        def dummy() -> None:
            pass

        assert hasattr(dummy, "_network_policy")
        assert dummy._network_policy.agent_name == "strict_agent"

    def test_custom_url_arg_name(self, tmp_path):
        pf = _write_policy(tmp_path, _SAMPLE_YAML)

        @network_restricted("strict_agent", policies_file=pf, url_arg="endpoint")
        def call(endpoint: str) -> str:
            return "called"

        with pytest.raises(NetworkPolicyViolation):
            call(endpoint="https://evil.com")
