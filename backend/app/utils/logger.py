import sys

from loguru import logger

from app.core.config import settings

logger.remove()
logger.add(sys.stdout, level=settings.LOG_LEVEL, colorize=True)
logger.add(
    settings.LOG_DIR / "app.log",
    level=settings.LOG_LEVEL,
    rotation="10 MB",
    retention="14 days",
    compression="zip",
)

__all__ = ["logger"]
