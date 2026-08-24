# -*- coding: utf-8 -*-
"""
pytest 共享 fixtures 与测试数据构造

两个测试文件原本各自重复「12 店含渠道/客群构造数据」的生成逻辑，
统一收拢到本文件，测试只消费 fixtures / 构造函数。
"""

import numpy as np
import pandas as pd
import pytest

from utils import data_process, leveling, metrics


def build_constructed_raw(n: int = 12) -> pd.DataFrame:
    """
    构造 12 家测试门店：含渠道 / 客群 / 店长 / 类型字段，定向埋 5 类问题。

    定向问题（供规则引擎测试断言）：
        - 测试门店1：活动过度依赖（97% 靠活动）+ 高价值渠道占比不足
        - 测试门店2：会员渗透率低 + 套购率低 + 新客主导
        - 测试门店3：高获客低转化
        - 测试门店4：获客不足
        - 测试门店5：渠道单一
    """
    rng = np.random.default_rng(7)

    hk = rng.integers(600, 2600, n)
    dd = (hk * rng.uniform(0.5, 0.85, n)).astype(int)
    cj = np.maximum((dd * rng.uniform(0.25, 0.5, n)).astype(int), 1)
    xse = (cj * rng.uniform(300, 900, n)).round(1)
    # 客单价为派生字段，不入输入数据，由清洗阶段自动计算

    channels = {ch: rng.integers(0, int(hk.mean()), n)
                for ch in ["自然流量获客", "线上引流获客", "转介绍获客",
                           "异业合作获客", "线下拓客获客", "活动获客"]}
    ch_df = pd.DataFrame(channels)
    ch_df = ch_df.mul(hk / ch_df.sum(axis=1).replace(0, 1), axis=0).astype(int)

    df = pd.DataFrame({
        "门店名称": [f"测试门店{i}" for i in range(1, n + 1)],
        "门店店长": [f"店长{i}" for i in range(1, n + 1)],
        "门店类型": [f"类型{i % 3}" for i in range(1, n + 1)],
        "获客数量": hk, "到店数量": dd, "成交人数": cj, "销售额": xse,
    })
    for ch in channels:
        df[ch] = ch_df[ch].values
    df["老客成交数"] = (cj * rng.uniform(0.1, 0.5, n)).astype(int)
    df["会员成交数"] = (cj * rng.uniform(0.2, 0.6, n)).astype(int)
    df["高客单成交数"] = (cj * rng.uniform(0.1, 0.4, n)).astype(int)

    # 整数列统一 int64（避免 clean_data 口径修正触发 FutureWarning）
    int_cols = (["获客数量", "到店数量", "成交人数"] + list(channels)
                + ["老客成交数", "会员成交数", "高客单成交数"])
    df[int_cols] = df[int_cols].astype("int64")

    # ---------- 定向构造问题（渠道数需与获客数量同量级，避免占比>100% 离群值） ----------
    # 测试门店1：活动过度依赖（97% 靠活动）+ 高价值渠道占比不足
    df.loc[0, ["自然流量获客", "线上引流获客", "转介绍获客", "异业合作获客", "线下拓客获客", "活动获客"]] = \
        [20, 10, 5, 5, 10, int(df.loc[0, "获客数量"]) - 50]
    # 测试门店2：会员渗透率低 + 套购率低 + 新客主导
    df.loc[1, ["老客成交数", "会员成交数", "高客单成交数"]] = [1, 1, 1]
    # 测试门店3：高获客低转化
    df.loc[2, "获客数量"] = int(hk.max()) * 2
    df.loc[2, ["到店数量", "成交人数"]] = [200, 20]
    # 测试门店4：获客不足（渠道同步缩放，保持占比合计 100%）
    df.loc[3, "获客数量"] = 50
    df.loc[3, ["自然流量获客", "线上引流获客", "转介绍获客", "异业合作获客", "线下拓客获客", "活动获客"]] = \
        [10, 10, 10, 10, 5, 5]
    # 测试门店5：渠道单一（全部获客集中在自然流量）
    df.loc[4, ["自然流量获客", "线上引流获客", "转介绍获客", "异业合作获客", "线下拓客获客", "活动获客"]] = \
        [int(df.loc[4, "获客数量"]), 0, 0, 0, 0, 0]

    return df


@pytest.fixture(scope="session")
def sample_level() -> pd.DataFrame:
    """示例数据（无渠道 / 客群字段）全流水线：清洗 → 指标 → 分层。"""
    cleaned, _ = data_process.clean_data(data_process.build_sample_data())
    return leveling.leveling_stores(metrics.calc_basic_metrics(cleaned))


@pytest.fixture(scope="session")
def constructed_level() -> pd.DataFrame:
    """构造数据（含渠道 + 客群 + 描述字段，定向埋问题）全流水线：清洗 → 指标 → 分层。"""
    cleaned, _ = data_process.clean_data(build_constructed_raw())
    return leveling.leveling_stores(metrics.calc_basic_metrics(cleaned))
