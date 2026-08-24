# -*- coding: utf-8 -*-
"""
门店分层诊断模块 —— 二级分层模型

==================== 一级：综合分层（五维加权） ====================
维度与权重：
    营收规模 25% | 获客能力 20% | 转化效率 25% | 客群质量 15% | 渠道健康度 15%

算法：
    1. 每个维度选取可用指标（缺失指标自动跳过；维度内全部缺失则维度失效）
    2. 指标 min-max 标准化到 [0,1]（全空或同值列取中性 0.5，避免除零）
    3. 维度得分 = 该维度可用指标标准化值的均值（门店级全缺失取中性 0.5）
    4. 综合得分 = Σ(维度得分 × 有效权重) × 100（0-100 分制）

分级规则（按综合得分降序排名）：
    S 级前 20% | A 级 20%-50% | B 级 50%-80% | C 级后 20%

兼容逻辑：
    客群 / 渠道字段整体缺失时对应维度自动失效，
    剩余维度权重按比例重新分配，保证合计 100%。

==================== 二级：标签画像 ====================
渠道标签：
    最高渠道占比 > 40% → 对应「XX驱动型」；有效渠道数 ≤ 2 → 「渠道单一型」
客群标签：
    老客占比 > 40% → 「老客复购型」；客单价 > 全店均值 ×1.5 → 「高净值型」
    转化率低于中位数且获客高于中位数 → 「泛客流低效型」
问题标签：
    获客不足 / 转化低效 / 客单偏低（与全店中位数比较）
    渠道畸形（有效渠道 ≤ 1 或 最高渠道占比 > 70%）

输出列：
    各维度得分、综合得分（0-100）、综合排名、门店等级、
    渠道标签、客群标签、问题标签

鲁棒性：
    - 空表、单店、字段缺失、指标全空均不报错
    - 全部算法参数可配置（维度/权重/分级比例/标签阈值，唯一来源：utils/config.py）
"""

import logging

import numpy as np
import pandas as pd

from . import config as cfg

logger = logging.getLogger(__name__)

# ==================== 可配置项（唯一来源：utils/config.py） ====================
# 五维配置 / 分级分界 / 标签阈值 / 渠道简称映射全部在 config.py 中定义，
# 调整维度权重与阈值只改 config.py（validate_config 会自动校验一致性），
# 此处仅绑定短名供本模块使用，保证单一事实源。
DEFAULT_DIMENSIONS = cfg.DIMENSIONS
DEFAULT_GRADE_RATIOS = cfg.GRADE_RATIOS
GRADE_LABELS = cfg.GRADE_LABELS
DEFAULT_TAG_THRESHOLDS = cfg.TAG_THRESHOLDS

# 渠道占比列名 → 标签中的渠道简称（唯一来源：config.py）
CHANNEL_NAME_MAP = cfg.CHANNEL_NAME_MAP

# 分层输出的新增列（保证各场景下列结构一致；维度得分列随 DIMENSIONS 自动派生，
# 修改 config 中的维度后无需手工维护本清单）
OUTPUT_COLUMNS = (
    [f"{dim['name']}得分" for dim in cfg.DIMENSIONS]
    + ["综合得分", "综合排名", "门店等级", "渠道标签", "客群标签", "问题标签"]
)


# ==================== 工具函数 ====================
def _minmax(series: pd.Series) -> pd.Series:
    """min-max 标准化到 [0,1]；全空或同值列返回中性 0.5（避免除零）。"""
    s = pd.to_numeric(series, errors="coerce").astype(float)
    vmin, vmax = s.min(), s.max()
    if pd.isna(vmin) or pd.isna(vmax) or vmax == vmin:
        return pd.Series(0.5, index=s.index)
    return (s - vmin) / (vmax - vmin)


def _dimension_score(df: pd.DataFrame, dim: dict):
    """
    计算单个维度的得分（0-1）：
        可用指标 min-max 标准化后取均值；维度内全部指标缺失时返回 None（维度失效）。

    参数：
        df: 门店指标表
        dim: 维度配置 {name, weight, indicators}

    返回：
        pd.Series: 维度得分；维度失效返回 None
    """
    # 仅保留「列存在且有有效数据」的候选指标
    usable = [
        ind for ind in dim["indicators"]
        if ind in df.columns and df[ind].notna().any()
    ]
    if not usable:
        return None
    # 各指标标准化后按行取均值（忽略门店级缺失），全缺失的门店取中性 0.5
    norm = pd.concat([_minmax(df[ind]) for ind in usable], axis=1)
    return norm.mean(axis=1).fillna(0.5)


def _rate_column(df: pd.DataFrame):
    """返回第一个可用的转化率列名（成交转化率优先，其次总转化率）；均无则 None。"""
    for col in ["成交转化率", "总转化率"]:
        if col in df.columns and df[col].notna().any():
            return col
    return None


def _grade_stores(scores: pd.Series, grade_ratios: list, grade_labels: list) -> pd.Series:
    """
    按综合得分降序排名分档（分界点与等级标签均可配置）。

    参数：
        scores: 综合得分（含 NaN）
        grade_ratios: 分级分界点列表，如 [0.2, 0.5, 0.8] 表示 4 档
        grade_labels: 等级标签列表，长度须为 len(grade_ratios) + 1

    返回：
        pd.Series: 门店等级；得分为空的行标记「未诊断」
    """
    n = len(scores)
    grades = pd.Series("未诊断", index=scores.index)
    valid = scores.notna()
    if not valid.any():
        return grades
    if n == 1:
        # 单店场景分级无意义，直接标记为最高档
        grades[valid] = grade_labels[0]
        return grades

    # 排名百分比（min 方法：并列同分同名次），仅对有效得分分级
    rank = scores[valid].rank(ascending=False, method="min")
    pct = rank / n
    # 按分界点动态生成分级条件，支持任意档位配置
    conditions = [pct <= r for r in grade_ratios]
    grades[valid] = np.select(conditions, grade_labels[:-1], default=grade_labels[-1])
    return grades


# ==================== 二级：标签 ====================
def _channel_tags(df: pd.DataFrame, thresholds: dict) -> pd.Series:
    """
    渠道标签：最高占比超阈值 → 对应驱动型；有效渠道数 ≤ 上限 → 渠道单一型。
    无渠道数据时返回空标签。
    """
    ratio_cols = [f"{ch}占比" for ch in cfg.CHANNEL_FIELDS if f"{ch}占比" in df.columns]
    if not ratio_cols:
        return pd.Series("", index=df.index)

    def _tags(row):
        # 有效渠道：占比有效且 > 0
        valid = {col: row[col] for col in ratio_cols if pd.notna(row[col]) and row[col] > 0}
        if not valid:
            return ""
        tags = []
        # 驱动型：最高占比超过阈值
        top_col = max(valid, key=valid.get)
        if valid[top_col] > thresholds["channel_drive_ratio"]:
            ch_name = top_col.replace("占比", "")
            tags.append(f"{CHANNEL_NAME_MAP.get(ch_name, ch_name)}驱动型")
        # 单一型：有效渠道数不超过上限
        if len(valid) <= thresholds["channel_single_max"]:
            tags.append("渠道单一型")
        return "；".join(tags)

    return df.apply(_tags, axis=1)


def _customer_tags(df: pd.DataFrame, thresholds: dict) -> pd.Series:
    """
    客群标签：老客复购型 / 高净值型 / 泛客流低效型。
    缺少对应字段时自动跳过，不会报错。
    """
    rate_col = _rate_column(df)
    hk_col = "获客数量" if "获客数量" in df.columns else None
    price_col = "客单价" if "客单价" in df.columns else None

    # 全店统计阈值（中位数 / 均值）
    rate_median = df[rate_col].median() if rate_col else np.nan
    hk_median = df[hk_col].median() if hk_col else np.nan
    price_mean = df[price_col].mean() if price_col else np.nan

    def _tags(row):
        tags = []
        # 老客复购型：老客成交占比超阈值
        old_ratio = row.get("老客成交数占比")
        if pd.notna(old_ratio) and old_ratio > thresholds["old_customer_ratio"]:
            tags.append("老客复购型")
        # 高净值型：客单价超全店均值若干倍
        price = row.get(price_col) if price_col else np.nan
        if pd.notna(price) and pd.notna(price_mean) and price > price_mean * thresholds["high_value_multiple"]:
            tags.append("高净值型")
        # 泛客流低效型：转化率低于中位数 且 获客高于中位数
        rate = row.get(rate_col) if rate_col else np.nan
        hk = row.get(hk_col) if hk_col else np.nan
        if (pd.notna(rate) and pd.notna(rate_median) and rate < rate_median
                and pd.notna(hk) and pd.notna(hk_median) and hk > hk_median):
            tags.append("泛客流低效型")
        return "；".join(tags)

    return df.apply(_tags, axis=1)


def _issue_tags(df: pd.DataFrame, thresholds: dict) -> pd.Series:
    """
    问题标签：获客不足 / 转化低效 / 客单偏低 / 渠道畸形。
    所有比较基于全店中位数（对极值更鲁棒），字段缺失自动跳过。
    """
    rate_col = _rate_column(df)
    hk_col = "获客数量" if "获客数量" in df.columns else None
    price_col = "客单价" if "客单价" in df.columns else None
    ratio_cols = [f"{ch}占比" for ch in cfg.CHANNEL_FIELDS if f"{ch}占比" in df.columns]

    rate_median = df[rate_col].median() if rate_col else np.nan
    hk_median = df[hk_col].median() if hk_col else np.nan
    price_median = df[price_col].median() if price_col else np.nan

    def _tags(row):
        tags = []
        # 获客不足：获客数量低于全店中位数
        hk = row.get(hk_col) if hk_col else np.nan
        if pd.notna(hk) and pd.notna(hk_median) and hk < hk_median:
            tags.append("获客不足")
        # 转化低效：转化率低于全店中位数
        rate = row.get(rate_col) if rate_col else np.nan
        if pd.notna(rate) and pd.notna(rate_median) and rate < rate_median:
            tags.append("转化低效")
        # 客单偏低：客单价低于全店中位数
        price = row.get(price_col) if price_col else np.nan
        if pd.notna(price) and pd.notna(price_median) and price < price_median:
            tags.append("客单偏低")
        # 渠道畸形：有效渠道 ≤ 上限 或 最高占比超阈值
        if ratio_cols:
            valid = [row[c] for c in ratio_cols if pd.notna(row[c]) and row[c] > 0]
            if valid and (len(valid) <= thresholds["channel_malformed_max"]
                          or max(valid) > thresholds["channel_malformed_ratio"]):
                tags.append("渠道畸形")
        return "；".join(tags)

    return df.apply(_tags, axis=1)


# ==================== 主函数 ====================
def leveling_stores(
    metric_df: pd.DataFrame,
    dimensions: list = None,
    grade_ratios: list = None,
    grade_labels: list = None,
    tag_thresholds: dict = None,
) -> pd.DataFrame:
    """
    门店二级分层：一级五维加权综合得分 + 分级，二级标签画像。

    参数：
        metric_df: 门店指标表（calc_basic_metrics 产出）
        dimensions: 维度配置（默认五维），可传入自定义配置
        grade_ratios: 分级分界点（默认 [0.2, 0.5, 0.8]）
        grade_labels: 等级标签（默认 S/A/B/C，须与分界点配套）
        tag_thresholds: 标签阈值（默认见 DEFAULT_TAG_THRESHOLDS）

    返回：
        pd.DataFrame: 原指标列 + 各维度得分 + 综合得分 + 综合排名 + 门店等级 + 三类标签
    """
    dimensions = dimensions or DEFAULT_DIMENSIONS
    grade_ratios = grade_ratios or DEFAULT_GRADE_RATIOS
    grade_labels = grade_labels or GRADE_LABELS
    tag_thresholds = tag_thresholds or DEFAULT_TAG_THRESHOLDS

    # 分级标签与分界点配套校验：数量不匹配时按 GRADE_LABELS 前缀自动适配
    if len(grade_labels) != len(grade_ratios) + 1:
        grade_labels = list(GRADE_LABELS[: len(grade_ratios)]) + [GRADE_LABELS[-1]]

    result = metric_df.copy()

    # ---------- 空表保护：补齐输出列后直接返回 ----------
    if result.empty:
        for col in OUTPUT_COLUMNS:
            result[col] = pd.NA
        return result

    # ---------- 一级：维度得分与权重重分配 ----------
    dim_scores, valid_dims = {}, []
    for dim in dimensions:
        score = _dimension_score(result, dim)
        if score is not None:
            dim_scores[dim["name"]] = score
            valid_dims.append(dim)

    logger.debug(
        "分层维度有效 %d/%d：%s",
        len(valid_dims), len(dimensions),
        "、".join(dim["name"] for dim in valid_dims) or "（全部失效，输出中性得分）",
    )

    # 权重重分配：有效维度权重按比例放大，保证合计 = 1（兼容字段缺失）
    total_weight = sum(dim["weight"] for dim in valid_dims)
    if total_weight == 0:
        # 所有维度失效（数据完全不可用）→ 中性得分，等级未诊断
        result["综合得分"] = 50.0
        grades = pd.Series("未诊断", index=result.index)
    else:
        # 写入各维度得分列（0-1 标准化值）
        for dim in valid_dims:
            result[f'{dim["name"]}得分'] = dim_scores[dim["name"]].round(2)
        effective_weights = {dim["name"]: dim["weight"] / total_weight for dim in valid_dims}
        # 综合得分 = Σ(维度得分 × 有效权重) × 100
        total_score = sum(dim_scores[name] * weight for name, weight in effective_weights.items())
        result["综合得分"] = (total_score * 100).round(2)
        # 分档
        grades = _grade_stores(result["综合得分"], grade_ratios, grade_labels)

    result["门店等级"] = grades
    # 综合排名（1 为最优；得分为空的门店排名为空）
    result["综合排名"] = result["综合得分"].rank(ascending=False, method="min").astype("Int64")

    # ---------- 二级：标签画像 ----------
    result["渠道标签"] = _channel_tags(result, tag_thresholds)
    result["客群标签"] = _customer_tags(result, tag_thresholds)
    result["问题标签"] = _issue_tags(result, tag_thresholds)

    logger.debug("分层完成，等级分布：%s", result["门店等级"].value_counts().to_dict())
    return result
