# -*- coding: utf-8 -*-
"""
「三、单门店画像诊断」板块冒烟测试（pytest）

裸 Streamlit 模式渲染，验证各数据场景（缺渠道 / 客群字段、含全套字段、
等级筛选、筛选结果为空、边界表）均不崩溃；含 _mean_delta 边界断言。

运行方式：
    /d/Anaconda/python.exe -m pytest -q            # pytest（推荐）
    /d/Anaconda/python.exe test_single_store_ui.py  # 直接运行（演示输出）
"""

import os
import sys

if __package__ in (None, ""):
    # 直接运行时保证项目根目录可导入 utils / conftest
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 直接运行时保证 UTF-8 输出（Windows GBK 控制台无法打印 ✓ 等字符）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import pytest
import streamlit as st

from utils import report

from conftest import build_constructed_raw


@pytest.fixture(autouse=True)
def _clean_single_store_state():
    """每个用例前清理单店板块的会话 key，避免用例间状态污染。"""
    for key in ("single_grade_filter", "single_store_select"):
        st.session_state.pop(key, None)
    yield


# ==================== 渲染冒烟（裸 Streamlit 模式） ====================
def test_sample_render(sample_level):
    """示例数据（无渠道 / 客群字段）：雷达缺维度、饼图隐藏，不崩溃。"""
    report.render_single_store_section(sample_level)


def test_constructed_render(constructed_level):
    """构造数据（含渠道 + 客群 + 店长 / 类型）：完整画像渲染不崩溃。"""
    report.render_single_store_section(constructed_level)


def test_grade_filter_s(constructed_level):
    """等级筛选 S 级：只展示该等级门店，不崩溃。"""
    st.session_state["single_grade_filter"] = "S级"
    report.render_single_store_section(constructed_level)


def test_grade_filter_a(constructed_level):
    """等级筛选 A 级：不崩溃。"""
    st.session_state["single_grade_filter"] = "A级"
    report.render_single_store_section(constructed_level)


def test_grade_filter_all(constructed_level):
    """等级筛选「全部」：展示全部门店，不崩溃。"""
    st.session_state["single_grade_filter"] = "全部"
    report.render_single_store_section(constructed_level)


def test_grade_filter_empty(constructed_level):
    """筛选等级无门店：显示友好提示而非崩溃。"""
    no_s = constructed_level.copy()
    no_s["门店等级"] = "C"  # 全表 C 级，筛选 S 级必为空
    st.session_state["single_grade_filter"] = "S级"
    report.render_single_store_section(no_s)


# ==================== 边界情况 ====================
def test_empty_df_render():
    """空表：不崩溃。"""
    report.render_single_store_section(pd.DataFrame())


def test_single_store_render(constructed_level):
    """单店表：不崩溃。"""
    report.render_single_store_section(constructed_level.iloc[[0]])


def test_no_name_render():
    """无门店名称的表：不崩溃。"""
    report.render_single_store_section(pd.DataFrame({"销售额": [1.0]}))


# ==================== 工具函数边界断言 ====================
def test_mean_delta_edges():
    """_mean_delta：高 / 低 / 持平 / 均值缺失四类边界。"""
    assert report._mean_delta(0.5, 1.0) == ("低于均值 50%", "down")
    assert report._mean_delta(2.0, 1.0) == ("高于均值 100%", "up")
    assert report._mean_delta(1.0, 1.0) == ("与均值持平", "neutral")
    assert report._mean_delta(0.5, None) == (None, "neutral")


# ==================== 直接运行模式（python test_single_store_ui.py） ====================
def _run_demo():
    """直接运行时的演示输出；pytest 模式请使用上面的测试用例。"""
    from utils import data_process, leveling, metrics

    print("=" * 70)
    print("直接运行模式：单店板块渲染冒烟演示（推荐使用 pytest 验证：")
    print("    /d/Anaconda/python.exe -m pytest -q）")
    print("=" * 70)

    # 场景 1：示例数据（无渠道 / 客群字段）
    sample = data_process.build_sample_data()
    cleaned, _ = data_process.clean_data(sample)
    level_df = leveling.leveling_stores(metrics.calc_basic_metrics(cleaned))
    report.render_single_store_section(level_df)
    print("场景 1（示例数据）渲染完成 ✓")

    # 场景 2：构造数据（含渠道 + 客群 + 店长 / 类型）
    cleaned2, _ = data_process.clean_data(build_constructed_raw())
    level_df2 = leveling.leveling_stores(metrics.calc_basic_metrics(cleaned2))
    report.render_single_store_section(level_df2)
    print("场景 2（构造数据）渲染完成 ✓")

    print("全部场景演示完成")


if __name__ == "__main__":
    _run_demo()
