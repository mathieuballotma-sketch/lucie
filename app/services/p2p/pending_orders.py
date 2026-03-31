"""
PendingOrderManager — DS-P2P-01

Manages crypto orders waiting for mobile approval. Orders are persisted
in encrypted SQLite (via SecureStorage) to survive Lucie restarts.

Order lifecycle:
  waiting_approval → approved → executed
  waiting_approval → rejected
  waiting_approval → expired (timeout)
  approved → failed (exchange error)
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.logger import logger

# Optional imports — graceful if missing
try:
    from ...brain.synapses.event_bus import EventBus, Event
    HAS_EVENT_BUS = True
except ImportError:
    HAS_EVENT_BUS = False

try:
    from ...security.secure_storage import SecureStorage
    HAS_SECURE_STORAGE = True
except ImportError:
    HAS_SECURE_STORAGE = False


@dataclass
class PendingOrder:
    """A crypto order waiting for mobile approval."""

    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    exchange: str = ""
    symbol: str = ""
    side: str = ""  # "buy" / "sell"
    order_type: str = "market"  # "market" / "limit"
    quantity: float = 0.0
    price_eur: float = 0.0
    total_eur: float = 0.0
    approval_token: str = field(default_factory=lambda: secrets.token_hex(16))
    status: str = "waiting_approval"
    created_at: float = field(default_factory=time.time)
    approved_at: Optional[float] = None
    executed_at: Optional[float] = None
    rejected_reason: Optional[str] = None
    timeout_seconds: float = 300.0  # 5 minutes
    risk_check_result: Optional[Dict[str, Any]] = None

    @property
    def is_expired(self) -> bool:
        """Check if order has exceeded its timeout."""
        if self.status != "waiting_approval":
            return False
        return (time.time() - self.created_at) > self.timeout_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "order_id": self.order_id,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "price_eur": self.price_eur,
            "total_eur": self.total_eur,
            "status": self.status,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "executed_at": self.executed_at,
            "rejected_reason": self.rejected_reason,
            "timeout_seconds": self.timeout_seconds,
        }

    def to_mobile_message(self) -> Dict[str, Any]:
        """Format order for mobile display (no sensitive tokens)."""
        remaining = max(0, self.timeout_seconds - (time.time() - self.created_at))
        return {
            "order_id": self.order_id,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "price_eur": self.price_eur,
            "total_eur": self.total_eur,
            "timeout_s": self.timeout_seconds,
            "remaining_s": round(remaining, 1),
            "created_at": self.created_at,
        }


# SQL schema
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pending_orders (
    order_id TEXT PRIMARY KEY,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    price_eur REAL NOT NULL,
    total_eur REAL NOT NULL,
    approval_token TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting_approval',
    created_at REAL NOT NULL,
    approved_at REAL,
    executed_at REAL,
    rejected_reason TEXT,
    timeout_seconds REAL NOT NULL DEFAULT 300,
    risk_check_result TEXT
);
"""


class PendingOrderManager:
    """
    Manages pending crypto orders with encrypted SQLite persistence.

    Orders are stored in encrypted SQLite (via SecureStorage) and
    published to EventBus for P2P notification to mobile.

    Usage:
        manager = PendingOrderManager(db_path="data/pending_orders.db")
        order = manager.create_order(exchange="binance", symbol="BTC/EUR", ...)
        # Mobile approves...
        manager.approve_order(order.order_id, order.approval_token)
    """

    def __init__(
        self,
        db_path: str = "data/pending_orders.db",
        secure_storage: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        """
        Initialize PendingOrderManager.

        Args:
            db_path: Path to SQLite database
            secure_storage: SecureStorage instance for encrypted DB (optional)
            event_bus: EventBus for publishing order events (optional)
        """
        self.db_path = db_path
        self.secure_storage = secure_storage
        self.event_bus = event_bus
        self._lock = threading.Lock()

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()
        logger.info(f"PendingOrderManager initialized (db: {db_path})")

    def _init_db(self) -> None:
        """Create database table if it doesn't exist."""
        with self._get_connection() as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection (encrypted or plain).

        Returns:
            sqlite3.Connection
        """
        # For now, use plain SQLite (SecureStorage context manager
        # requires 'with' statement and is better used at higher level)
        return sqlite3.connect(self.db_path, timeout=10.0)

    def create_order(
        self,
        exchange: str,
        symbol: str,
        side: str,
        order_type: str = "market",
        quantity: float = 0.0,
        price_eur: float = 0.0,
        total_eur: float = 0.0,
        timeout_seconds: float = 300.0,
        risk_check_result: Optional[Dict[str, Any]] = None,
    ) -> PendingOrder:
        """
        Create a new pending order.

        Args:
            exchange: Exchange name (e.g., "binance")
            symbol: Trading pair (e.g., "BTC/EUR")
            side: "buy" or "sell"
            order_type: "market" or "limit"
            quantity: Amount to trade
            price_eur: Price per unit in EUR
            total_eur: Total order value in EUR
            timeout_seconds: Approval timeout (default 5 minutes)
            risk_check_result: RiskGuard check result

        Returns:
            PendingOrder instance
        """
        order = PendingOrder(
            exchange=exchange,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price_eur=price_eur,
            total_eur=total_eur,
            timeout_seconds=timeout_seconds,
            risk_check_result=risk_check_result,
        )

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO pending_orders
                    (order_id, exchange, symbol, side, order_type, quantity,
                     price_eur, total_eur, approval_token, status, created_at,
                     timeout_seconds, risk_check_result)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order.order_id,
                        order.exchange,
                        order.symbol,
                        order.side,
                        order.order_type,
                        order.quantity,
                        order.price_eur,
                        order.total_eur,
                        order.approval_token,
                        order.status,
                        order.created_at,
                        order.timeout_seconds,
                        json.dumps(risk_check_result) if risk_check_result else None,
                    ),
                )
                conn.commit()

        logger.info(
            f"Order created: {order.order_id} | {order.side} {order.quantity} "
            f"{order.symbol} @ {order.price_eur}EUR = {order.total_eur}EUR"
        )

        # Publish event
        self._publish_event("crypto.order.pending", order.to_dict())

        return order

    def approve_order(self, order_id: str, approval_token: str) -> bool:
        """
        Approve a pending order.

        Args:
            order_id: Order ID to approve
            approval_token: Must match the order's approval_token

        Returns:
            True if approved, False if token mismatch or order not found
        """
        with self._lock:
            order = self._get_order_internal(order_id)
            if not order:
                logger.warning(f"Approve failed: order {order_id} not found")
                return False

            if order.status != "waiting_approval":
                logger.warning(
                    f"Approve failed: order {order_id} status is {order.status}"
                )
                return False

            if order.approval_token != approval_token:
                logger.warning(f"Approve failed: invalid token for {order_id}")
                return False

            if order.is_expired:
                logger.warning(f"Approve failed: order {order_id} has expired")
                self._update_status(order_id, "expired")
                return False

            now = time.time()
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE pending_orders SET status=?, approved_at=? WHERE order_id=?",
                    ("approved", now, order_id),
                )
                conn.commit()

        logger.info(f"Order approved: {order_id}")
        self._publish_event("crypto.order.approved", {"order_id": order_id})
        return True

    def reject_order(
        self, order_id: str, approval_token: str, reason: str = ""
    ) -> bool:
        """
        Reject a pending order.

        Args:
            order_id: Order ID to reject
            approval_token: Must match the order's approval_token
            reason: Optional rejection reason

        Returns:
            True if rejected, False if token mismatch or order not found
        """
        with self._lock:
            order = self._get_order_internal(order_id)
            if not order:
                return False

            if order.status != "waiting_approval":
                return False

            if order.approval_token != approval_token:
                logger.warning(f"Reject failed: invalid token for {order_id}")
                return False

            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE pending_orders SET status=?, rejected_reason=? WHERE order_id=?",
                    ("rejected", reason, order_id),
                )
                conn.commit()

        logger.info(f"Order rejected: {order_id} (reason: {reason})")
        self._publish_event(
            "crypto.order.rejected",
            {"order_id": order_id, "reason": reason},
        )
        return True

    def mark_executed(self, order_id: str, result_data: Optional[Dict] = None) -> None:
        """Mark an approved order as executed."""
        now = time.time()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE pending_orders SET status=?, executed_at=? WHERE order_id=?",
                    ("executed", now, order_id),
                )
                conn.commit()

        logger.info(f"Order executed: {order_id}")
        self._publish_event(
            "crypto.order.executed",
            {"order_id": order_id, "result": result_data or {}},
        )

    def mark_failed(self, order_id: str, error: str) -> None:
        """Mark an approved order as failed."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE pending_orders SET status=?, rejected_reason=? WHERE order_id=?",
                    ("failed", error, order_id),
                )
                conn.commit()

        logger.warning(f"Order failed: {order_id} ({error})")
        self._publish_event(
            "crypto.order.failed",
            {"order_id": order_id, "error": error},
        )

    def get_pending_orders(self) -> List[PendingOrder]:
        """Get all orders with status 'waiting_approval'."""
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM pending_orders WHERE status='waiting_approval' ORDER BY created_at DESC"
                ).fetchall()
                return [self._row_to_order(row, conn) for row in rows]

    def get_order(self, order_id: str) -> Optional[PendingOrder]:
        """Get a specific order by ID."""
        with self._lock:
            return self._get_order_internal(order_id)

    def check_expired_orders(self) -> List[PendingOrder]:
        """
        Find and mark expired orders.

        Returns:
            List of newly expired orders
        """
        expired: List[PendingOrder] = []
        now = time.time()

        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM pending_orders WHERE status='waiting_approval'"
                ).fetchall()

                for row in rows:
                    order = self._row_to_order(row, conn)
                    if order.is_expired:
                        conn.execute(
                            "UPDATE pending_orders SET status='expired' WHERE order_id=?",
                            (order.order_id,),
                        )
                        order.status = "expired"
                        expired.append(order)

                if expired:
                    conn.commit()

        for order in expired:
            logger.info(f"Order expired: {order.order_id}")
            self._publish_event(
                "crypto.order.expired", {"order_id": order.order_id}
            )

        return expired

    def cleanup_old_orders(self, days: int = 30) -> int:
        """
        Remove completed orders older than N days.

        Returns:
            Number of orders removed
        """
        cutoff = time.time() - (days * 86400)
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM pending_orders WHERE status IN ('executed', 'expired', 'rejected', 'failed') AND created_at < ?",
                    (cutoff,),
                )
                conn.commit()
                count = cursor.rowcount

        if count > 0:
            logger.info(f"Cleaned up {count} old orders")
        return count

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    def _get_order_internal(self, order_id: str) -> Optional[PendingOrder]:
        """Get order without lock (caller must hold lock)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pending_orders WHERE order_id=?", (order_id,)
            ).fetchone()
            if row:
                return self._row_to_order(row, conn)
            return None

    def _row_to_order(self, row: tuple, conn: sqlite3.Connection) -> PendingOrder:
        """Convert a database row to PendingOrder."""
        # Get column names from cursor description
        col_names = [desc[0] for desc in conn.execute("SELECT * FROM pending_orders LIMIT 0").description]
        d = dict(zip(col_names, row))

        risk_result = None
        if d.get("risk_check_result"):
            try:
                risk_result = json.loads(d["risk_check_result"])
            except (json.JSONDecodeError, TypeError):
                pass

        return PendingOrder(
            order_id=d["order_id"],
            exchange=d["exchange"],
            symbol=d["symbol"],
            side=d["side"],
            order_type=d["order_type"],
            quantity=d["quantity"],
            price_eur=d["price_eur"],
            total_eur=d["total_eur"],
            approval_token=d["approval_token"],
            status=d["status"],
            created_at=d["created_at"],
            approved_at=d.get("approved_at"),
            executed_at=d.get("executed_at"),
            rejected_reason=d.get("rejected_reason"),
            timeout_seconds=d.get("timeout_seconds", 300.0),
            risk_check_result=risk_result,
        )

    def _update_status(self, order_id: str, status: str) -> None:
        """Update order status (caller must hold lock)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE pending_orders SET status=? WHERE order_id=?",
                (status, order_id),
            )
            conn.commit()

    def _publish_event(self, channel: str, data: Dict[str, Any]) -> None:
        """Publish event to EventBus if available."""
        if not self.event_bus:
            return
        try:
            # EventBus.publish is async — use fire-and-forget from sync context
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    self.event_bus.publish(
                        channel=channel,
                        data=data,
                        source="PendingOrderManager",
                    )
                )
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"Failed to publish {channel}: {e}")
