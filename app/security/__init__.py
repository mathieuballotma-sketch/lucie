"""Package sécurité Lucie — OWASP Top 10 LLM 2025."""

from .sandbox_profiles import SandboxTier, AGENT_SANDBOX_MAP
from .ipc_crypto import IPCCrypto, AgentIPCClient
from .sandbox_manager import SandboxManager
from .secure_storage import SecureStorage
from .exfiltration_detector import ExfiltrationDetector, ExfiltrationConfig
from .memory_protection import (
    SecureBuffer, SecureMemoryBuffer, SecretsScanner, ProcessMemoryGuard,
    lock_memory, unlock_memory, secure_wipe,
)
from .integrity_monitor import IntegrityMonitor, CodeSignatureVerifier
from .security_response import SecurityResponseEngine, SecurityEvent, SecuritySeverity, ResponseAction

__all__ = [
    # SEC-01: Sandboxing + IPC
    "SandboxTier",
    "AGENT_SANDBOX_MAP",
    "IPCCrypto",
    "AgentIPCClient",
    "SandboxManager",
    # SEC-02: Encryption at rest + Exfiltration
    "SecureStorage",
    "ExfiltrationDetector",
    "ExfiltrationConfig",
    # SEC-03: Memory & Secrets Protection
    "SecureBuffer",
    "SecureMemoryBuffer",
    "SecretsScanner",
    "ProcessMemoryGuard",
    "lock_memory",
    "unlock_memory",
    "secure_wipe",
    # SEC-04: Integrity Monitor
    "IntegrityMonitor",
    "CodeSignatureVerifier",
    # SEC-05: Automated Security Response
    "SecurityResponseEngine",
    "SecurityEvent",
    "SecuritySeverity",
    "ResponseAction",
]
