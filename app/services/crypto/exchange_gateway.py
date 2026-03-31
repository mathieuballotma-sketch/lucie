"""ExchangeGateway — Unified multi-exchange interface."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .secret_vault import SecretVault, ExchangeCredentials
from ...utils.logger import logger

# Try importing aiohttp, provide fallback for testing
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    logger.warning("⚠️ aiohttp not available — exchange operations will fail")

# Try importing CircuitBreaker
try:
    from ...utils.circuit_breaker import CircuitBreaker
    HAS_CIRCUIT_BREAKER = True
except ImportError:
    HAS_CIRCUIT_BREAKER = False
    logger.warning("⚠️ CircuitBreaker not available — using pass-through")


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class ExchangeAPIError(Exception):
    """Exchange API error."""
    pass


@dataclass
class BalanceEntry:
    """Balance of an asset on an exchange."""
    exchange: str
    asset: str            # "BTC", "ETH", "EUR", etc.
    free: float           # Available
    locked: float         # In orders
    total: float          # free + locked
    value_eur: float = 0  # Value in EUR (calculated)


@dataclass
class OrderResult:
    """Result of an executed order."""
    exchange: str
    order_id: str
    symbol: str           # "BTC/EUR"
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float          # Execution price (or limit)
    status: str           # "filled", "pending", "rejected"
    timestamp: float
    fees: float = 0.0
    fee_asset: str = ""

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            "exchange": self.exchange,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status,
            "timestamp": self.timestamp,
            "fees": self.fees,
            "fee_asset": self.fee_asset,
        }


@dataclass
class MarketTicker:
    """Current price of a trading pair."""
    symbol: str
    price: float
    volume_24h: float
    change_24h_pct: float
    timestamp: float


class RateLimiter:
    """Rate limiter per exchange with sliding window."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait if necessary to respect the limit."""
        async with self._lock:
            now = time.monotonic()
            # Clean up timestamps outside the window
            self._timestamps = [
                t for t in self._timestamps if now - t < self._window
            ]
            if len(self._timestamps) >= self._max:
                # Wait for oldest to expire
                wait_time = self._window - (now - self._timestamps[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            self._timestamps.append(time.monotonic())


class _PassthroughCircuitBreaker:
    """Passthrough circuit breaker when the real one is not available."""

    async def call_async(self, func, *args, **kwargs):
        return await func(*args, **kwargs)


class ExchangeAdapter(ABC):
    """Abstract interface for an exchange."""

    @abstractmethod
    async def get_balances(self, creds: ExchangeCredentials) -> List[BalanceEntry]:
        ...

    @abstractmethod
    async def get_ticker(self, creds: ExchangeCredentials,
                         symbol: str) -> MarketTicker:
        ...

    @abstractmethod
    async def place_order(self, creds: ExchangeCredentials,
                          symbol: str, side: OrderSide,
                          order_type: OrderType, quantity: float,
                          price: Optional[float] = None) -> OrderResult:
        ...

    @abstractmethod
    async def get_order_history(self, creds: ExchangeCredentials,
                                symbol: str, limit: int = 50
                                ) -> List[OrderResult]:
        ...


class BinanceAdapter(ExchangeAdapter):
    """
    Binance Adapter — REST API v3.

    Base URL : https://api.binance.com
    Authentication : HMAC-SHA256 on query string
    Rate limit : 1200 requests/minute (weight-based)
    """

    BASE_URL = "https://api.binance.com"

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter(max_requests=1100, window_seconds=60)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not HAS_AIOHTTP:
            raise ExchangeAPIError("aiohttp not available")

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
            )
        return self._session

    def _sign(self, params: Dict[str, str],
              secret: str) -> Dict[str, str]:
        """Sign parameters with HMAC-SHA256."""
        params["timestamp"] = str(int(time.time() * 1000))
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            secret.encode(), query.encode(), hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    async def _request(
        self, method: str, path: str,
        creds: ExchangeCredentials,
        params: Optional[Dict[str, str]] = None,
        signed: bool = False,
    ) -> Dict[str, Any]:
        """HTTP request with rate limiting and retry."""
        if not HAS_AIOHTTP:
            raise ExchangeAPIError("aiohttp not available")

        await self._rate_limiter.acquire()
        session = await self._get_session()

        params = params or {}
        headers = {"X-MBX-APIKEY": creds.api_key}

        if signed:
            params = self._sign(params, creds.api_secret)

        url = f"{self.BASE_URL}{path}"

        for attempt in range(3):
            try:
                async with session.request(
                    method, url, params=params, headers=headers,
                ) as resp:
                    data = await resp.json()
                    if resp.status == 429:
                        # Rate limited — backoff
                        wait = 2 ** attempt
                        logger.warning(f"Binance rate limited, waiting {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    if resp.status >= 400:
                        raise ExchangeAPIError(
                            f"Binance {resp.status}: {data.get('msg', '')}"
                        )
                    return data

            except Exception as e:
                if attempt < 2 and HAS_AIOHTTP:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise ExchangeAPIError(f"Binance request failed: {e}")

        raise ExchangeAPIError("Binance max retries exceeded")

    async def get_balances(self, creds: ExchangeCredentials) -> List[BalanceEntry]:
        data = await self._request(
            "GET", "/api/v3/account", creds, signed=True,
        )
        balances = []
        for b in data.get("balances", []):
            free = float(b["free"])
            locked = float(b["locked"])
            if free + locked > 0:
                balances.append(BalanceEntry(
                    exchange="binance",
                    asset=b["asset"],
                    free=free,
                    locked=locked,
                    total=free + locked,
                ))
        return balances

    async def get_ticker(self, creds: ExchangeCredentials,
                         symbol: str) -> MarketTicker:
        data = await self._request(
            "GET", "/api/v3/ticker/24hr", creds,
            params={"symbol": symbol.replace("/", "")},
        )
        return MarketTicker(
            symbol=symbol,
            price=float(data["lastPrice"]),
            volume_24h=float(data["volume"]),
            change_24h_pct=float(data["priceChangePercent"]),
            timestamp=time.time(),
        )

    async def place_order(self, creds: ExchangeCredentials,
                          symbol: str, side: OrderSide,
                          order_type: OrderType, quantity: float,
                          price: Optional[float] = None) -> OrderResult:
        if creds.permissions != "trade":
            raise PermissionError("Trading not allowed — read-only credentials")

        params: Dict[str, str] = {
            "symbol": symbol.replace("/", ""),
            "side": side.value.upper(),
            "type": "MARKET" if order_type == OrderType.MARKET else "LIMIT",
            "quantity": f"{quantity:.8f}",
        }
        if price is not None and order_type == OrderType.LIMIT:
            params["price"] = f"{price:.8f}"
            params["timeInForce"] = "GTC"

        data = await self._request(
            "POST", "/api/v3/order", creds, params=params, signed=True,
        )

        return OrderResult(
            exchange="binance",
            order_id=str(data["orderId"]),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=float(data.get("executedQty", quantity)),
            price=float(data.get("price", 0)),
            status=data.get("status", "unknown").lower(),
            timestamp=time.time(),
            fees=0,
        )

    async def get_order_history(self, creds: ExchangeCredentials,
                                symbol: str, limit: int = 50
                                ) -> List[OrderResult]:
        data = await self._request(
            "GET", "/api/v3/allOrders", creds,
            params={"symbol": symbol.replace("/", ""), "limit": str(limit)},
            signed=True,
        )
        results = []
        for o in data:
            results.append(OrderResult(
                exchange="binance",
                order_id=str(o["orderId"]),
                symbol=symbol,
                side=OrderSide.BUY if o["side"] == "BUY" else OrderSide.SELL,
                order_type=OrderType.MARKET if o["type"] == "MARKET" else OrderType.LIMIT,
                quantity=float(o.get("executedQty", 0)),
                price=float(o.get("price", 0)),
                status=o.get("status", "").lower(),
                timestamp=float(o.get("time", 0)) / 1000,
            ))
        return results

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class ExchangeGateway:
    """
    Unified multi-exchange gateway.

    Dispatches calls to the correct adapter.
    Manages global circuit breaker.
    """

    def __init__(self, vault: SecretVault) -> None:
        self._vault = vault
        self._adapters: Dict[str, ExchangeAdapter] = {
            "binance": BinanceAdapter(),
        }
        self._circuit_breakers: Dict[str, Any] = {}
        for name in self._adapters:
            if HAS_CIRCUIT_BREAKER:
                self._circuit_breakers[name] = CircuitBreaker(
                    name=f"exchange_{name}",
                    failure_threshold=5,
                    recovery_timeout=60.0,
                )
            else:
                self._circuit_breakers[name] = _PassthroughCircuitBreaker()

    async def get_balances(self, exchange: str) -> List[BalanceEntry]:
        """Fetch balances from an exchange."""
        adapter = self._adapters.get(exchange)
        if not adapter:
            raise ValueError(f"Unsupported exchange: {exchange}")

        cb = self._circuit_breakers[exchange]

        with self._vault.get_credentials(exchange) as creds:
            if not creds:
                raise ValueError(f"No credentials for {exchange}")
            return await cb.call_async(adapter.get_balances, creds)

    async def get_ticker(self, exchange: str, symbol: str) -> MarketTicker:
        adapter = self._adapters.get(exchange)
        if not adapter:
            raise ValueError(f"Unsupported exchange: {exchange}")

        cb = self._circuit_breakers[exchange]

        with self._vault.get_credentials(exchange) as creds:
            if not creds:
                raise ValueError(f"No credentials for {exchange}")
            return await cb.call_async(adapter.get_ticker, creds, symbol)

    async def place_order(
        self, exchange: str, symbol: str,
        side: OrderSide, order_type: OrderType,
        quantity: float, price: Optional[float] = None,
    ) -> OrderResult:
        adapter = self._adapters.get(exchange)
        if not adapter:
            raise ValueError(f"Unsupported exchange: {exchange}")

        # Verify permissions
        if not self._vault.has_trade_permission(exchange):
            raise PermissionError(
                f"Trading not allowed for {exchange}. "
                f"Credentials are read-only."
            )

        cb = self._circuit_breakers[exchange]

        with self._vault.get_credentials(exchange) as creds:
            if not creds:
                raise ValueError(f"No credentials for {exchange}")
            return await cb.call_async(
                adapter.place_order, creds, symbol, side,
                order_type, quantity, price,
            )

    async def get_all_balances(self) -> List[BalanceEntry]:
        """Fetch balances from all configured exchanges."""
        exchanges = self._vault.list_exchanges()
        all_balances: List[BalanceEntry] = []

        tasks = [self.get_balances(ex) for ex in exchanges]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for ex, result in zip(exchanges, results):
            if isinstance(result, Exception):
                logger.warning(f"⚠️ Error fetching balances from {ex}: {result}")
            else:
                all_balances.extend(result)

        return all_balances

    async def close(self) -> None:
        for adapter in self._adapters.values():
            if hasattr(adapter, "close"):
                await adapter.close()
