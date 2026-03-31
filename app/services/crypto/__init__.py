"""Crypto services — secure, compliant crypto investment management."""

from __future__ import annotations

from .secret_vault import SecretVault, ExchangeCredentials
from .exchange_gateway import (
    ExchangeGateway,
    OrderSide,
    OrderType,
    BalanceEntry,
    OrderResult,
    MarketTicker,
    ExchangeAPIError,
)
from .risk_guard import RiskGuard, RiskLimits, RiskCheckResult
from .tax_reporter import TaxReporter, Transaction, TaxEvent, TaxReport
from .mining_monitor import MiningMonitor, MiningMetrics, MiningStatus

# CryptoInvestorAgent is imported lazily to avoid pydantic dependency
# from .crypto_agent import CryptoInvestorAgent

__all__ = [
    "SecretVault",
    "ExchangeCredentials",
    "ExchangeGateway",
    "OrderSide",
    "OrderType",
    "BalanceEntry",
    "OrderResult",
    "MarketTicker",
    "ExchangeAPIError",
    "RiskGuard",
    "RiskLimits",
    "RiskCheckResult",
    "TaxReporter",
    "Transaction",
    "TaxEvent",
    "TaxReport",
    "MiningMonitor",
    "MiningMetrics",
    "MiningStatus",
    # "CryptoInvestorAgent",  # Lazy load due to pydantic
]
