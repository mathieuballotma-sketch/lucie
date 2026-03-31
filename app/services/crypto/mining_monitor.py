"""MiningMonitor — Passive surveillance of crypto mining."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ...utils.logger import logger


class MiningStatus(Enum):
    UNKNOWN = "unknown"
    PROFITABLE = "profitable"
    MARGINAL = "marginal"       # Profitability < 20%
    UNPROFITABLE = "unprofitable"
    OVERHEATING = "overheating"
    STOPPED = "stopped"


@dataclass
class MiningMetrics:
    """Current mining metrics."""
    hashrate_mhs: float = 0.0       # Hashrate in MH/s
    gpu_temp_celsius: float = 0.0
    power_watts: float = 0.0
    electricity_cost_kwh: float = 0.22  # EUR/kWh (France average)
    daily_revenue_eur: float = 0.0
    daily_cost_eur: float = 0.0
    status: MiningStatus = MiningStatus.UNKNOWN
    timestamp: float = field(default_factory=time.time)

    @property
    def daily_profit_eur(self) -> float:
        return self.daily_revenue_eur - self.daily_cost_eur

    @property
    def profit_margin_pct(self) -> float:
        if self.daily_revenue_eur <= 0:
            return -100.0
        return (self.daily_profit_eur / self.daily_revenue_eur) * 100


class MiningMonitor:
    """
    Passive mining observer.

    Does NOT control the miner — observe only.
    Recommendations based on metrics.
    """

    TEMP_WARNING = 80.0   # °C
    TEMP_CRITICAL = 90.0  # °C
    MARGIN_WARNING = 20.0 # %

    def __init__(self, electricity_cost_kwh: float = 0.22) -> None:
        self._cost_kwh = electricity_cost_kwh
        self._history: List[MiningMetrics] = []

    async def check_metrics(
        self,
        hashrate_mhs: float,
        gpu_temp: float,
        power_watts: float,
        estimated_daily_revenue: float,
    ) -> MiningMetrics:
        """
        Evaluate metrics and determine status.

        Does NOT touch the miner — returns recommendation only.
        """
        daily_cost = (power_watts / 1000) * 24 * self._cost_kwh

        # Determine status
        if gpu_temp >= self.TEMP_CRITICAL:
            status = MiningStatus.OVERHEATING
        elif estimated_daily_revenue <= daily_cost:
            status = MiningStatus.UNPROFITABLE
        elif gpu_temp >= self.TEMP_WARNING:
            status = MiningStatus.MARGINAL
        else:
            margin = ((estimated_daily_revenue - daily_cost) /
                      max(estimated_daily_revenue, 0.01)) * 100
            status = (MiningStatus.PROFITABLE if margin > self.MARGIN_WARNING
                      else MiningStatus.MARGINAL)

        metrics = MiningMetrics(
            hashrate_mhs=hashrate_mhs,
            gpu_temp_celsius=gpu_temp,
            power_watts=power_watts,
            electricity_cost_kwh=self._cost_kwh,
            daily_revenue_eur=estimated_daily_revenue,
            daily_cost_eur=daily_cost,
            status=status,
        )

        self._history.append(metrics)
        # Keep 24h of history (1 check/min = 1440)
        if len(self._history) > 1440:
            self._history = self._history[-1440:]

        return metrics

    def get_recommendation(self, metrics: MiningMetrics) -> str:
        """Generate a text recommendation."""
        if metrics.status == MiningStatus.OVERHEATING:
            return (
                f"🔴 CRITICAL : GPU temp {metrics.gpu_temp_celsius}°C "
                f"exceeds {self.TEMP_CRITICAL}°C. "
                f"Recommendation : STOP mining immediately."
            )
        elif metrics.status == MiningStatus.UNPROFITABLE:
            return (
                f"🟡 Unprofitable : Cost {metrics.daily_cost_eur:.2f}EUR/day "
                f"> Revenue {metrics.daily_revenue_eur:.2f}EUR/day. "
                f"Loss : {abs(metrics.daily_profit_eur):.2f}EUR/day. "
                f"Recommendation : stop mining."
            )
        elif metrics.status == MiningStatus.MARGINAL:
            return (
                f"🟠 Marginal : Profit {metrics.daily_profit_eur:.2f}EUR/day "
                f"(margin {metrics.profit_margin_pct:.1f}%). "
                f"Recommendation : monitor price trends."
            )
        else:
            return (
                f"🟢 Profitable : Profit {metrics.daily_profit_eur:.2f}EUR/day "
                f"(margin {metrics.profit_margin_pct:.1f}%). "
                f"Temperature : {metrics.gpu_temp_celsius}°C."
            )

    def get_history(self, last_n: int = 100) -> List[MiningMetrics]:
        """Get recent history."""
        return self._history[-last_n:]
