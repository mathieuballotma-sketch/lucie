"""RiskGuard — Inviolable risk limits for crypto trading."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...utils.logger import logger


@dataclass
class RiskLimits:
    """Configurable risk limits per user."""
    max_order_eur: float = 1000.0      # Max per order in EUR
    max_daily_eur: float = 5000.0      # Max per day in EUR
    max_position_pct: float = 20.0     # Max % of portfolio in one asset
    require_stop_loss: bool = True     # Stop-loss mandatory
    stop_loss_pct: float = 10.0        # Default stop-loss (-10%)
    allowed_assets: Optional[List[str]] = None  # If set, whitelist only
    forbidden_assets: List[str] = field(
        default_factory=lambda: ["SHIB", "DOGE", "PEPE", "FLOKI"]  # Meme coins
    )


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    allowed: bool
    reason: str = ""
    warnings: List[str] = field(default_factory=list)


class RiskGuard:
    """
    Verifies each order against risk limits.

    IMPORTANT : This class is the last line of defense before execution.
    No order can bypass these checks.
    """

    # Hardcoded — CANNOT be modified by configuration
    _ABSOLUTE_MAX_ORDER_EUR = 10_000.0    # Even if user sets higher
    _ABSOLUTE_MAX_DAILY_EUR = 50_000.0
    _FORBIDDEN_ORDER_TYPES = {"margin", "futures", "perpetual", "options"}

    def __init__(self, limits: Optional[RiskLimits] = None) -> None:
        self._limits = limits or RiskLimits()
        self._daily_volume: Dict[str, float] = {}  # date_str → total EUR
        self._order_history: List[Dict[str, Any]] = []

    def check_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price_eur: float,
        order_type: str = "market",
        portfolio_total_eur: float = 0,
    ) -> RiskCheckResult:
        """
        Verify an order against all limits.

        Returns a RiskCheckResult with allowed=True/False
        and the reason for rejection if applicable.
        """
        warnings: List[str] = []
        total_eur = quantity * price_eur

        # 1. Forbidden order type
        if order_type.lower() in self._FORBIDDEN_ORDER_TYPES:
            return RiskCheckResult(
                allowed=False,
                reason=f"Forbidden order type: {order_type}. "
                       f"Lucie does not allow leverage or derivatives.",
            )

        # 2. Forbidden asset
        asset = symbol.split("/")[0] if "/" in symbol else symbol
        if asset in self._limits.forbidden_assets:
            return RiskCheckResult(
                allowed=False,
                reason=f"Asset {asset} in forbidden list. "
                       f"Reason: too speculative.",
            )

        # 3. Whitelist
        if self._limits.allowed_assets:
            if asset not in self._limits.allowed_assets:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Asset {asset} not allowed. "
                           f"Allowed: {', '.join(self._limits.allowed_assets)}",
                )

        # 4. Order amount limit
        max_order = min(self._limits.max_order_eur, self._ABSOLUTE_MAX_ORDER_EUR)
        if total_eur > max_order:
            return RiskCheckResult(
                allowed=False,
                reason=f"Amount {total_eur:.2f}EUR exceeds order limit "
                       f"of {max_order:.2f}EUR.",
            )

        # 5. Daily volume limit
        today = time.strftime("%Y-%m-%d")
        daily_total = self._daily_volume.get(today, 0) + total_eur
        max_daily = min(self._limits.max_daily_eur, self._ABSOLUTE_MAX_DAILY_EUR)
        if daily_total > max_daily:
            return RiskCheckResult(
                allowed=False,
                reason=f"Daily volume {daily_total:.2f}EUR would exceed "
                       f"limit of {max_daily:.2f}EUR.",
            )

        # 6. Portfolio concentration
        if portfolio_total_eur > 0 and side == "buy":
            position_pct = (total_eur / portfolio_total_eur) * 100
            if position_pct > self._limits.max_position_pct:
                warnings.append(
                    f"⚠️ This order is {position_pct:.1f}% of portfolio "
                    f"(limit: {self._limits.max_position_pct}%)"
                )

        # 7. Stop-loss required
        if self._limits.require_stop_loss and side == "buy":
            warnings.append(
                f"📋 Stop-loss recommended at -{self._limits.stop_loss_pct}%"
            )

        return RiskCheckResult(
            allowed=True,
            reason="Order validated by RiskGuard",
            warnings=warnings,
        )

    def record_order(self, total_eur: float) -> None:
        """Record an executed order for daily tracking."""
        today = time.strftime("%Y-%m-%d")
        self._daily_volume[today] = self._daily_volume.get(today, 0) + total_eur
        self._order_history.append({
            "date": today,
            "amount": total_eur,
            "timestamp": time.time(),
        })

    @property
    def daily_remaining_eur(self) -> float:
        """Remaining authorized amount for today."""
        today = time.strftime("%Y-%m-%d")
        used = self._daily_volume.get(today, 0)
        max_daily = min(self._limits.max_daily_eur, self._ABSOLUTE_MAX_DAILY_EUR)
        return max(0, max_daily - used)

    @property
    def daily_used_eur(self) -> float:
        """Amount already used today."""
        today = time.strftime("%Y-%m-%d")
        return self._daily_volume.get(today, 0)
