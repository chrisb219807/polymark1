"""Polymarket API/CLOB client with retries, idempotency, and structured logging."""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

import requests
from requests import Response, Session


@dataclass(frozen=True)
class PolymarketConfig:
    """Runtime configuration for :class:`PolymarketClient`."""

    base_url: str = "https://clob.polymarket.com"
    api_key: str | None = None
    api_secret: str | None = None
    api_passphrase: str | None = None
    timeout_seconds: float = 10.0
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5

    @classmethod
    def from_env(cls, prefix: str = "POLYMARKET_") -> "PolymarketConfig":
        """Load config from environment variables.

        Supported vars:
        - ``{prefix}BASE_URL``
        - ``{prefix}API_KEY``
        - ``{prefix}API_SECRET``
        - ``{prefix}API_PASSPHRASE``
        - ``{prefix}TIMEOUT_SECONDS``
        - ``{prefix}MAX_RETRIES``
        - ``{prefix}RETRY_BACKOFF_SECONDS``
        """

        def _get(name: str, default: str | None = None) -> str | None:
            return os.getenv(f"{prefix}{name}", default)

        return cls(
            base_url=_get("BASE_URL", cls.base_url) or cls.base_url,
            api_key=_get("API_KEY"),
            api_secret=_get("API_SECRET"),
            api_passphrase=_get("API_PASSPHRASE"),
            timeout_seconds=float(_get("TIMEOUT_SECONDS", str(cls.timeout_seconds)) or cls.timeout_seconds),
            max_retries=int(_get("MAX_RETRIES", str(cls.max_retries)) or cls.max_retries),
            retry_backoff_seconds=float(
                _get("RETRY_BACKOFF_SECONDS", str(cls.retry_backoff_seconds)) or cls.retry_backoff_seconds
            ),
        )


class PolymarketClient:
    """High-level client for Polymarket CLOB/API workflows.

    This client focuses on:
    - authenticated session setup
    - odds retrieval as implied probability in [0, 1]
    - buy/sell order placement with idempotency keys
    - position lookups
    - retries and timeout handling
    - structured logging fields for downstream observability
    """

    def __init__(
        self,
        config: PolymarketConfig | None = None,
        *,
        session: Session | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config or PolymarketConfig.from_env()
        self.logger = logger or logging.getLogger(__name__)
        self.session = session or requests.Session()
        self._configure_session()

    @classmethod
    def from_env(cls, *, prefix: str = "POLYMARKET_") -> "PolymarketClient":
        """Construct a client with environment-driven credentials/configuration."""
        return cls(config=PolymarketConfig.from_env(prefix=prefix))

    def _configure_session(self) -> None:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "polymarket-client/1.0",
        }

        if self.config.api_key:
            headers["X-API-KEY"] = self.config.api_key
        if self.config.api_secret:
            headers["X-API-SECRET"] = self.config.api_secret
        if self.config.api_passphrase:
            headers["X-API-PASSPHRASE"] = self.config.api_passphrase

        self.session.headers.update(headers)

    def _log(
        self,
        level: int,
        message: str,
        *,
        market_id: str | None = None,
        event_id: str | None = None,
        game_id: str | None = None,
        order_id: str | None = None,
        action: str | None = None,
        probability: float | None = None,
        **extra: Any,
    ) -> None:
        payload = {
            "market_id": market_id,
            "event_id": event_id,
            "game_id": game_id,
            "order_id": order_id,
            "action": action,
            "probability": probability,
            **extra,
        }
        self.logger.log(level, message, extra={"polymarket": payload})

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        market_id: str | None = None,
        event_id: str | None = None,
        game_id: str | None = None,
        order_id: str | None = None,
        action: str | None = None,
        probability: float | None = None,
    ) -> Response:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        timeout_s = timeout if timeout is not None else self.config.timeout_seconds
        last_exc: Exception | None = None

        for attempt in range(1, self.config.max_retries + 2):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    timeout=timeout_s,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    if attempt <= self.config.max_retries:
                        sleep_s = self.config.retry_backoff_seconds * attempt
                        self._log(
                            logging.WARNING,
                            "Retryable response from Polymarket API",
                            market_id=market_id,
                            event_id=event_id,
                            game_id=game_id,
                            order_id=order_id,
                            action=action,
                            probability=probability,
                            status_code=response.status_code,
                            attempt=attempt,
                            backoff_seconds=sleep_s,
                        )
                        time.sleep(sleep_s)
                        continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                if attempt > self.config.max_retries:
                    break
                sleep_s = self.config.retry_backoff_seconds * attempt
                self._log(
                    logging.WARNING,
                    "Request exception while calling Polymarket API; retrying",
                    market_id=market_id,
                    event_id=event_id,
                    game_id=game_id,
                    order_id=order_id,
                    action=action,
                    probability=probability,
                    error=str(exc),
                    attempt=attempt,
                    backoff_seconds=sleep_s,
                )
                time.sleep(sleep_s)

        self._log(
            logging.ERROR,
            "Exhausted retries when calling Polymarket API",
            market_id=market_id,
            event_id=event_id,
            game_id=game_id,
            order_id=order_id,
            action=action,
            probability=probability,
            error=str(last_exc) if last_exc else "unknown",
        )
        if last_exc:
            raise last_exc
        raise RuntimeError("Polymarket API request failed without exception")

    def get_market_odds(self, market_id: str) -> float:
        """Fetch market odds and return implied probability in [0, 1]."""
        response = self._request("GET", f"markets/{market_id}/odds", market_id=market_id, action="get_market_odds")
        data = response.json()

        probability: float | None = None
        for key in ("probability", "implied_probability", "yes_probability"):
            value = data.get(key)
            if value is not None:
                probability = float(value)
                break

        if probability is None:
            best_bid = data.get("best_bid")
            best_ask = data.get("best_ask")
            if best_bid is not None and best_ask is not None:
                probability = (float(best_bid) + float(best_ask)) / 2.0

        if probability is None:
            raise ValueError(f"Unable to derive probability from response for market {market_id}: {data}")

        probability = max(0.0, min(1.0, probability))
        self._log(
            logging.INFO,
            "Fetched market implied probability",
            market_id=market_id,
            action="get_market_odds",
            probability=probability,
        )
        return probability

    def place_buy_order(
        self,
        market_id: str,
        side: str,
        size: float,
        max_price: float,
        *,
        idempotency_key: str | None = None,
        event_id: str | None = None,
        game_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a buy order and return order/fill details."""
        return self._place_order(
            market_id=market_id,
            side=side,
            size=size,
            price=max_price,
            action="buy",
            idempotency_key=idempotency_key,
            event_id=event_id,
            game_id=game_id,
        )

    def place_sell_order(
        self,
        market_id: str,
        side: str,
        size: float,
        min_price: float,
        *,
        idempotency_key: str | None = None,
        event_id: str | None = None,
        game_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a sell order and return order/fill details."""
        return self._place_order(
            market_id=market_id,
            side=side,
            size=size,
            price=min_price,
            action="sell",
            idempotency_key=idempotency_key,
            event_id=event_id,
            game_id=game_id,
        )

    def _place_order(
        self,
        *,
        market_id: str,
        side: str,
        size: float,
        price: float,
        action: str,
        idempotency_key: str | None,
        event_id: str | None,
        game_id: str | None,
    ) -> dict[str, Any]:
        if not 0 <= price <= 1:
            raise ValueError("Price must be in [0, 1]")
        if size <= 0:
            raise ValueError("Size must be > 0")

        idem_key = idempotency_key or str(uuid.uuid4())

        payload = {
            "market_id": market_id,
            "side": side,
            "size": size,
            "price": price,
            "action": action,
            "idempotency_key": idem_key,
        }

        response = self._request(
            "POST",
            "orders",
            json=payload,
            market_id=market_id,
            event_id=event_id,
            game_id=game_id,
            action=f"place_{action}_order",
        )
        data = response.json()

        order_id = str(data.get("order_id") or data.get("id") or "")
        result = {
            "order_id": order_id,
            "status": data.get("status"),
            "filled_size": data.get("filled_size", 0),
            "avg_fill_price": data.get("avg_fill_price"),
            "raw": data,
        }

        self._log(
            logging.INFO,
            "Placed order",
            market_id=market_id,
            event_id=event_id,
            game_id=game_id,
            order_id=order_id or None,
            action=f"place_{action}_order",
            probability=price,
            side=side,
            size=size,
            idempotency_key=idem_key,
            status=result["status"],
            filled_size=result["filled_size"],
        )
        return result

    def get_position(self, market_id: str) -> dict[str, Any]:
        """Inspect open exposure for a market."""
        response = self._request("GET", f"positions/{market_id}", market_id=market_id, action="get_position")
        data = response.json()
        self._log(
            logging.INFO,
            "Fetched position",
            market_id=market_id,
            action="get_position",
            exposure=data.get("exposure"),
            size=data.get("size"),
        )
        return data
