"""CryptoInvestorAgent — Secure, compliant crypto investment agent."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from ...agents.base_agent import BaseAgent
from .secret_vault import SecretVault
from .exchange_gateway import (
    ExchangeGateway, OrderSide, OrderType, BalanceEntry, OrderResult,
)
from .risk_guard import RiskGuard, RiskLimits
from .tax_reporter import TaxReporter, Transaction, TaxReport
from .mining_monitor import MiningMonitor, MiningMetrics
from ...utils.logger import logger


class CryptoInvestorAgent(BaseAgent):
    """
    Crypto investment agent — secure and compliant.

    Features:
    - Portfolio tracking
    - Order execution with RiskGuard verification
    - Tax reporting (PMPA method, French form 2086)
    - Mining monitoring
    - Risk limits enforcement

    COMPLIANCE:
    - Lucie is NOT a PSAN — this is a personal assistant
    - User retains full control of API keys (Keychain storage)
    - No fund custody (funds remain on exchanges)
    - No automated withdrawals
    - Every operation is audited
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(name="CryptoInvestorAgent", *args, **kwargs)
        self.stability = "core"

        self._vault = SecretVault()
        self._gateway = ExchangeGateway(self._vault)
        self._risk_guard = RiskGuard()
        self._tax_reporter = TaxReporter()
        self._mining_monitor = MiningMonitor()
        self._audit: Optional[Any] = None  # Injected by engine

        # Active DCA strategies
        self._active_dcas: Dict[str, Dict[str, Any]] = {}

    def can_handle(self, query: str) -> bool:
        """Check if this agent can handle the query."""
        keywords = [
            "crypto", "bitcoin", "btc", "ethereum", "eth",
            "portefeuille", "portfolio", "binance", "coinbase",
            "kraken", "acheter", "vendre", "dca", "stop-loss",
            "plus-value", "impot", "mining",
            "solde", "cours", "prix", "buy", "sell", "wallet",
        ]
        q = query.lower()
        return any(kw in q for kw in keywords)

    async def execute(self, query: str) -> str:
        """Main entry point — dispatch to correct action."""
        q = query.lower()

        if any(w in q for w in ["solde", "portefeuille", "portfolio", "bilan", "balance", "wallet"]):
            return await self.portfolio_summary()

        if any(w in q for w in ["acheter", "achete", "buy"]):
            return "I can help you buy crypto. Please specify: exchange (binance), asset (BTC), quantity, and price."

        if any(w in q for w in ["vendre", "vends", "sell"]):
            return "I can help you sell crypto. Please specify: exchange, asset, quantity, and price."

        if any(w in q for w in ["dca", "investissement", "cost-averaging"]):
            return "I can help set up Dollar Cost Averaging. Specify: exchange, asset, frequency (daily/weekly), amount."

        if any(w in q for w in ["impot", "taxe", "plus-value", "2086", "fiscal", "tax"]):
            return await self.tax_report_summary()

        if any(w in q for w in ["minage", "mining", "mineur", "gpu"]):
            return "I can monitor mining. Please provide: hashrate (MH/s), GPU temp (°C), power (watts), daily revenue (EUR)."

        if any(w in q for w in ["cours", "prix", "price"]):
            return "I can check prices. Please specify: exchange and asset (e.g., BTC/EUR on Binance)."

        if any(w in q for w in ["limites", "risque", "limits", "risk"]):
            return await self.show_risk_limits()

        return (
            "I can help with crypto management. What would you like to do?\n"
            "- Check portfolio (solde, portfolio)\n"
            "- Buy/Sell crypto (acheter, vendre)\n"
            "- Tax report (impot, 2086)\n"
            "- Mining monitoring (minage, GPU)\n"
            "- Risk settings (limites, risque)"
        )

    async def portfolio_summary(self) -> str:
        """Return portfolio summary across all exchanges."""
        try:
            exchanges = self._vault.list_exchanges()
            if not exchanges:
                return "❌ No exchanges configured. Use store_credentials() to add an exchange."

            summary = "📊 Portfolio Summary\n"
            summary += "=" * 50 + "\n"

            total_eur = 0.0

            for exchange in exchanges:
                try:
                    balances = await self._gateway.get_balances(exchange)
                    if not balances:
                        summary += f"\n{exchange.upper()}: No balance data\n"
                        continue

                    summary += f"\n{exchange.upper()}:\n"
                    exchange_total = 0.0

                    for balance in balances:
                        if balance.total > 0:
                            value_str = f" = {balance.value_eur:.2f}EUR" if balance.value_eur > 0 else ""
                            summary += (
                                f"  {balance.asset:6s} : "
                                f"{balance.total:>12.8f} "
                                f"(free: {balance.free:.8f}, locked: {balance.locked:.8f}){value_str}\n"
                            )
                            exchange_total += balance.value_eur

                    if exchange_total > 0:
                        summary += f"  Subtotal: {exchange_total:.2f}EUR\n"
                    total_eur += exchange_total

                except Exception as e:
                    summary += f"\n{exchange.upper()}: ⚠️ Error: {e}\n"

            summary += "\n" + "=" * 50 + "\n"
            summary += f"Total Portfolio: {total_eur:.2f}EUR\n"

            # Show risk limits
            summary += f"\nRisk Limits:\n"
            summary += f"  Daily remaining: {self._risk_guard.daily_remaining_eur:.2f}EUR\n"
            summary += f"  Daily used: {self._risk_guard.daily_used_eur:.2f}EUR\n"

            return summary

        except Exception as e:
            logger.error(f"Portfolio summary error: {e}")
            return f"❌ Error fetching portfolio: {e}"

    async def tax_report_summary(self) -> str:
        """Return tax report summary."""
        try:
            if not self._tax_reporter._transactions:
                return "ℹ️ No transactions recorded. Add transactions using add_transactions()."

            import datetime
            current_year = datetime.datetime.now().year
            report = self._tax_reporter.generate_report(current_year)

            return report.summary()

        except Exception as e:
            logger.error(f"Tax report error: {e}")
            return f"❌ Error generating tax report: {e}"

    async def show_risk_limits(self) -> str:
        """Show current risk limits."""
        limits = self._risk_guard._limits
        return (
            f"🛡️ Current Risk Limits:\n"
            f"  Max per order: {limits.max_order_eur:.2f}EUR\n"
            f"  Max per day: {limits.max_daily_eur:.2f}EUR\n"
            f"  Max position: {limits.max_position_pct:.1f}% of portfolio\n"
            f"  Stop-loss required: {limits.require_stop_loss}\n"
            f"  Stop-loss %: {limits.stop_loss_pct:.1f}%\n"
            f"  Allowed assets: {limits.allowed_assets or 'All (except forbidden)'}\n"
            f"  Forbidden assets: {', '.join(limits.forbidden_assets)}\n"
        )

    def store_exchange_credentials(
        self,
        exchange: str,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        permissions: str = "read",
    ) -> str:
        """Store exchange credentials securely."""
        try:
            self._vault.store_credentials(
                exchange=exchange,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                permissions=permissions,
            )
            return f"✅ Credentials for {exchange} stored securely."
        except Exception as e:
            logger.error(f"Error storing credentials: {e}")
            return f"❌ Error: {e}"

    def delete_exchange_credentials(self, exchange: str) -> str:
        """Delete exchange credentials from Keychain."""
        try:
            self._vault.delete_credentials(exchange)
            return f"✅ Credentials for {exchange} deleted."
        except Exception as e:
            logger.error(f"Error deleting credentials: {e}")
            return f"❌ Error: {e}"

    def add_transactions(self, transactions: List[Transaction]) -> str:
        """Add transactions for tax calculation."""
        try:
            self._tax_reporter.add_transactions(transactions)
            return f"✅ Added {len(transactions)} transactions."
        except Exception as e:
            logger.error(f"Error adding transactions: {e}")
            return f"❌ Error: {e}"

    async def check_mining(
        self,
        hashrate_mhs: float,
        gpu_temp: float,
        power_watts: float,
        estimated_daily_revenue: float,
    ) -> str:
        """Check mining profitability and health."""
        try:
            metrics = await self._mining_monitor.check_metrics(
                hashrate_mhs=hashrate_mhs,
                gpu_temp=gpu_temp,
                power_watts=power_watts,
                estimated_daily_revenue=estimated_daily_revenue,
            )

            rec = self._mining_monitor.get_recommendation(metrics)

            return (
                f"⛏️ Mining Status:\n"
                f"  Hashrate: {metrics.hashrate_mhs:.1f} MH/s\n"
                f"  GPU Temp: {metrics.gpu_temp_celsius:.1f}°C\n"
                f"  Power: {metrics.power_watts:.0f}W\n"
                f"  Daily Cost: {metrics.daily_cost_eur:.2f}EUR\n"
                f"  Daily Revenue: {metrics.daily_revenue_eur:.2f}EUR\n"
                f"  Daily Profit: {metrics.daily_profit_eur:+.2f}EUR\n"
                f"  Margin: {metrics.profit_margin_pct:+.1f}%\n"
                f"  Status: {metrics.status.value}\n\n"
                f"📋 {rec}"
            )

        except Exception as e:
            logger.error(f"Mining check error: {e}")
            return f"❌ Error: {e}"

    def configure_risk_limits(
        self,
        max_order_eur: Optional[float] = None,
        max_daily_eur: Optional[float] = None,
        max_position_pct: Optional[float] = None,
        require_stop_loss: Optional[bool] = None,
        stop_loss_pct: Optional[float] = None,
        allowed_assets: Optional[List[str]] = None,
    ) -> str:
        """Reconfigure risk limits."""
        try:
            limits = self._risk_guard._limits

            if max_order_eur is not None:
                limits.max_order_eur = min(max_order_eur, 10000)

            if max_daily_eur is not None:
                limits.max_daily_eur = min(max_daily_eur, 50000)

            if max_position_pct is not None:
                limits.max_position_pct = max_position_pct

            if require_stop_loss is not None:
                limits.require_stop_loss = require_stop_loss

            if stop_loss_pct is not None:
                limits.stop_loss_pct = stop_loss_pct

            if allowed_assets is not None:
                limits.allowed_assets = allowed_assets

            logger.info(f"Risk limits updated: {limits}")
            return "✅ Risk limits updated successfully."

        except Exception as e:
            logger.error(f"Error configuring limits: {e}")
            return f"❌ Error: {e}"

    async def export_tax_report(self, year: int) -> str:
        """Export tax report as CSV for form 2086."""
        try:
            report = self._tax_reporter.generate_report(year)
            csv_content = self._tax_reporter.export_csv_2086(report)
            return csv_content
        except Exception as e:
            logger.error(f"Error exporting tax report: {e}")
            return f"❌ Error: {e}"
