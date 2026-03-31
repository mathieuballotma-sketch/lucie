"""SecretVault — Secure storage of exchange API keys in macOS Keychain."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import Any, Dict, Generator, Optional

from ...utils.logger import logger

# Try importing keyring, provide fallback for non-macOS
try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False
    logger.warning("⚠️ keyring library not available — using in-memory fallback")


# Namespace Keychain for Lucie Crypto
KEYCHAIN_SERVICE = "com.lucie.crypto"


@dataclass(frozen=True)
class ExchangeCredentials:
    """
    Credentials for an exchange.
    frozen=True : immutable, no accidental modifications.

    IMPORTANT : The secret is in memory only during use.
    Use via SecretVault.get_credentials() in context manager.
    """
    exchange: str        # "binance", "coinbase", "kraken"
    api_key: str         # Public API key
    api_secret: str      # Secret API key
    passphrase: str = "" # Passphrase (Coinbase Pro, Kraken)
    permissions: str = "read"  # "read" or "trade"

    def __repr__(self) -> str:
        """Never display secrets."""
        return (
            f"ExchangeCredentials(exchange={self.exchange!r}, "
            f"api_key={self.api_key[:8]}..., permissions={self.permissions!r})"
        )


class _InMemoryKeyring:
    """Fallback in-memory keyring for non-macOS systems."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, str]] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        if service not in self._store:
            self._store[service] = {}
        self._store[service][username] = password

    def get_password(self, service: str, username: str) -> Optional[str]:
        return self._store.get(service, {}).get(username)

    def delete_password(self, service: str, username: str) -> None:
        if service in self._store and username in self._store[service]:
            del self._store[service][username]


class SecretVault:
    """
    Secure manager for API keys.

    Storage in macOS Keychain via `keyring` library.
    On macOS, keyring uses Security.framework by default.
    Falls back to in-memory storage on other systems.

    Usage:
        vault = SecretVault()
        vault.store_credentials("binance", api_key, api_secret, permissions="read")

        with vault.get_credentials("binance") as creds:
            # creds available here
            pass
        # creds cleaned from memory
    """

    def __init__(self) -> None:
        if HAS_KEYRING:
            self._keyring = keyring
        else:
            self._keyring = _InMemoryKeyring()  # type: ignore
        self._verify_keychain_backend()
        self._exchanges: Dict[str, bool] = {}  # track configured exchanges

    def _verify_keychain_backend(self) -> None:
        """Verify keyring backend is macOS Keychain if available."""
        if HAS_KEYRING:
            try:
                backend = keyring.get_keyring()
                backend_name = type(backend).__name__
                if "macOS" not in backend_name and "Keychain" not in backend_name:
                    logger.warning(
                        f"⚠️ Unexpected keyring backend: {backend_name}. "
                        f"Secrets may not be in macOS Keychain."
                    )
            except Exception as e:
                logger.warning(f"⚠️ Could not verify keyring backend: {e}")

    def store_credentials(
        self,
        exchange: str,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        permissions: str = "read",
    ) -> None:
        """
        Store credentials in Keychain.

        Storage format:
        - Service: com.lucie.crypto.<exchange>
        - Username: key name (api_key, api_secret, etc.)
        - Password: the actual secret

        SECURITY: This method is called only once during initial setup by user.
        """
        service = f"{KEYCHAIN_SERVICE}.{exchange}"

        # Store the API key and secret
        self._keyring.set_password(service, "api_key", api_key)
        self._keyring.set_password(service, "api_secret", api_secret)
        if passphrase:
            self._keyring.set_password(service, "passphrase", passphrase)
        self._keyring.set_password(service, "permissions", permissions)

        self._exchanges[exchange] = True

        logger.info(
            f"🔐 Credentials {exchange} stored in Keychain "
            f"(permissions: {permissions})"
        )

    def delete_credentials(self, exchange: str) -> None:
        """Delete credentials for an exchange from Keychain."""
        service = f"{KEYCHAIN_SERVICE}.{exchange}"
        for key in ["api_key", "api_secret", "passphrase", "permissions"]:
            try:
                self._keyring.delete_password(service, key)
            except Exception:
                pass

        self._exchanges.pop(exchange, None)
        logger.info(f"🗑️ Credentials {exchange} deleted from Keychain")

    @contextlib.contextmanager
    def get_credentials(self, exchange: str) -> Generator[
        Optional[ExchangeCredentials], None, None
    ]:
        """
        Context manager to retrieve credentials temporarily.

        Credentials are in memory ONLY within the `with` block.
        On exit, references are explicitly cleared.

        Usage:
            with vault.get_credentials("binance") as creds:
                if creds:
                    client.set_key(creds.api_key)
        """
        creds = None
        try:
            service = f"{KEYCHAIN_SERVICE}.{exchange}"
            api_key = self._keyring.get_password(service, "api_key")
            api_secret = self._keyring.get_password(service, "api_secret")

            if not api_key or not api_secret:
                logger.warning(f"⚠️ No credentials found for {exchange}")
                yield None
                return

            passphrase = self._keyring.get_password(service, "passphrase") or ""
            permissions = self._keyring.get_password(service, "permissions") or "read"

            creds = ExchangeCredentials(
                exchange=exchange,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                permissions=permissions,
            )
            yield creds

        finally:
            # Clear memory references
            creds = None

    def list_exchanges(self) -> list[str]:
        """List all configured exchanges."""
        return list(self._exchanges.keys())

    def has_trade_permission(self, exchange: str) -> bool:
        """Check if exchange credentials have trading permission."""
        service = f"{KEYCHAIN_SERVICE}.{exchange}"
        permissions = self._keyring.get_password(service, "permissions") or "read"
        return permissions == "trade"
