# -*- coding: utf-8 -*-
"""
自动诊断规则引擎测试（pytest）

场景覆盖：
    1. 示例数据（无渠道 / 客群字段）—— 验证缺字段容错
    2. 构造数据（含渠道 / 客群，定向埋问题）—— 验证规则与标签命中
    3. 边界容错（空表 / 单店 / 缺字段行 / 零值行）

运行方式：
    /d/Anaconda/python.exe -m pytest -q          # pytest（推荐）
    /d/Anaconda/python.exe test_diagnosis.py      # 直接运行（演示输出）
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

from utils import config, report

from conftest import build_constructed_raw


# ==================== 0. 配置校验 ====================
def test_validate_config():
    """业务配置一致性校验（换业态改配置后跑一遍，保证不会静默出错）。"""
    problems = config.validate_config()
    assert problems == [], f"业务配置校验未通过：{problems}"


# ==================== 1. 示例数据（无渠道 / 客群字段，验证缺字段容错） ====================
def test_sample_diagnosis_quality(sample_level):
    """每家门店的诊断结论与建议结构完整：结论 ≤140 字、建议 1~3 条、结论非空。"""
    assert len(sample_level) == 10
    for _, row in sample_level.iterrows():
        d = report.get_store_diagnosis(row, sample_level)
        assert d["门店名称"], "门店名称缺失"
        assert d["诊断结论"], "诊断结论为空"
        assert len(d["诊断结论"]) <= 140, f"结论过长：{len(d['诊断结论'])}字"
        assert 1 <= len(d["改进建议"]) <= 3, f"建议条数异常：{len(d['改进建议'])}"


def test_sample_levels_valid(sample_level):
    """等级全部落在 S/A/B/C，且数量合计等于门店数。"""
    grades = sample_level["门店等级"]
    assert set(grades).issubset({"S", "A", "B", "C"})
    assert grades.value_counts().sum() == len(sample_level)


def test_sample_overall_summary(sample_level):
    """大盘总结在缺渠道 / 客群字段时仍有亮点与共性问题。"""
    s = report.get_overall_summary(sample_level)
    assert s["highlights"], "缺渠道/客群字段时亮点不应为空"
    assert s["problems"], "缺渠道/客群字段时共性问题不应为空"


# ==================== 2. 构造数据（含渠道 + 客群字段，定向埋问题） ====================
def _store_row(level_df, name):
    """按门店名称取分层表中的第一行。"""
    return level_df[level_df["门店名称"] == name].iloc[0]


def test_targeted_issue_hits(constructed_level):
    """定向构造的问题应被规则引擎命中（换配置后如断言失败说明规则口径有变）。"""
    cases = {
        "测试门店1": "活动过度依赖",
        "测试门店2": "会员渗透率低",
        "测试门店3": "高获客低转化",
        "测试门店4": "获客不足",
        "测试门店5": "渠道单一",
    }
    for name, issue in cases.items():
        row = _store_row(constructed_level, name)
        d = report.get_store_diagnosis(row, constructed_level)
        assert issue in d["问题"], f"{name} 未命中「{issue}」：{d['问题']}"


def test_targeted_tags(constructed_level):
    """定向构造的门店标签符合预期（渠道 / 客群 / 问题三类）。"""
    r1 = _store_row(constructed_level, "测试门店1")
    assert "渠道单一型" in r1["渠道标签"]
    assert "渠道畸形" in r1["问题标签"]
    r3 = _store_row(constructed_level, "测试门店3")
    assert "高净值型" in r3["客群标签"]
    r5 = _store_row(constructed_level, "测试门店5")
    assert "自然流量驱动型" in r5["渠道标签"]


def test_constructed_overall_summary(constructed_level):
    """构造数据的大盘总结：共性问题中应包含「活动过度依赖」相关观察。"""
    s = report.get_overall_summary(constructed_level)
    assert any("活动营销" in p or "活动过度依赖" in p for p in s["problems"]), (
        f"活动过度依赖应为共性问题：{s['problems']}"
    )


# ==================== 3. 边界容错 ====================
def test_empty_overall_summary():
    """空表大盘：返回友好提示而非报错。"""
    s = report.get_overall_summary(pd.DataFrame())
    assert s == {"highlights": [], "problems": ["暂无门店数据，无法生成大盘诊断"]}


def test_single_store_scenarios(sample_level):
    """单店数据：大盘与单店诊断均正常输出（数据不足不报错）。"""
    single = sample_level.iloc[[0]].copy()
    s = report.get_overall_summary(single)
    assert isinstance(s["highlights"], list) and isinstance(s["problems"], list)
    d = report.get_store_diagnosis(sample_level.iloc[0], single)
    assert d["诊断结论"], "单店诊断结论为空"


def test_bare_row_missing_fields(constructed_level):
    """行缺字段（仅门店名称的 Series）：不报错，无问题命中。"""
    bare = pd.Series({"门店名称": "裸门店"})
    d = report.get_store_diagnosis(bare, constructed_level)
    assert d["问题"] == []
    assert d["诊断结论"]


def test_zero_row(constructed_level):
    """全 0 值行：不报错，建议条数正常。"""
    zero_row = constructed_level.iloc[1].copy()
    for col in constructed_level.columns:
        try:
            zero_row[col] = 0
        except Exception:
            pass
    zero_row["门店名称"] = "零值门店"
    d = report.get_store_diagnosis(zero_row, constructed_level)
    assert 1 <= len(d["改进建议"]) <= 3


def test_empty_df_row_diagnosis():
    """空 DataFrame 行级诊断：不抛异常。"""
    d = report.get_store_diagnosis(pd.Series({"门店名称": "空店"}), pd.DataFrame())
    assert d["问题"] == []


# ==================== 直接运行模式（python test_diagnosis.py） ====================
def _run_demo():
    """直接运行时的演示输出；pytest 模式请使用上面的测试用例。"""
    from utils import data_process, leveling, metrics

    print("=" * 70)
    print("直接运行模式：演示诊断引擎输出（推荐使用 pytest 验证：")
    print("    /d/Anaconda/python.exe -m pytest -q）")
    print("=" * 70)

    # 1. 示例数据
    print("1. 示例数据（无渠道 / 客群字段）")
    sample = data_process.build_sample_data()
    cleaned, issues = data_process.clean_data(sample)
    level_df = leveling.leveling_stores(metrics.calc_basic_metrics(cleaned))
    for _, row in level_df.iterrows():
        d = report.get_store_diagnosis(row, level_df)
        print(f"[{d['门店名称']}] 得分{d['综合得分']} {d['门店等级']}")
        print(f"   结论({len(d['诊断结论'])}字): {d['诊断结论']}")
    s = report.get_overall_summary(level_df)
    print("【大盘总结】亮点:", len(s["highlights"]), "条 / 共性问题:", len(s["problems"]), "条")

    # 2. 构造数据（定向埋问题）
    print("2. 构造数据（含渠道 + 客群字段，定向埋问题）")
    cleaned2, _ = data_process.clean_data(build_constructed_raw())
    level_df2 = leveling.leveling_stores(metrics.calc_basic_metrics(cleaned2))
    for name in [f"测试门店{i}" for i in range(1, 6)]:
        row = _store_row(level_df2, name)
        d = report.get_store_diagnosis(row, level_df2)
        print(f"[{d['门店名称']}] 问题: {d['问题']}")

    # 3. 边界容错
    print("3. 边界容错")
    print("空表大盘:", report.get_overall_summary(pd.DataFrame()))
    print("全部演示完成")


if __name__ == "__main__":
    _run_demo()
