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

log = logging.getLogger("spv")
