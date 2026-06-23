"""
comfy_core 自包含 logger —— 仅用标准库 logging，不依赖 mirage。

实现与 mirage/app/core/logger.py 等价（同格式、同级别），复制于此以保证
comfy_core 可独立部署（worker 侧无 mirage 时也能取到 logger）。
"""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger
