"""
P2P Message Protocol — DS-P2P-01

Defines the message types, formats, and builders for Lucie ↔ Mobile
communication. All messages are JSON-serializable and designed to be
encrypted with AES-256-GCM before transmission.

Message flow:
  1. hello → hello_ack (X25519 key exchange)
  2. auth → auth_ok/auth_fail (challenge-response)
  3. order_pending → order_approve/order_reject (business logic)
  4. ping/pong (keepalive)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(Enum):
    """All P2P message types."""

    # Handshake
    HELLO = "hello"
    HELLO_ACK = "hello_ack"
    AUTH = "auth"
    AUTH_OK = "auth_ok"
    AUTH_FAIL = "auth_fail"

    # Order lifecycle
    ORDER_PENDING = "order_pending"
    ORDER_APPROVE = "order_approve"
    ORDER_REJECT = "order_reject"
    ORDER_EXECUTED = "order_executed"
    ORDER_EXPIRED = "order_expired"
    ORDER_FAILED = "order_failed"

    # Utility
    STATUS_REQUEST = "status_request"
    STATUS_RESPONSE = "status_response"
    PING = "ping"
    PONG = "pong"
    DISCONNECT = "disconnect"


@dataclass
class P2PMessage:
    """
    A single P2P message exchanged between Lucie and mobile companion.

    Attributes:
        type: MessageType enum value
        payload: Dictionary of message-specific data
        message_id: Unique identifier (UUID4)
        timestamp: Unix timestamp of creation
    """

    type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "type": self.type.value,
            "payload": self.payload,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> P2PMessage:
        """
        Deserialize from JSON string.

        Args:
            data: JSON string

        Returns:
            P2PMessage instance

        Raises:
            ValueError: If JSON is invalid or type is unknown
        """
        try:
            d = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        msg_type_str = d.get("type")
        if not msg_type_str:
            raise ValueError("Missing 'type' field")

        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            raise ValueError(f"Unknown message type: {msg_type_str}")

        return cls(
            type=msg_type,
            payload=d.get("payload", {}),
            message_id=d.get("message_id", str(uuid.uuid4())),
            timestamp=d.get("timestamp", time.time()),
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> P2PMessage:
        """Deserialize from dictionary."""
        return cls(
            type=MessageType(d["type"]),
            payload=d.get("payload", {}),
            message_id=d.get("message_id", str(uuid.uuid4())),
            timestamp=d.get("timestamp", time.time()),
        )


class P2PProtocol:
    """
    Stateless message builder/parser for the Lucie P2P protocol.

    All methods are static — no state is held.
    """

    @staticmethod
    def build_hello(pubkey_hex: str, device_name: str) -> P2PMessage:
        """Build a HELLO message (client → server)."""
        return P2PMessage(
            type=MessageType.HELLO,
            payload={"pubkey": pubkey_hex, "device_name": device_name},
        )

    @staticmethod
    def build_hello_ack(
        pubkey_hex: str, session_id: str, challenge: str
    ) -> P2PMessage:
        """Build a HELLO_ACK message (server → client)."""
        return P2PMessage(
            type=MessageType.HELLO_ACK,
            payload={
                "pubkey": pubkey_hex,
                "session_id": session_id,
                "challenge": challenge,
            },
        )

    @staticmethod
    def build_auth(challenge_response: str) -> P2PMessage:
        """Build an AUTH message (client → server, encrypted)."""
        return P2PMessage(
            type=MessageType.AUTH,
            payload={"challenge_response": challenge_response},
        )

    @staticmethod
    def build_auth_ok() -> P2PMessage:
        """Build an AUTH_OK message (server → client, encrypted)."""
        return P2PMessage(type=MessageType.AUTH_OK)

    @staticmethod
    def build_auth_fail(reason: str = "Invalid challenge response") -> P2PMessage:
        """Build an AUTH_FAIL message (server → client)."""
        return P2PMessage(
            type=MessageType.AUTH_FAIL,
            payload={"reason": reason},
        )

    @staticmethod
    def build_order_pending(order_dict: Dict[str, Any]) -> P2PMessage:
        """
        Build an ORDER_PENDING message (server → client, encrypted).

        Args:
            order_dict: Order details including order_id, symbol, side,
                        quantity, price_eur, total_eur, timeout_s
        """
        return P2PMessage(
            type=MessageType.ORDER_PENDING,
            payload=order_dict,
        )

    @staticmethod
    def build_order_approve(order_id: str, token: str) -> P2PMessage:
        """Build an ORDER_APPROVE message (client → server, encrypted)."""
        return P2PMessage(
            type=MessageType.ORDER_APPROVE,
            payload={"order_id": order_id, "token": token},
        )

    @staticmethod
    def build_order_reject(
        order_id: str, token: str, reason: str = ""
    ) -> P2PMessage:
        """Build an ORDER_REJECT message (client → server, encrypted)."""
        return P2PMessage(
            type=MessageType.ORDER_REJECT,
            payload={"order_id": order_id, "token": token, "reason": reason},
        )

    @staticmethod
    def build_order_executed(order_id: str, result: Dict[str, Any]) -> P2PMessage:
        """Build an ORDER_EXECUTED message (server → client, encrypted)."""
        return P2PMessage(
            type=MessageType.ORDER_EXECUTED,
            payload={"order_id": order_id, "result": result},
        )

    @staticmethod
    def build_order_expired(order_id: str) -> P2PMessage:
        """Build an ORDER_EXPIRED message (server → client, encrypted)."""
        return P2PMessage(
            type=MessageType.ORDER_EXPIRED,
            payload={"order_id": order_id},
        )

    @staticmethod
    def build_order_failed(order_id: str, error: str) -> P2PMessage:
        """Build an ORDER_FAILED message (server → client, encrypted)."""
        return P2PMessage(
            type=MessageType.ORDER_FAILED,
            payload={"order_id": order_id, "error": error},
        )

    @staticmethod
    def build_status_request() -> P2PMessage:
        """Build a STATUS_REQUEST message (client → server, encrypted)."""
        return P2PMessage(type=MessageType.STATUS_REQUEST)

    @staticmethod
    def build_status_response(status: Dict[str, Any]) -> P2PMessage:
        """Build a STATUS_RESPONSE message (server → client, encrypted)."""
        return P2PMessage(
            type=MessageType.STATUS_RESPONSE,
            payload=status,
        )

    @staticmethod
    def build_ping() -> P2PMessage:
        """Build a PING message."""
        return P2PMessage(type=MessageType.PING)

    @staticmethod
    def build_pong() -> P2PMessage:
        """Build a PONG message."""
        return P2PMessage(type=MessageType.PONG)

    @staticmethod
    def build_disconnect(reason: str = "") -> P2PMessage:
        """Build a DISCONNECT message."""
        return P2PMessage(
            type=MessageType.DISCONNECT,
            payload={"reason": reason},
        )

    @staticmethod
    def parse(raw: str) -> P2PMessage:
        """
        Parse a raw JSON string into a P2PMessage.

        Alias for P2PMessage.from_json().

        Args:
            raw: JSON string

        Returns:
            P2PMessage instance
        """
        return P2PMessage.from_json(raw)
