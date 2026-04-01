"""
SEC-QW-02 : Politique réseau par agent.

Chaque agent ne peut accéder qu'aux ressources réseau explicitement
autorisées dans config/network_policies.yaml (ou app/security/network_policies.yaml).
Le décorateur @network_restricted intercepte toute tentative d'accès
réseau avant l'exécution de la fonction décorée.

Politique par défaut : tout bloqué sauf localhost / Ollama.
"""

from __future__ import annotations

import functools
import logging
import re
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

try:
    import yaml  # type: ignore[import-untyped]
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

# Chemin par défaut de la configuration réseau
_DEFAULT_POLICIES_FILE = Path(__file__).parent / "network_policies.yaml"

# Politique "deny-all" appliquée quand aucune règle spécifique n'existe
_DENY_ALL_POLICY: dict = {
    "allowed_hosts": [],
    "allowed_ports": [],
    "allow_localhost": True,
    "allow_ollama": True,
}

# Ports / hôtes Ollama par défaut
_OLLAMA_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_OLLAMA_PORTS = {11434}
_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}


class NetworkPolicyViolation(PermissionError):
    """Levée quand un agent tente d'accéder à une ressource non autorisée."""


class NetworkPolicy:
    """
    Définit et vérifie les droits réseau d'un agent donné.

    Les politiques sont chargées depuis un fichier YAML structuré ainsi ::

        policies:
          default:
            allow_localhost: true
            allow_ollama: true
            allowed_hosts: []
            allowed_ports: []
          accounting_agent:
            allow_localhost: true
            allow_ollama: true
            allowed_hosts:
              - "api.impots.gouv.fr"
            allowed_ports: [443]

    Utilisation ::

        policy = NetworkPolicy.for_agent("accounting_agent")
        policy.check_access("https://api.impots.gouv.fr/endpoint")  # OK
        policy.check_access("https://evil.com/steal")               # raise

    Ou via le décorateur ::

        @network_restricted("accounting_agent")
        def fetch_tax_data(url: str) -> dict:
            ...
    """

    def __init__(self, agent_name: str, rules: dict) -> None:
        self.agent_name = agent_name
        self.allow_localhost: bool = rules.get("allow_localhost", True)
        self.allow_ollama: bool = rules.get("allow_ollama", True)
        self.allowed_hosts: list[str] = [h.lower() for h in rules.get("allowed_hosts", [])]
        self.allowed_ports: set[int] = set(rules.get("allowed_ports", []))

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def for_agent(
        cls,
        agent_name: str,
        policies_file: Optional[Path] = None,
    ) -> "NetworkPolicy":
        """Charge la politique réseau d'un agent depuis le fichier YAML."""
        file_path = Path(policies_file) if policies_file else _DEFAULT_POLICIES_FILE
        raw_policies = _load_policies_file(file_path)

        # Priorité : règle spécifique → règle default → deny-all interne
        if agent_name in raw_policies:
            rules = raw_policies[agent_name]
        elif "default" in raw_policies:
            rules = raw_policies["default"]
        else:
            rules = _DENY_ALL_POLICY

        return cls(agent_name=agent_name, rules=rules)

    # ------------------------------------------------------------------
    # Vérification d'accès
    # ------------------------------------------------------------------

    def check_access(self, url_or_host: str, port: Optional[int] = None) -> None:
        """
        Vérifie si l'accès réseau est autorisé.

        :param url_or_host: URL complète (``https://host/path``) ou nom d'hôte nu.
        :param port: Port explicite (ignoré si déjà présent dans l'URL).
        :raises NetworkPolicyViolation: si l'accès est refusé.
        """
        host, resolved_port = _parse_target(url_or_host, port)

        # 1. Localhost toujours autorisé si flag activé
        if self.allow_localhost and host in _LOCALHOST_HOSTS:
            return

        # 2. Ollama autorisé si flag activé
        if self.allow_ollama and host in _OLLAMA_HOSTS and (
            resolved_port is None or resolved_port in _OLLAMA_PORTS
        ):
            return

        # 3. Vérifier les hôtes explicitement autorisés (wildcard *.domain supporté)
        for allowed in self.allowed_hosts:
            if _host_matches(host, allowed):
                # Si des ports sont précisés, vérifier
                if self.allowed_ports and resolved_port is not None:
                    if resolved_port in self.allowed_ports:
                        return
                else:
                    return

        # 4. Accès refusé
        raise NetworkPolicyViolation(
            f"[NetworkPolicy] Agent '{self.agent_name}' : accès refusé vers "
            f"{host}:{resolved_port} — non autorisé par la politique réseau."
        )

    def is_allowed(self, url_or_host: str, port: Optional[int] = None) -> bool:
        """Version booléenne de check_access (ne lève pas d'exception)."""
        try:
            self.check_access(url_or_host, port)
            return True
        except NetworkPolicyViolation:
            return False


# ---------------------------------------------------------------------------
# Décorateur
# ---------------------------------------------------------------------------

def network_restricted(
    agent_name: str,
    policies_file: Optional[Path] = None,
    url_arg: str = "url",
) -> Callable:
    """
    Décorateur qui vérifie la politique réseau avant d'exécuter la fonction.

    ::

        @network_restricted("accounting_agent")
        def fetch(url: str) -> str:
            return requests.get(url).text

    Le décorateur cherche l'argument ``url`` (configurable via ``url_arg``)
    dans les kwargs ou le 1er positional argument.  Si l'URL est absente,
    aucune vérification n'est effectuée (utile pour fonctions qui construisent
    l'URL en interne — la vérification doit alors être faite manuellement).
    """

    def decorator(func: Callable) -> Callable:
        policy = NetworkPolicy.for_agent(agent_name, policies_file)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            target_url: Optional[str] = kwargs.get(url_arg)
            if target_url is None and args:
                target_url = args[0] if isinstance(args[0], str) else None

            if target_url is not None:
                policy.check_access(target_url)

            return func(*args, **kwargs)

        wrapper._network_policy = policy  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Helpers privés
# ---------------------------------------------------------------------------

def _load_policies_file(path: Path) -> dict:
    """Charge le fichier YAML de politiques ; retourne {} si absent/invalide."""
    if not path.exists():
        logger.debug("[NetworkPolicy] Fichier de politiques absent : %s", path)
        return {}
    if not _YAML_AVAILABLE:
        logger.error("[NetworkPolicy] PyYAML non installé — politiques ignorées.")
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("policies", data)
    except (yaml.YAMLError, OSError) as exc:
        logger.error("[NetworkPolicy] Erreur lecture %s : %s", path, exc)
        return {}


def _parse_target(url_or_host: str, explicit_port: Optional[int]) -> tuple[str, Optional[int]]:
    """Extrait (host, port) depuis une URL ou un nom d'hôte nu."""
    # Si ça ressemble à une URL complète
    if "://" in url_or_host or url_or_host.startswith("//"):
        parsed = urlparse(url_or_host if "://" in url_or_host else f"//{url_or_host}")
        host = (parsed.hostname or "").lower()
        port = parsed.port or explicit_port or _scheme_default_port(parsed.scheme)
    else:
        # Hôte nu, éventuellement avec port (host:port)
        if ":" in url_or_host and not url_or_host.startswith("["):
            parts = url_or_host.rsplit(":", 1)
            host = parts[0].lower()
            try:
                port = int(parts[1])
            except ValueError:
                port = explicit_port
        else:
            host = url_or_host.lower()
            port = explicit_port

    return host, port


def _scheme_default_port(scheme: str) -> Optional[int]:
    """Retourne le port par défaut pour un schéma courant."""
    return {"http": 80, "https": 443, "ftp": 21, "ws": 80, "wss": 443}.get(scheme)


def _host_matches(host: str, pattern: str) -> bool:
    """
    Vérifie si un hôte correspond à un pattern (wildcard *.domain supporté).

    Exemples ::

        _host_matches("api.example.com", "*.example.com")  → True
        _host_matches("example.com", "example.com")        → True
        _host_matches("evil.com", "example.com")           → False
    """
    host = host.lower()
    pattern = pattern.lower()
    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".example.com"
        return host == pattern[2:] or host.endswith(suffix)
    return host == pattern
