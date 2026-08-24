# -*- coding: utf-8 -*-
"""
日志初始化模块

统一日志体系：控制台（stderr）+ 滚动文件 logs/app.log，便于线上排查与调试。

环境变量控制（Windows 设置方式：set STORE_DIAG_LOG_LEVEL=DEBUG）：
    - STORE_DIAG_LOG_LEVEL  日志级别：DEBUG / INFO / WARNING / ERROR（默认 INFO）
    - STORE_DIAG_LOG_FILE   日志文件路径（默认项目根目录 logs/app.log）
    - STORE_DIAG_LOG_DIR    日志目录（默认项目根目录 logs/，STORE_DIAG_LOG_FILE 优先）

使用方式（业务模块）：
    import logging
    logger = logging.getLogger(__name__)   # 自动按模块名命名
    logger.info(...) / logger.debug(...) / logger.exception("...", exc_info=True)

app.py 启动时调用 setup_logging() 一次；测试直接运行场景下不调用也不报错。
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# 日志格式：时间 [级别] 模块:行号 - 消息
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 默认日志目录：项目根目录下的 logs/
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# 滚动文件大小与保留份数
FILE_MAX_BYTES = 5 * 1024 * 1024   # 5MB
FILE_BACKUP_COUNT = 3              # 保留最近 3 份


def _resolve_log_file() -> Path:
    """解析日志文件路径：环境变量优先，否则使用默认 logs/app.log。"""
    env_file = os.environ.get("STORE_DIAG_LOG_FILE")
    if env_file:
        return Path(env_file)
    log_dir = Path(os.environ.get("STORE_DIAG_LOG_DIR", DEFAULT_LOG_DIR))
    return log_dir / "app.log"


def setup_logging(level: str = None) -> logging.Logger:
    """
    初始化日志体系（幂等：重复调用只生效一次）。

    参数：
        level: 日志级别字符串（DEBUG/INFO/WARNING/ERROR），
               未指定时读取环境变量 STORE_DIAG_LOG_LEVEL，默认 INFO

    返回：
        根业务 logger（getLogger("store_diagnosis")），供模块直接使用
    """
    # 幂等：已初始化过（根 logger 已有处理器）时直接返回
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger("store_diagnosis")

    log_level = (level or os.environ.get("STORE_DIAG_LOG_LEVEL", "INFO")).upper()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # ---------- 控制台处理器（stderr） ----------
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(console)

    # ---------- 滚动文件处理器（logs/app.log） ----------
    try:
        log_file = _resolve_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=FILE_MAX_BYTES,
            backupCount=FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root.addHandler(file_handler)
    except OSError as e:
        # 日志目录不可写时降级为仅控制台（不影响应用运行）
        logging.getLogger("store_diagnosis").warning("日志文件初始化失败，仅输出到控制台：%s", e)

    return logging.getLogger("store_diagnosis")
