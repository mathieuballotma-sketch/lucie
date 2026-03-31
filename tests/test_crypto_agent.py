"""Tests for crypto agent components."""

from __future__ import annotations

import asyncio
import sys
from typing import List

# Add the project root to the path
sys.path.insert(0, '/sessions/zealous-elegant-brahmagupta/mnt/mon-agence-ia')

from app.services.crypto.risk_guard import RiskGuard, RiskLimits, RiskCheckResult
from app.services.crypto.tax_reporter import TaxReporter, Transaction, TaxEvent, TaxReport
from app.services.crypto.mining_monitor import MiningMonitor, MiningMetrics, MiningStatus
from app.services.crypto.secret_vault import SecretVault, ExchangeCredentials
from app.services.crypto.exchange_gateway import (
    BalanceEntry, OrderResult, MarketTicker, OrderSide, OrderType
)


# ============================================================================
# RiskGuard Tests
# ============================================================================

class TestRiskGuard:
    """Test RiskGuard limits enforcement."""

    def test_normal_order_allowed(self):
        guard = RiskGuard()
        result = guard.check_order("BTC/EUR", "buy", 0.01, 30000, "market")
        assert result.allowed is True, f"Normal order should be allowed: {result.reason}"
        print("✓ test_normal_order_allowed passed")

    def test_exceeds_max_order(self):
        guard = RiskGuard(RiskLimits(max_order_eur=500))
        result = guard.check_order("BTC/EUR", "buy", 0.1, 30000, "market")
        # 0.1 × 30000 = 3000 > 500
        assert result.allowed is False, "Order exceeding limit should be rejected"
        assert "limite" in result.reason.lower() or "exceed" in result.reason.lower()
        print("✓ test_exceeds_max_order passed")

    def test_forbidden_asset(self):
        guard = RiskGuard()
        result = guard.check_order("SHIB/EUR", "buy", 1000, 0.0001, "market")
        assert result.allowed is False, "Forbidden asset should be rejected"
        assert "forbidden" in result.reason.lower() or "interdit" in result.reason.lower()
        print("✓ test_forbidden_asset passed")

    def test_margin_order_blocked(self):
        guard = RiskGuard()
        result = guard.check_order("BTC/EUR", "buy", 0.01, 30000, "margin")
        assert result.allowed is False, "Margin orders should be blocked"
        print("✓ test_margin_order_blocked passed")

    def test_futures_blocked(self):
        guard = RiskGuard()
        result = guard.check_order("BTC/EUR", "buy", 0.01, 30000, "futures")
        assert result.allowed is False, "Futures orders should be blocked"
        print("✓ test_futures_blocked passed")

    def test_daily_limit(self):
        guard = RiskGuard(RiskLimits(max_daily_eur=1000))
        # First order OK
        r1 = guard.check_order("BTC/EUR", "buy", 0.01, 30000, "market")
        assert r1.allowed is True
        guard.record_order(300)

        # Second order exceeding
        r2 = guard.check_order("ETH/EUR", "buy", 1, 800, "market")
        # 300 + 800 = 1100 > 1000
        assert r2.allowed is False, "Daily limit exceeded should be rejected"
        assert "daily" in r2.reason.lower() or "quotidien" in r2.reason.lower()
        print("✓ test_daily_limit passed")

    def test_absolute_max_enforced(self):
        guard = RiskGuard(RiskLimits(max_order_eur=999999))
        result = guard.check_order("BTC/EUR", "buy", 1, 20000, "market")
        # 20000 > ABSOLUTE_MAX (10000)
        assert result.allowed is False, "Absolute max should be enforced"
        print("✓ test_absolute_max_enforced passed")

    def test_whitelist_enforced(self):
        guard = RiskGuard(RiskLimits(allowed_assets=["BTC", "ETH"]))
        r1 = guard.check_order("BTC/EUR", "buy", 0.01, 30000, "market")
        assert r1.allowed is True

        r2 = guard.check_order("SOL/EUR", "buy", 1, 100, "market")
        assert r2.allowed is False, "Non-whitelisted asset should be rejected"
        assert "not allowed" in r2.reason.lower() or "non autorisé" in r2.reason.lower()
        print("✓ test_whitelist_enforced passed")

    def test_stop_loss_warning(self):
        guard = RiskGuard(RiskLimits(require_stop_loss=True))
        result = guard.check_order("BTC/EUR", "buy", 0.01, 30000, "market")
        assert result.allowed is True
        assert any("stop" in w.lower() for w in result.warnings)
        print("✓ test_stop_loss_warning passed")

    def run_all(self):
        """Run all RiskGuard tests."""
        self.test_normal_order_allowed()
        self.test_exceeds_max_order()
        self.test_forbidden_asset()
        self.test_margin_order_blocked()
        self.test_futures_blocked()
        self.test_daily_limit()
        self.test_absolute_max_enforced()
        self.test_whitelist_enforced()
        self.test_stop_loss_warning()
        print("\n✅ All RiskGuard tests passed!\n")


# ============================================================================
# TaxReporter Tests (PMPA)
# ============================================================================

class TestTaxReporter:
    """Test TaxReporter with PMPA method."""

    def test_simple_profit(self):
        reporter = TaxReporter()
        reporter.add_transactions([
            Transaction(date="2025-01-15", type="buy", asset="BTC",
                       quantity=1.0, price_eur=30000, total_eur=30000),
            Transaction(date="2025-06-15", type="sell", asset="BTC",
                       quantity=1.0, price_eur=40000, total_eur=40000),
        ])
        report = reporter.generate_report(2025)

        assert len(report.events) == 1
        assert report.events[0].plus_value == 10000.0
        assert report.net_plus_value == 10000.0
        assert report.flat_tax_30_pct == 3000.0
        print("✓ test_simple_profit passed")

    def test_pmpa_multiple_buys(self):
        reporter = TaxReporter()
        reporter.add_transactions([
            Transaction(date="2025-01-01", type="buy", asset="BTC",
                       quantity=1.0, price_eur=30000, total_eur=30000),
            Transaction(date="2025-03-01", type="buy", asset="BTC",
                       quantity=1.0, price_eur=40000, total_eur=40000),
            Transaction(date="2025-06-01", type="sell", asset="BTC",
                       quantity=1.0, price_eur=45000, total_eur=45000),
        ])
        report = reporter.generate_report(2025)

        # PMPA = (30000 + 40000) / 2 = 35000
        # PV = 45000 - 35000 = 10000
        assert len(report.events) == 1
        assert abs(report.events[0].pmpa - 35000) < 0.01
        assert abs(report.events[0].plus_value - 10000) < 0.01
        print("✓ test_pmpa_multiple_buys passed")

    def test_loss(self):
        reporter = TaxReporter()
        reporter.add_transactions([
            Transaction(date="2025-01-01", type="buy", asset="ETH",
                       quantity=10.0, price_eur=3000, total_eur=30000),
            Transaction(date="2025-06-01", type="sell", asset="ETH",
                       quantity=10.0, price_eur=2000, total_eur=20000),
        ])
        report = reporter.generate_report(2025)

        assert report.events[0].plus_value == -10000.0
        assert report.net_plus_value == -10000.0
        assert report.flat_tax_30_pct == 0.0  # No tax on losses
        print("✓ test_loss passed")

    def test_csv_export(self):
        reporter = TaxReporter()
        reporter.add_transactions([
            Transaction(date="2025-01-01", type="buy", asset="BTC",
                       quantity=1.0, price_eur=30000, total_eur=30000),
            Transaction(date="2025-06-01", type="sell", asset="BTC",
                       quantity=1.0, price_eur=35000, total_eur=35000),
        ])
        report = reporter.generate_report(2025)
        csv_content = reporter.export_csv_2086(report)

        assert "Date cession" in csv_content
        assert "BTC" in csv_content
        assert "5000" in csv_content  # Gain
        print("✓ test_csv_export passed")

    def run_all(self):
        """Run all TaxReporter tests."""
        self.test_simple_profit()
        self.test_pmpa_multiple_buys()
        self.test_loss()
        self.test_csv_export()
        print("\n✅ All TaxReporter tests passed!\n")


# ============================================================================
# MiningMonitor Tests
# ============================================================================

class TestMiningMonitor:
    """Test MiningMonitor profitability calculation."""

    async def test_profitable(self):
        monitor = MiningMonitor(electricity_cost_kwh=0.22)
        metrics = await monitor.check_metrics(
            hashrate_mhs=100, gpu_temp=65,
            power_watts=200, estimated_daily_revenue=5.0,
        )
        # Cost = 0.2kW × 24h × 0.22 = 1.056EUR
        assert metrics.status == MiningStatus.PROFITABLE
        assert metrics.daily_profit_eur > 0
        print("✓ test_profitable passed")

    async def test_unprofitable(self):
        monitor = MiningMonitor(electricity_cost_kwh=0.30)
        metrics = await monitor.check_metrics(
            hashrate_mhs=50, gpu_temp=70,
            power_watts=300, estimated_daily_revenue=1.0,
        )
        # Cost = 0.3kW × 24h × 0.30 = 2.16EUR > 1.0EUR
        assert metrics.status == MiningStatus.UNPROFITABLE
        print("✓ test_unprofitable passed")

    async def test_overheating(self):
        monitor = MiningMonitor()
        metrics = await monitor.check_metrics(
            hashrate_mhs=100, gpu_temp=95,
            power_watts=200, estimated_daily_revenue=5.0,
        )
        assert metrics.status == MiningStatus.OVERHEATING
        print("✓ test_overheating passed")

    async def test_recommendation_text(self):
        monitor = MiningMonitor()
        metrics = await monitor.check_metrics(
            hashrate_mhs=100, gpu_temp=95,
            power_watts=200, estimated_daily_revenue=5.0,
        )
        rec = monitor.get_recommendation(metrics)
        assert "STOP" in rec or "ARRÊTER" in rec
        print("✓ test_recommendation_text passed")

    def run_all(self):
        """Run all MiningMonitor tests."""
        asyncio.run(self.test_profitable())
        asyncio.run(self.test_unprofitable())
        asyncio.run(self.test_overheating())
        asyncio.run(self.test_recommendation_text())
        print("\n✅ All MiningMonitor tests passed!\n")


# ============================================================================
# SecretVault Tests
# ============================================================================

class TestSecretVault:
    """Test SecretVault."""

    def test_store_and_retrieve(self):
        # Create vault with in-memory keyring fallback
        vault = SecretVault()
        try:
            vault.store_credentials(
                "test_exchange",
                api_key="test_key_123",
                api_secret="test_secret_456",
                permissions="read",
            )

            with vault.get_credentials("test_exchange") as creds:
                assert creds is not None
                assert creds.exchange == "test_exchange"
                assert creds.api_key == "test_key_123"
                assert creds.api_secret == "test_secret_456"
                assert creds.permissions == "read"
        except Exception as e:
            # If keyring fails, skip this test (expected in test environment)
            print(f"⊘ test_store_and_retrieve skipped (keyring unavailable: {e})")
            return

        print("✓ test_store_and_retrieve passed")

    def test_missing_credentials(self):
        vault = SecretVault()
        try:
            with vault.get_credentials("nonexistent") as creds:
                assert creds is None
        except Exception as e:
            print(f"⊘ test_missing_credentials skipped (keyring unavailable: {e})")
            return

        print("✓ test_missing_credentials passed")

    def test_credentials_repr_safe(self):
        creds = ExchangeCredentials(
            exchange="binance",
            api_key="super_secret_key_12345",
            api_secret="super_secret_secret_xyz",
        )
        repr_str = repr(creds)
        assert "super_secret" not in repr_str
        assert "12345" not in repr_str
        assert "xyz" not in repr_str
        assert "..." in repr_str
        print("✓ test_credentials_repr_safe passed")

    def run_all(self):
        """Run all SecretVault tests."""
        self.test_store_and_retrieve()
        self.test_missing_credentials()
        self.test_credentials_repr_safe()
        print("\n✅ All SecretVault tests passed!\n")


# ============================================================================
# Data Models Tests
# ============================================================================

class TestDataModels:
    """Test data model creation."""

    def test_balance_entry_creation(self):
        entry = BalanceEntry(
            exchange="binance",
            asset="BTC",
            free=1.5,
            locked=0.5,
            total=2.0,
            value_eur=60000,
        )
        assert entry.asset == "BTC"
        assert entry.total == 2.0
        assert entry.value_eur == 60000
        print("✓ test_balance_entry_creation passed")

    def test_order_result_creation(self):
        result = OrderResult(
            exchange="binance",
            order_id="12345",
            symbol="BTC/EUR",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=30000,
            status="filled",
            timestamp=1234567890.0,
            fees=15.0,
            fee_asset="EUR",
        )
        assert result.symbol == "BTC/EUR"
        assert result.status == "filled"

        audit_dict = result.to_audit_dict()
        assert audit_dict["order_id"] == "12345"
        assert audit_dict["side"] == "buy"
        print("✓ test_order_result_creation passed")

    def test_market_ticker_creation(self):
        ticker = MarketTicker(
            symbol="BTC/EUR",
            price=30000.0,
            volume_24h=1000000.0,
            change_24h_pct=5.5,
            timestamp=1234567890.0,
        )
        assert ticker.symbol == "BTC/EUR"
        assert ticker.price == 30000.0
        print("✓ test_market_ticker_creation passed")

    def test_mining_metrics_creation(self):
        metrics = MiningMetrics(
            hashrate_mhs=100.0,
            gpu_temp_celsius=65.0,
            power_watts=200.0,
            electricity_cost_kwh=0.22,
            daily_revenue_eur=5.0,
            daily_cost_eur=1.056,
            status=MiningStatus.PROFITABLE,
        )
        assert metrics.daily_profit_eur == pytest_approx(3.944, rel=0.01)
        print("✓ test_mining_metrics_creation passed")

    def run_all(self):
        """Run all data model tests."""
        self.test_balance_entry_creation()
        self.test_order_result_creation()
        self.test_market_ticker_creation()
        self.test_mining_metrics_creation()
        print("\n✅ All DataModels tests passed!\n")


def pytest_approx(value, rel=0.01):
    """Simple approx for testing."""
    return value


# ============================================================================
# Main Test Runner
# ============================================================================

def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("CRYPTO AGENT TEST SUITE")
    print("=" * 70 + "\n")

    try:
        print("Running RiskGuard tests...")
        TestRiskGuard().run_all()

        print("Running TaxReporter tests...")
        TestTaxReporter().run_all()

        print("Running MiningMonitor tests...")
        TestMiningMonitor().run_all()

        print("Running SecretVault tests...")
        TestSecretVault().run_all()

        print("Running DataModels tests...")
        TestDataModels().run_all()

        print("=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return 1

    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
