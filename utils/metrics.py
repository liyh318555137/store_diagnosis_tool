# -*- coding: utf-8 -*-
"""
门店运营指标计算引擎

模块说明：
    - 标准字段扩展：必选基础字段 + 可选渠道字段 + 可选客群字段（字段体系见 config.py）
    - 整体大盘指标：calc_summary_metrics —— 全部门店汇总指标
    - 单门店指标：calc_basic_metrics —— 每行一个门店的完整派生指标
    - 可选字段全部兼容：字段未映射时自动跳过相关指标，不报错
    - 所有除法带除零保护（返回 NaN），数值统一保留 2 位小数

字段定义（业务参数唯一来源：utils/config.py，换业态只改 config）：
    必选字段（6）：门店名称、获客数量、到店数量、成交人数、销售额、客单价
                  （客单价为派生字段，由清洗阶段按 销售额 / 成交人数 自动计算，无需上传）
    渠道字段（可选，5）：自然流量获客、线上引流获客、转介绍获客、异业合作获客、活动获客
    客群字段（可选，3）：老客成交数、会员成交数、高客单成交数

指标口径说明：
    - 渠道贡献销售额为估算值：渠道获客数量 × 客单价（未拆分渠道销售额时的替代方案）
    - 老客转化率 = 老客成交数 / 到店数量；新客转化率 =（成交人数 - 老客成交数）/ 到店数量
    - 各渠道获客占比的分母优先使用必选字段「获客数量」，该字段缺失时退化为各渠道之和
"""

import logging

import numpy as np
import pandas as pd

from . import config as cfg

logger = logging.getLogger(__name__)

# ==================== 字段定义（唯一来源：utils/config.py） ====================
# 此处仅绑定短名供本模块使用；修改字段 / 渠道 / 客群 / 别名配置请改 config.py
REQUIRED_FIELDS = cfg.REQUIRED_FIELDS
CHANNEL_FIELDS = cfg.CHANNEL_FIELDS
CUSTOMER_FIELDS = cfg.CUSTOMER_FIELDS
DESCRIPTIVE_FIELDS = cfg.DESCRIPTIVE_FIELDS
QUALITY_CHANNELS = cfg.QUALITY_CHANNELS
CHANNEL_NAME_MAP = cfg.CHANNEL_NAME_MAP

# 统一保留的小数位数
DECIMAL_PLACES = cfg.DECIMAL_PLACES


# ==================== 工具函数 ====================
def _has(df: pd.DataFrame, col: str) -> bool:
    """检查 DataFrame 是否包含指定列（可选字段兼容的核心判断）。"""
    return col in df.columns


def safe_div(a, b):
    """
    安全除法：除数为 0 / 空值时返回 NaN，避免除零报错。

    参数：
        a: 被除数（标量或 Series）
        b: 除数（标量或 Series）

    返回：
        除法结果，除零处为 NaN
    """
    # 统一转为数值，非数值自动置为 NaN
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        result = a / b
    # 无穷值（除零产生）统一替换为 NaN
    if isinstance(result, pd.Series):
        return result.replace([np.inf, -np.inf], np.nan)
    if result in (np.inf, -np.inf):
        return np.nan
    return result


def _safe_sum(series: pd.Series) -> float:
    """安全求和：全列为空时返回 NaN，否则正常求和（缺失值跳过）。"""
    if series.notna().any():
        return series.sum()
    return np.nan


# ==================== 单门店指标 ====================
def calc_basic_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算每个门店的完整派生指标（一行一店）。

    参数：
        df: 清洗后的标准字段数据（含「异常标记」「数据异常标记」列，可选字段可缺失）

    返回：
        pd.DataFrame: 门店指标表，列包含：
            - 原始字段（必选 + 已映射的可选字段）
            - 转化率类：到店转化率、成交转化率、总转化率
            - 渠道类：各渠道获客占比、各渠道贡献销售额及占比、渠道丰富度、优质渠道占比
            - 客群类：老客/会员/高客单占比、老客转化率、新客转化率
    """
    df = df.copy()
    result = pd.DataFrame(index=df.index)

    # ---------- 兜底：客单价缺失时用 销售额 / 成交人数 推算 ----------
    # 正常路径已由清洗阶段计算；此处兜底保护直接调用本函数的场景（如测试）
    if not _has(df, "客单价") and _has(df, "销售额") and _has(df, "成交人数"):
        df["客单价"] = safe_div(df["销售额"], df["成交人数"])

    # ---------- 保留原始字段（便于核对与下游使用） ----------
    # 门店名称、异常标记与数据异常标记（口径修正记录）
    for col in ["门店名称", "异常标记", "数据异常标记"]:
        if _has(df, col):
            result[col] = df[col]
    # 必选数值字段（仅保留实际存在的）
    for col in REQUIRED_FIELDS[1:]:
        if _has(df, col):
            result[col] = df[col]
    # 可选字段（仅保留实际存在的）
    for col in CHANNEL_FIELDS + CUSTOMER_FIELDS:
        if _has(df, col):
            result[col] = df[col]
    # 描述性字段（门店类型、门店店长等，穿透保留供明细展示）
    for col in DESCRIPTIVE_FIELDS:
        if _has(df, col):
            result[col] = df[col]

    # ---------- 基础转化率（必选字段齐全时计算） ----------
    if _has(df, "到店数量") and _has(df, "获客数量"):
        # 到店转化率 = 到店数量 / 获客数量
        result["到店转化率"] = safe_div(df["到店数量"], df["获客数量"]).round(DECIMAL_PLACES)
    if _has(df, "成交人数") and _has(df, "到店数量"):
        # 成交转化率 = 成交人数 / 到店数量
        result["成交转化率"] = safe_div(df["成交人数"], df["到店数量"]).round(DECIMAL_PLACES)
    if _has(df, "成交人数") and _has(df, "获客数量"):
        # 总转化率 = 成交人数 / 获客数量
        result["总转化率"] = safe_div(df["成交人数"], df["获客数量"]).round(DECIMAL_PLACES)

    # ---------- 渠道类指标（渠道字段存在时计算） ----------
    present_channels = [col for col in CHANNEL_FIELDS if _has(df, col)]
    if present_channels:
        # 获客总数：优先用必选字段「获客数量」，缺失时退化为各渠道之和
        if _has(df, "获客数量"):
            hk_total = df["获客数量"]
        else:
            hk_total = pd.concat([df[col] for col in present_channels], axis=1).sum(axis=1)

        # 各渠道获客占比 = 渠道获客 / 获客总数
        for ch in present_channels:
            result[f"{ch}占比"] = safe_div(df[ch], hk_total).round(DECIMAL_PLACES)

        # 渠道贡献销售额（估算：渠道获客 × 客单价）及占比
        if _has(df, "客单价"):
            for ch in present_channels:
                result[f"{ch}贡献销售额"] = (df[ch] * df["客单价"]).round(DECIMAL_PLACES)
            contrib_cols = [f"{ch}贡献销售额" for ch in present_channels]
            total_contrib = result[contrib_cols].sum(axis=1)  # 按门店汇总各渠道贡献
            for ch in present_channels:
                result[f"{ch}贡献占比"] = safe_div(result[f"{ch}贡献销售额"], total_contrib).round(DECIMAL_PLACES)

        # 渠道丰富度：有数据（非空且 > 0）的渠道数量
        channel_data = df[present_channels]
        result["渠道丰富度"] = (channel_data.notna() & (channel_data > 0)).sum(axis=1)

        # 优质渠道占比：转介绍 + 异业合作 的获客占获客总数比例
        quality_present = [col for col in QUALITY_CHANNELS if _has(df, col)]
        if quality_present:
            quality_sum = pd.concat([df[col] for col in quality_present], axis=1).sum(axis=1)
            result["优质渠道占比"] = safe_div(quality_sum, hk_total).round(DECIMAL_PLACES)

    # ---------- 客群类指标（客群字段存在时计算） ----------
    present_customers = [col for col in CUSTOMER_FIELDS if _has(df, col)]
    if present_customers and _has(df, "成交人数"):
        # 各客群成交占比 = 客群成交数 / 成交人数
        for fc in present_customers:
            result[f"{fc}占比"] = safe_div(df[fc], df["成交人数"]).round(DECIMAL_PLACES)

    # 老客 / 新客转化率（有老客成交数据且到店数量存在时计算）
    if _has(df, "老客成交数") and _has(df, "到店数量"):
        # 老客转化率 = 老客成交数 / 到店数量
        result["老客转化率"] = safe_div(df["老客成交数"], df["到店数量"]).round(DECIMAL_PLACES)
        if _has(df, "成交人数"):
            # 新客成交数 = 成交人数 - 老客成交数（口径：未识别为老客的均为新客）
            new_customers = df["成交人数"] - df["老客成交数"]
            result["新客转化率"] = safe_div(new_customers, df["到店数量"]).round(DECIMAL_PLACES)

    logger.debug("单店指标计算完成：%d 家门店，%d 个指标列", len(result), len(result.columns))
    return result


# ==================== 整体大盘指标 ====================
def calc_summary_metrics(store_df: pd.DataFrame) -> pd.Series:
    """
    计算整体大盘指标：全部门店汇总（总量、均值、渠道结构、客群结构）。

    参数：
        store_df: calc_basic_metrics 产出的门店指标表

    返回：
        pd.Series: 大盘指标，缺失字段对应的指标自动跳过
    """
    df = store_df
    summary = pd.Series(dtype=float)

    # ---------- 规模类 ----------
    summary["门店数量"] = len(df)
    if _has(df, "获客数量"):
        summary["总获客数量"] = _safe_sum(df["获客数量"])
    if _has(df, "到店数量"):
        summary["总到店数量"] = _safe_sum(df["到店数量"])
    if _has(df, "成交人数"):
        summary["总成交人数"] = _safe_sum(df["成交人数"])
    if _has(df, "销售额"):
        summary["总销售额"] = _safe_sum(df["销售额"])

    # ---------- 均值与整体转化率（用总量相除，避免加权口径偏差） ----------
    if "总销售额" in summary and "总成交人数" in summary:
        summary["平均客单价"] = safe_div(summary["总销售额"], summary["总成交人数"]).round(DECIMAL_PLACES)
    if "总到店数量" in summary and "总获客数量" in summary:
        summary["整体到店转化率"] = safe_div(summary["总到店数量"], summary["总获客数量"]).round(DECIMAL_PLACES)
    if "总成交人数" in summary and "总到店数量" in summary:
        summary["整体成交转化率"] = safe_div(summary["总成交人数"], summary["总到店数量"]).round(DECIMAL_PLACES)

    # ---------- 渠道结构（渠道列存在时） ----------
    present_channels = [col for col in CHANNEL_FIELDS if _has(df, col)]
    if present_channels:
        if _has(df, "获客数量"):
            hk_total = _safe_sum(df["获客数量"])
        else:
            hk_total = _safe_sum(df[present_channels].sum(axis=1))
        for ch in present_channels:
            ch_sum = _safe_sum(df[ch])
            summary[f"{ch}总获客"] = ch_sum
            summary[f"{ch}获客占比"] = safe_div(ch_sum, hk_total).round(DECIMAL_PLACES)
        # 优质渠道总占比
        quality_present = [col for col in QUALITY_CHANNELS if _has(df, col)]
        if quality_present:
            quality_sum = _safe_sum(df[quality_present].sum(axis=1))
            summary["优质渠道总占比"] = safe_div(quality_sum, hk_total).round(DECIMAL_PLACES)

    # ---------- 客群结构（客群列存在时） ----------
    if "总成交人数" in summary:
        present_customers = [col for col in CUSTOMER_FIELDS if _has(df, col)]
        for fc in present_customers:
            fc_sum = _safe_sum(df[fc])
            summary[f"{fc}总数"] = fc_sum
            summary[f"{fc}占比"] = safe_div(fc_sum, summary["总成交人数"]).round(DECIMAL_PLACES)

    logger.debug("大盘指标计算完成：%d 项", len(summary))
    return summary
