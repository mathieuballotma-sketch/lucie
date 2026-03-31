"""TaxReporter — French tax compliance for crypto gains using PMPA method."""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...utils.logger import logger


@dataclass
class Transaction:
    """Crypto transaction for tax calculation."""
    date: str              # "YYYY-MM-DD"
    type: str              # "buy" or "sell"
    asset: str             # "BTC", "ETH"
    quantity: float
    price_eur: float       # Unit price in EUR
    total_eur: float       # Total amount EUR
    fees_eur: float = 0.0
    exchange: str = ""
    order_id: str = ""


@dataclass
class TaxEvent:
    """Tax event (sale)."""
    date: str
    asset: str
    quantity_sold: float
    sale_price_eur: float     # Total sale price
    pmpa: float               # Weighted average acquisition price
    acquisition_cost: float   # PMPA × quantity sold
    plus_value: float         # Sale - Acquisition
    fees_eur: float = 0.0


@dataclass
class TaxReport:
    """Annual tax report."""
    year: int
    events: List[TaxEvent] = field(default_factory=list)
    total_plus_values: float = 0.0
    total_moins_values: float = 0.0
    net_plus_value: float = 0.0
    flat_tax_30_pct: float = 0.0

    def summary(self) -> str:
        return (
            f"📊 Tax Report {self.year}\n"
            f"  Number of sales : {len(self.events)}\n"
            f"  Total gains : {self.total_plus_values:+.2f}EUR\n"
            f"  Total losses : {self.total_moins_values:+.2f}EUR\n"
            f"  Net result : {self.net_plus_value:+.2f}EUR\n"
            f"  Estimated flat tax (30%) : {self.flat_tax_30_pct:.2f}EUR\n"
        )


class TaxReporter:
    """
    Calculate crypto gains using PMPA method (France).

    PMPA = Prix Moyen Pondéré d'Acquisition
    (Weighted Average Acquisition Price)

    Usage:
        reporter = TaxReporter()
        reporter.add_transactions(transactions)
        report = reporter.generate_report(2025)
        csv_content = reporter.export_csv_2086(report)
    """

    def __init__(self) -> None:
        self._transactions: List[Transaction] = []

    def add_transactions(self, transactions: List[Transaction]) -> None:
        """Add transactions sorted by date."""
        self._transactions.extend(transactions)
        self._transactions.sort(key=lambda t: t.date)

    def generate_report(self, year: int) -> TaxReport:
        """
        Generate tax report for a year.

        PMPA Algorithm:
        1. Maintain portfolio state (quantity + total cost)
        2. On each buy: add to total cost
        3. On each sell: calculate PMPA and gain
        """
        # Portfolio state per asset
        portfolio: Dict[str, Dict[str, float]] = {}  # asset → {qty, cost}

        events: List[TaxEvent] = []

        for tx in self._transactions:
            asset = tx.asset

            if asset not in portfolio:
                portfolio[asset] = {"qty": 0.0, "cost": 0.0}

            if tx.type == "buy":
                # Buy: add to portfolio
                portfolio[asset]["qty"] += tx.quantity
                portfolio[asset]["cost"] += tx.total_eur + tx.fees_eur

            elif tx.type == "sell":
                # Sell: calculate gain
                if not tx.date.startswith(str(year)):
                    # Transaction outside target year
                    # but still update PMPA
                    qty = portfolio[asset]["qty"]
                    cost = portfolio[asset]["cost"]
                    if qty > 0:
                        pmpa = cost / qty
                        portfolio[asset]["qty"] -= tx.quantity
                        portfolio[asset]["cost"] -= pmpa * tx.quantity
                    continue

                qty = portfolio[asset]["qty"]
                cost = portfolio[asset]["cost"]

                if qty <= 0:
                    logger.warning(
                        f"⚠️ Sale of {asset} without stock — "
                        f"possible untraceable transfer"
                    )
                    continue

                pmpa = cost / qty
                acquisition_cost = pmpa * tx.quantity
                plus_value = tx.total_eur - acquisition_cost - tx.fees_eur

                events.append(TaxEvent(
                    date=tx.date,
                    asset=asset,
                    quantity_sold=tx.quantity,
                    sale_price_eur=tx.total_eur,
                    pmpa=pmpa,
                    acquisition_cost=acquisition_cost,
                    plus_value=plus_value,
                    fees_eur=tx.fees_eur,
                ))

                # Update portfolio
                portfolio[asset]["qty"] -= tx.quantity
                portfolio[asset]["cost"] -= pmpa * tx.quantity

        # Aggregate calculations
        total_pv = sum(e.plus_value for e in events if e.plus_value > 0)
        total_mv = sum(e.plus_value for e in events if e.plus_value < 0)
        net = total_pv + total_mv
        tax = max(0, net) * 0.30  # Flat tax 30%

        return TaxReport(
            year=year,
            events=events,
            total_plus_values=total_pv,
            total_moins_values=total_mv,
            net_plus_value=net,
            flat_tax_30_pct=tax,
        )

    def export_csv_2086(self, report: TaxReport) -> str:
        """
        Export report to CSV format compatible with form 2086.

        Columns:
        Date | Asset | Quantity | Sale Price EUR | PMPA | Acquisition Cost |
        Gain/Loss | Fees
        """
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")

        # Header
        writer.writerow([
            "Date cession",
            "Actif numérique",
            "Quantité cédée",
            "Prix de cession (EUR)",
            "PMPA (EUR)",
            "Coût d'acquisition (EUR)",
            "Plus/Moins-value (EUR)",
            "Frais (EUR)",
        ])

        for event in report.events:
            writer.writerow([
                event.date,
                event.asset,
                f"{event.quantity_sold:.8f}",
                f"{event.sale_price_eur:.2f}",
                f"{event.pmpa:.2f}",
                f"{event.acquisition_cost:.2f}",
                f"{event.plus_value:+.2f}",
                f"{event.fees_eur:.2f}",
            ])

        # Totals
        writer.writerow([])
        writer.writerow([
            "TOTAL", "", "", "",
            "", "",
            f"{report.net_plus_value:+.2f}",
            "",
        ])
        writer.writerow([
            f"Flat tax (30%)", "", "", "",
            "", "",
            f"{report.flat_tax_30_pct:.2f}",
            "",
        ])

        return output.getvalue()
