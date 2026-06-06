import json
import logging
import time
import threading
from typing import Callable, List

import websocket

from .config import Config
from .models import Trade, SubscriptionStatus

logger = logging.getLogger(__name__)

FINNHUB_WS_URL = "wss://ws.finnhub.io"


class FinnhubWebSocket:
    """
    Maintains a persistent WebSocket connection to Finnhub.
    Automatically reconnects on disconnect with exponential back-off.
    Calls `on_trade` for every received trade tick.
    """

    def __init__(
        self,
        config: Config,
        on_trade: Callable[[Trade], None],
    ):
        self._config = config
        self._on_trade = on_trade
        self._ws: websocket.WebSocketApp | None = None
        self._running = False
        self._connected = threading.Event()
        self._last_message_at = 0.0
        self._reconnect_delay = 1  # seconds, doubles on each failure up to 60s

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Blocking call — runs until stop() is called."""
        self._running = True
        while self._running:
            self._connect()
            if self._running:
                logger.info(
                    "Reconnecting in %ss...", self._reconnect_delay
                )
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        url = f"{FINNHUB_WS_URL}?token={self._config.finnhub_api_key}"
        self._connected.clear()
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        # run_forever blocks until the connection drops
        self._ws.run_forever(ping_interval=self._config.ws_heartbeat_interval)

    def _on_open(self, ws) -> None:
        self._reconnect_delay = 1  # reset on successful connect
        logger.info("Connected to Finnhub WebSocket")
        self._last_message_at = time.time()
        for symbol in self._config.symbols:
            ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))
            logger.debug("Subscribed to %s", symbol)

    def _on_message(self, ws, raw: str) -> None:
        self._last_message_at = time.time()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Non-JSON message: %s", raw[:200])
            return

        msg_type = msg.get("type")
        if msg_type == "trade":
            for tick in msg.get("data", []):
                try:
                    trade = Trade.from_finnhub(tick)
                    self._on_trade(trade)
                except (KeyError, TypeError) as exc:
                    logger.warning("Malformed trade tick %s: %s", tick, exc)
        elif msg_type == "ping":
            pass  # websocket-client handles pong automatically
        elif msg_type == "error":
            logger.error("Finnhub error message: %s", msg)
        else:
            logger.debug("Unhandled message type '%s'", msg_type)

    def _on_error(self, ws, error) -> None:
        logger.error("WebSocket error: %s", error)

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        logger.warning(
            "WebSocket closed (code=%s msg=%s)", close_status_code, close_msg
        )
