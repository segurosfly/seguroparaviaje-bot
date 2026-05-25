import logging
import os
from datetime import datetime
from config import DIR_LOGS

os.makedirs(DIR_LOGS, exist_ok=True)

_log_file = os.path.join(DIR_LOGS, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ]
)

_logger = logging.getLogger("segurosfly")


class _CallableLogger:
    """Logger wrapper that supports both log('msg') and log.info('msg')."""

    def __call__(self, msg, *args, **kwargs):
        _logger.info(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        _logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        _logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        _logger.error(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        _logger.debug(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        _logger.exception(msg, *args, **kwargs)


log = _CallableLogger()
