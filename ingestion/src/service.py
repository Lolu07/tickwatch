import logging
import signal
import sys
import threading
import time

from .config import Config
from .finnhub_ws import FinnhubWebSocket
from .kinesis_publisher import KinesisPublisher
from .models import Trade

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Top-level orchestrator: wires the Finnhub WebSocket to the Kinesis publisher
    and handles graceful shutdown on SIGINT / SIGTERM.
    """

    def __init__(self, config: Config):
        self._config = config
        self._publisher = KinesisPublisher(config)
        self._ws = FinnhubWebSocket(config, on_trade=self._handle_trade)
        self._stats_thread: threading.Thread | None = None

    def run(self) -> None:
        self._register_signals()
        self._start_stats_logger()
        logger.info(
            "Starting TickWatch ingestion — symbols: %s, stream: %s",
            self._config.symbols,
            self._config.kinesis_stream_name,
        )
        try:
            self._ws.run_forever()  # blocks
        finally:
            self._shutdown()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _handle_trade(self, trade: Trade) -> None:
        logger.debug(
            "TRADE %s  price=%.4f  vol=%.2f", trade.symbol, trade.price, trade.volume
        )
        self._publisher.put(trade)

    def _shutdown(self) -> None:
        logger.info("Shutting down — flushing remaining records...")
        self._publisher.close()
        stats = self._publisher.stats
        logger.info(
            "Final stats — published: %d  failed: %d",
            stats["total_published"],
            stats["total_failed"],
        )

    def _register_signals(self) -> None:
        def _handler(signum, frame):
            logger.info("Received signal %s — stopping", signum)
            self._ws.stop()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _start_stats_logger(self) -> None:
        def _loop():
            while True:
                time.sleep(60)
                logger.info("Publisher stats: %s", self._publisher.stats)

        self._stats_thread = threading.Thread(target=_loop, daemon=True)
        self._stats_thread.start()
