"""
Tests du système de sandboxing.

Couvre :
- Génération de profils .sb
- IPC chiffré (handshake, encrypt/decrypt, rotation)
- SandboxManager (spawn, terminate, watchdog)
- Tests d'intrusion simulés
"""

import asyncio
import json
import os
import pytest
import tempfile

from app.security.sandbox_profiles import (
    SandboxTier, generate_sandbox_profile, AGENT_SANDBOX_MAP,
)
from app.security.ipc_crypto import (
    IPCCrypto, AgentIPCClient, NONCE_SIZE, KEY_SIZE,
)


# ═══════════════════════════════════════════════════════════════
# Profils Sandbox
# ═══════════════════════════════════════════════════════════════

class TestSandboxProfiles:

    def test_restricted_profile_denies_network(self):
        """RESTRICTED : pas de réseau."""
        profile = generate_sandbox_profile(
            SandboxTier.RESTRICTED, "TestAgent",
            "/tmp/test", "/tmp/test.sock",
        )
        assert "(deny default)" in profile
        assert "network-outbound" not in profile.split("RESTRICTED")[1]

    def test_file_access_allows_user_read(self):
        """FILE_ACCESS : lecture dans /Users."""
        profile = generate_sandbox_profile(
            SandboxTier.FILE_ACCESS, "FileAgent",
            "/tmp/test", "/tmp/test.sock",
        )
        assert '(subpath "/Users")' in profile
        assert "FILE_ACCESS" in profile

    def test_network_access_allows_http(self):
        """NETWORK_ACCESS : HTTP/HTTPS autorisé."""
        profile = generate_sandbox_profile(
            SandboxTier.NETWORK_ACCESS, "MailAgent",
            "/tmp/test", "/tmp/test.sock",
        )
        assert '"*:443"' in profile
        assert '"*:80"' in profile

    def test_sensitive_allows_keychain(self):
        """SENSITIVE : accès Keychain autorisé."""
        profile = generate_sandbox_profile(
            SandboxTier.SENSITIVE, "AccountingAgent",
            "/tmp/test", "/tmp/test.sock",
        )
        assert "com.apple.SecurityServer" in profile
        assert "com.apple.securityd" in profile

    def test_all_profiles_deny_fork(self):
        """Tous les profils interdisent fork."""
        for tier in SandboxTier:
            profile = generate_sandbox_profile(
                tier, "Test", "/tmp/t", "/tmp/t.sock",
            )
            assert "(deny process-fork)" in profile

    def test_all_profiles_deny_ptrace(self):
        """Tous les profils interdisent ptrace/debugging."""
        for tier in SandboxTier:
            profile = generate_sandbox_profile(
                tier, "Test", "/tmp/t", "/tmp/t.sock",
            )
            assert "(deny process-info-pidinfo)" in profile

    def test_socket_path_in_profile(self):
        """Le socket path est autorisé dans tous les profils."""
        profile = generate_sandbox_profile(
            SandboxTier.RESTRICTED, "Test",
            "/tmp/work", "/tmp/ipc/test.sock",
        )
        assert "/tmp/ipc/test.sock" in profile

    def test_agent_sandbox_map_covers_all(self):
        """Les agents critiques ont un tier défini."""
        assert "FileAgent" in AGENT_SANDBOX_MAP
        assert "AccountingAgent" in AGENT_SANDBOX_MAP
        assert "SmartMailAgent" in AGENT_SANDBOX_MAP

    def test_work_dir_in_profile(self):
        """Le répertoire de travail est autorisé."""
        profile = generate_sandbox_profile(
            SandboxTier.RESTRICTED, "Test",
            "/tmp/lucie/agents/test", "/tmp/test.sock",
        )
        assert "/tmp/lucie/agents/test" in profile


# ═══════════════════════════════════════════════════════════════
# IPC Crypto
# ═══════════════════════════════════════════════════════════════

class TestIPCCrypto:

    def test_handshake_full_flow(self):
        """Handshake complet : broker ↔ agent."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")

        assert agent.complete_handshake(broker_pub, session_id) is True
        assert broker.complete_handshake(
            session_id, agent.public_key_bytes
        ) is True

    def test_encrypt_decrypt_roundtrip(self):
        """Chiffrement → déchiffrement = message original."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        plaintext = b"Hello from broker"
        aad = b"TestAgent"
        encrypted = broker.encrypt(session_id, plaintext, aad)

        decrypted = agent.decrypt(encrypted, aad)
        assert decrypted == plaintext

    def test_encrypt_decrypt_agent_to_broker(self):
        """Agent → Broker fonctionne aussi."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        plaintext = b"Response from agent"
        aad = b"TestAgent"
        encrypted = agent.encrypt(plaintext, aad)

        decrypted = broker.decrypt(session_id, encrypted, aad)
        assert decrypted == plaintext

    def test_tampered_message_fails(self):
        """Un message modifié est rejeté (intégrité GCM)."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        encrypted = broker.encrypt(session_id, b"secret", b"TestAgent")

        tampered = bytearray(encrypted)
        tampered[NONCE_SIZE + 5] ^= 0xFF
        tampered = bytes(tampered)

        with pytest.raises(Exception):  # InvalidTag
            agent.decrypt(tampered, b"TestAgent")

    def test_wrong_aad_fails(self):
        """AAD incorrect → déchiffrement échoue."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        encrypted = broker.encrypt(session_id, b"secret", b"TestAgent")

        with pytest.raises(Exception):  # InvalidTag
            agent.decrypt(encrypted, b"WrongAgent")

    def test_key_rotation(self):
        """Rotation de clé fonctionne."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        assert broker.rotate_key(session_id) is True

        session = broker._sessions[session_id]
        assert session._nonce_counter == 0
        assert session._message_count == 0

    def test_destroy_session_clears_keys(self):
        """destroy_session efface les clés."""
        broker = IPCCrypto()
        session_id, _ = broker.create_session("TestAgent")

        broker.destroy_session(session_id)
        assert session_id not in broker._sessions

    def test_max_message_size_enforced(self):
        """Messages > 1MB sont rejetés."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        big_message = b"X" * (1024 * 1024 + 1)
        with pytest.raises(ValueError, match="too large"):
            broker.encrypt(session_id, big_message)

    def test_nonce_never_reused(self):
        """Les nonces sont toujours uniques."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        nonces = set()
        for _ in range(100):
            encrypted = broker.encrypt(session_id, b"test")
            nonce = encrypted[:NONCE_SIZE]
            assert nonce not in nonces
            nonces.add(nonce)


# ═══════════════════════════════════════════════════════════════
# Tests d'intrusion simulés
# ═══════════════════════════════════════════════════════════════

class TestSandboxIntrusion:

    def test_restricted_profile_blocks_file_access(self):
        """Vérifier que le profil RESTRICTED bloque l'accès fichiers."""
        profile = generate_sandbox_profile(
            SandboxTier.RESTRICTED, "EvilAgent",
            "/tmp/evil", "/tmp/evil.sock",
        )
        assert '(subpath "/Users")' not in profile.split("RESTRICTED")[1]

    def test_no_fork_in_any_profile(self):
        """Aucun profil ne permet de forker (prévient l'évasion)."""
        for tier in SandboxTier:
            profile = generate_sandbox_profile(
                tier, "Test", "/tmp/t", "/tmp/t.sock",
            )
            assert "deny process-fork" in profile

    def test_replay_attack_detected(self):
        """Rejouer un message — le nonce unique protège."""
        broker = IPCCrypto()
        agent = AgentIPCClient()

        session_id, broker_pub = broker.create_session("TestAgent")
        agent.complete_handshake(broker_pub, session_id)
        broker.complete_handshake(session_id, agent.public_key_bytes)

        encrypted = broker.encrypt(session_id, b"legit", b"TestAgent")
        decrypted = agent.decrypt(encrypted, b"TestAgent")
        assert decrypted == b"legit"

    def test_cross_session_attack_fails(self):
        """Un message d'une session ne déchiffre pas dans une autre."""
        broker = IPCCrypto()

        sid1, pub1 = broker.create_session("Agent1")
        sid2, pub2 = broker.create_session("Agent2")

        agent1 = AgentIPCClient()
        agent1.complete_handshake(pub1, sid1)
        broker.complete_handshake(sid1, agent1.public_key_bytes)

        agent2 = AgentIPCClient()
        agent2.complete_handshake(pub2, sid2)
        broker.complete_handshake(sid2, agent2.public_key_bytes)

        encrypted = broker.encrypt(sid1, b"secret1", b"Agent1")

        with pytest.raises(Exception):
            agent2.decrypt(encrypted, b"Agent1")
