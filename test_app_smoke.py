# -*- coding: utf-8 -*-
"""
应用级端到端冒烟测试（Streamlit AppTest）

用 Streamlit 官方 AppTest 框架真实执行 app.py 脚本：
    - 默认进入数据导入页，无异常
    - 点击「加载示例数据」→ 成功提示 → 切换到分析诊断页渲染，无异常
    - 侧边栏标题 / 版本号来自 config 与 utils.__version__（配置化联调验证）

运行方式：
    /d/Anaconda/python.exe -m pytest -q
"""

import logging
import os
import sys

if __package__ in (None, ""):
    # 直接运行时保证项目根目录可导入 utils
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pytest
from streamlit.testing.v1 import AppTest

from utils import __version__


def _new_app() -> AppTest:
    """创建 app.py 的 AppTest 实例（每次独立会话状态）。"""
    return AppTest.from_file("app.py", default_timeout=60)


# ==================== 应用级冒烟 ====================
def test_app_import_page_loads():
    """默认进入数据导入页：无异常；侧边栏标题 / 版本号来自配置。"""
    at = _new_app()
    at.run()
    assert not at.exception, at.exception
    # 标题来自 config.APP_TITLE / PAGE_ICON
    assert at.sidebar.title[0].value == "🏪 通用门店运营分层诊断系统"
    # 版本号来自 utils.__version__（升版本时本断言自动跟随）
    assert any(f"v{__version__}" in c.value for c in at.sidebar.caption)


def test_app_full_flow_sample_data():
    """端到端：加载示例数据 → 成功提示 → 切分析诊断页 → 渲染无异常。"""
    at = _new_app()
    at.run()
    assert not at.exception, at.exception

    # 1. 点击「加载示例数据」
    load_btn = next(b for b in at.button if "示例数据" in b.label)
    load_btn.click().run()
    assert not at.exception, at.exception
    assert any("15 家门店" in s.value for s in at.success), "导入成功提示缺失"

    # 2. 切换到分析诊断页（完整流水线：指标 → 分层 → 报告渲染）
    at.sidebar.radio[0].set_value("分析诊断").run()
    assert not at.exception, at.exception
    assert any("运营大盘" in m.value for m in at.subheader), "运营大盘板块缺失"


def test_app_debug_log_panel_only_in_debug(monkeypatch):
    """DEBUG 面板：STORE_DIAG_LOG_LEVEL=DEBUG 时出现，否则不出现。"""
    # 非 DEBUG：无日志面板
    monkeypatch.delenv("STORE_DIAG_LOG_LEVEL", raising=False)
    at = _new_app()
    at.run()
    assert not any("调试日志" in e.label for e in at.sidebar.expander)

    # DEBUG：出现日志面板
    monkeypatch.setenv("STORE_DIAG_LOG_LEVEL", "DEBUG")
    at = _new_app()
    at.run()
    assert any("调试日志" in e.label for e in at.sidebar.expander), "DEBUG 模式应显示日志面板"


# ==================== 日志体系 ====================
def test_logging_setup_idempotent():
    """setup_logging 幂等：重复调用不重复添加处理器。"""
    from utils.logging_setup import setup_logging

    logger = setup_logging()
    assert isinstance(logger, logging.Logger)
    handler_count = len(logging.getLogger().handlers)
    assert handler_count > 0, "日志体系应有至少一个处理器"
    setup_logging()
    assert len(logging.getLogger().handlers) == handler_count, "重复初始化不应叠加处理器"
