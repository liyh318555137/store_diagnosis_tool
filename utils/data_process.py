# -*- coding: utf-8 -*-
"""
数据导入与预处理模块

功能说明：
    - load_data：读取上传的门店运营数据文件（CSV / XLSX），带编码回退与格式校验
    - build_sample_data：生成内置示例数据（10 家模拟门店，含少量异常用于演示）
    - suggest_mapping：根据列名自动推荐「文件列 → 标准字段」的映射
    - map_columns：按映射表抽取并重命名标准字段列
    - clean_data：数据清洗与异常检测（转数字、去空行、自动计算客单价、口径修正、
      标记负数 / 转化率超 100% 等）

标准字段（5 个输入字段，唯一来源：utils/config.py）：
    门店名称、获客数量、到店数量、成交人数、销售额
客单价为派生字段：清洗阶段按 销售额 / 成交人数 自动计算（成交人数为 0 时赋值为 0，避免除零异常）
"""

import logging

import numpy as np
import pandas as pd

from . import config as cfg
from . import metrics as metrics_mod

logger = logging.getLogger(__name__)

# ---------- 标准字段（唯一来源：utils/config.py） ----------
# 5 个输入标准字段，界面与下游分析统一使用；
# 客单价为派生字段，不参与上传与映射，清洗阶段自动计算
STANDARD_FIELDS = cfg.STANDARD_FIELDS

# 需要转换为数值的字段：从标准字段自动派生（去掉文本字段「门店名称」），
# 新增文本型标准字段时无需手工维护本清单
NUMERIC_FIELDS = [f for f in cfg.STANDARD_FIELDS if f != "门店名称"]

# ---------- 固定上传字段的别名映射（业务字段名 → 引擎标准字段名，见 config.py） ----------
# 上传文件中出现左侧列名时，读取后自动标准化为右侧标准名，
# 使渠道 / 客群指标计算与分层模型无需感知业务命名差异。
FIELD_ALIASES = cfg.FIELD_ALIASES

# 除标准字段外自动保留的附加列（渠道 / 客群 / 描述字段，见 config.py）
EXTRA_COLUMNS = (
    cfg.CHANNEL_FIELDS
    + cfg.CUSTOMER_FIELDS
    + cfg.DESCRIPTIVE_FIELDS
)

# 上传文件大小上限（见 config.py）
MAX_FILE_SIZE = cfg.MAX_FILE_SIZE

# 映射下拉框中「不导入」选项的占位文案（见 config.py）
NOT_IMPORTED = cfg.NOT_IMPORTED


def load_data(uploaded_file) -> pd.DataFrame:
    """
    读取上传的数据文件为 DataFrame。

    参数：
        uploaded_file: Streamlit 上传文件对象（CSV / XLSX）

    返回：
        pd.DataFrame: 解析后的原始数据

    异常：
        文件格式不支持 / 内容损坏时抛出带中文说明的异常，
        由界面层捕获并友好提示。
    """
    # 根据文件后缀选择对应的读取方式
    file_name = uploaded_file.name.lower()

    if file_name.endswith(".csv"):
        # CSV 文件优先按 UTF-8 编码读取，失败时回退 GBK（常见于国内导出的文件）
        try:
            df = pd.read_csv(uploaded_file, encoding="utf-8")
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            try:
                df = pd.read_csv(uploaded_file, encoding="gbk")
            except Exception:
                raise ValueError("CSV 文件编码无法识别，请另存为 UTF-8 编码后重试")
    elif file_name.endswith(".xlsx"):
        # Excel 文件使用 openpyxl 引擎读取
        try:
            df = pd.read_excel(uploaded_file, engine="openpyxl")
        except Exception as e:
            raise ValueError(f"Excel 文件读取失败，请确认文件未损坏且为 .xlsx 格式：{e}")
    else:
        raise ValueError("暂不支持该文件格式，请上传 CSV 或 XLSX 文件")

    # 空文件检查
    if df is None or df.empty:
        raise ValueError("文件中没有可用的数据行，请检查文件内容")

    # 字段名标准化：固定业务字段名 → 引擎标准字段名（渠道 / 客群别名映射）
    df = standardize_columns(df)

    return df


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    将固定业务字段名标准化为引擎标准字段名（见 FIELD_ALIASES）。
    已存在标准化列名或未知列名不受影响，可安全重复调用。
    """
    rename_map = {k: v for k, v in FIELD_ALIASES.items() if k in df.columns}
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def build_sample_data(n: int = 10) -> pd.DataFrame:
    """
    生成内置示例数据：10 家模拟门店（列名即标准字段）。

    故意在数据中埋入 2 处异常，用于演示清洗与异常标记效果：
        - 1 家门店销售额为负数
        - 1 家门店成交人数 > 到店数量（转化率超 100%）

    参数：
        n: 门店数量（默认 10）

    返回：
        pd.DataFrame: 示例门店数据
    """
    # 固定随机种子，保证每次生成的示例数据一致
    rng = np.random.default_rng(42)

    store_names = [
        "北京朝阳店", "北京海淀店", "上海静安店", "上海徐汇店", "广州天河店",
        "深圳南山店", "杭州西湖店", "成都春熙店", "武汉江汉店", "南京新街口店",
    ]

    # 生成符合业务量级的模拟数据：获客 → 到店 → 成交 → 销售额
    hk = rng.integers(800, 3000, n)                          # 获客数量
    dd = (hk * rng.uniform(0.45, 0.90, n)).astype(int)       # 到店数量（到店率 45%~90%）
    cj = (dd * rng.uniform(0.20, 0.55, n)).astype(int)       # 成交人数（成交率 20%~55%）
    xse = (cj * rng.uniform(280, 1100, n)).round(1)          # 销售额
    # 客单价为派生字段，不入样例数据，由清洗阶段自动计算

    sample_df = pd.DataFrame({
        "门店名称": store_names[:n],
        "获客数量": hk,
        "到店数量": dd,
        "成交人数": cj,
        "销售额": xse,
    })

    # 埋入演示用异常：负销售额
    sample_df.loc[n - 3, "销售额"] = -8520.5
    # 埋入演示用异常：成交人数大于到店数量（成交转化率超 100%）
    sample_df.loc[n - 2, "成交人数"] = sample_df.loc[n - 2, "到店数量"] + 30

    return sample_df


def suggest_mapping(columns) -> dict:
    """
    根据文件列名自动推荐「标准字段 → 源列」映射。

    匹配规则：源列名包含标准字段的关键字（忽略大小写），
    每个源列最多被映射一次。

    参数：
        columns: 文件的实际列名列表

    返回：
        dict: {标准字段: 源列名 或 None（未找到推荐）}
    """
    # 标准字段对应的列名关键字
    rules = {
        "门店名称": ["门店", "店名", "店铺", "名称"],
        "获客数量": ["获客"],
        "到店数量": ["到店", "进店", "客流"],
        "成交人数": ["成交"],
        "销售额": ["销售", "营业额", "营收"],
    }

    used_columns = set()  # 已被映射的源列，避免一列多用
    suggestion = {}
    for std_field, keywords in rules.items():
        # 1. 精确匹配优先（列名与标准字段完全一致）
        match = next(
            (str(col) for col in columns
             if str(col) == std_field and str(col) not in used_columns),
            None,
        )
        # 2. 关键字匹配（如「店名」→ 门店名称），避免与同名渠道列混淆
        if match is None:
            for col in columns:
                col_str = str(col)
                if col_str in used_columns:
                    continue
                if any(keyword.lower() in col_str.lower() for keyword in keywords):
                    match = col_str
                    break
        if match is not None:
            used_columns.add(match)
        suggestion[std_field] = match

    return suggestion


def map_columns(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """
    按映射表将文件列转换为标准字段列，并自动保留扩展字段。

    参数：
        df: 原始数据
        mapping: {标准字段: 源列名 或 None}，由界面下拉框生成

    返回：
        pd.DataFrame: 标准字段列 + 自动附加的扩展字段列
            （渠道字段 / 客群字段 / 描述字段：门店类型、门店店长等）
    """
    # 收集被映射的源列（同一源列映射到多个标准字段时只取第一次）
    used_sources, rename_map = [], {}
    for std_field, src_col in mapping.items():
        if src_col is None or src_col == NOT_IMPORTED:
            continue
        if src_col in used_sources or src_col not in df.columns:
            continue
        used_sources.append(src_col)
        rename_map[src_col] = std_field

    # 自动保留扩展字段：已标准化的渠道 / 客群 / 描述字段列（未被显式映射的）
    extra_sources = [
        col for col in EXTRA_COLUMNS
        if col in df.columns and col not in used_sources
    ]

    # 未映射任何字段且无扩展字段时返回空表
    if not used_sources and not extra_sources:
        return df.iloc[0:0].copy()

    # 抽取源列并重命名为标准字段名，再附加扩展字段（保持标准字段在前）
    result = df[used_sources + extra_sources].rename(columns=rename_map)
    return result


def _get_store_name(df: pd.DataFrame, idx) -> str:
    """获取指定行（原始索引）的门店名称，供异常记录使用。"""
    if "门店名称" in df.columns:
        value = df.loc[idx, "门店名称"]
        if pd.notna(value):
            return str(value)
    return "（空）"


def clean_data(df: pd.DataFrame):
    """
    数据清洗与异常检测：
        1. 去除门店名称为空的行
        2. 数值字段统一转换为数字（无法转换的置为空并记录异常）
        3. 自动计算客单价 = 销售额 / 成交人数（成交人数为 0 时赋值为 0，避免除零）
        4. 口径修正：成交人数 > 到店数量（或到店数量 > 获客数量）时自动
           修正到店数量，保证到店率 / 到店转化率计算结果最大为 100%，
           修正记录写入新增的「数据异常标记」列，正常行留空
        5. 标记异常值：负数、成交转化率超 100%、到店转化率超 100%
        6. 为每行增加「异常标记」与「数据异常标记」列

    参数：
        df: 映射后的标准字段数据

    返回：
        (cleaned_df, issues_df):
            cleaned_df - 清洗后的数据（含「异常标记」列）
            issues_df  - 异常明细表（行号 / 门店名称 / 字段 / 问题 / 说明）
    """
    df = df.copy()
    issues = []  # 异常记录列表

    # ---------- 1. 去空行：门店名称为空的行直接删除 ----------
    if "门店名称" in df.columns:
        name_str = df["门店名称"].astype(str).str.strip()
        empty_mask = df["门店名称"].isna() | (name_str == "") | (name_str.str.lower() == "nan")
        for idx in df.index[empty_mask]:
            issues.append({
                "行号": int(idx) + 1,           # 展示为原始数据中的行（1 起）
                "门店名称": "（空）",
                "字段": "门店名称",
                "问题": "门店名称为空",
                "说明": "该行门店名称缺失，已整行删除",
            })
        df = df[~empty_mask]

    # ---------- 2. 数值字段转数字 ----------
    for col in NUMERIC_FIELDS:
        if col not in df.columns:
            continue
        raw = df[col]
        df[col] = pd.to_numeric(df[col], errors="coerce")

        # 原值为非空文本但转换失败 → 置为空并记录异常
        raw_str = raw.astype(str).str.strip()
        bad_mask = (
            df[col].isna()
            & raw.notna()
            & (raw_str != "")
            & (raw_str.str.lower() != "nan")
        )
        for idx in df.index[bad_mask]:
            issues.append({
                "行号": int(idx) + 1,
                "门店名称": _get_store_name(df, idx),
                "字段": col,
                "问题": "数值格式错误",
                "说明": f"「{raw.loc[idx]}」无法转换为数字，已置为空值",
            })

        # 无穷值（inf / -inf）视为异常数值：置空并记录，避免下游计算与展示异常
        inf_mask = df[col].isin([np.inf, -np.inf])
        for idx in df.index[inf_mask]:
            issues.append({
                "行号": int(idx) + 1,
                "门店名称": _get_store_name(df, idx),
                "字段": col,
                "问题": "数值异常（无穷值）",
                "说明": f"{col}为无穷值（{df.loc[idx, col]}），已置为空值",
            })
        if inf_mask.any():
            df.loc[inf_mask, col] = np.nan

    # ---------- 3. 客单价自动计算（派生字段，无需用户上传与映射） ----------
    # 客单价 = 销售额 / 成交人数；兜底：成交人数为 0（或数据缺失）时赋值为 0，避免除零异常
    if "销售额" in df.columns and "成交人数" in df.columns:
        df["客单价"] = metrics_mod.safe_div(df["销售额"], df["成交人数"]).fillna(0).round(2)

    # ---------- 4. 口径修正：自动修复到店转化率超 100% 的数据 ----------
    # 修正规则（顺序不可颠倒，保证到店率 / 到店转化率计算结果最大为 100%）：
    #   ① 成交人数 > 到店数量：成交转化率（成交 / 到店）超 100% → 到店数量修正为成交人数
    #   ② 到店数量 > 获客数量：到店转化率（到店 / 获客）超 100% → 到店数量修正为获客数量
    # 必须 ① 在前、② 在后：若先执行 ②，遇到「成交人数 > 获客数量」的极端脏数据时，
    # 到店数量会被修正到获客数量之上，破坏「到店转化率 ≤ 100%」的保证
    # 修正过的行写入「数据异常标记」列，正常行留空；后续异常检测不再重复标记
    corrections = {}  # {行索引: [修正标记, ...]}
    if "成交人数" in df.columns and "到店数量" in df.columns:
        fix_mask = df["成交人数"] > df["到店数量"]
        if fix_mask.any():
            df.loc[fix_mask, "到店数量"] = df.loc[fix_mask, "成交人数"]
            for idx in df.index[fix_mask]:
                corrections.setdefault(idx, []).append("到店数修正（成交>到店）")
    if "获客数量" in df.columns and "到店数量" in df.columns:
        fix_mask = df["到店数量"] > df["获客数量"]
        if fix_mask.any():
            df.loc[fix_mask, "到店数量"] = df.loc[fix_mask, "获客数量"]
            for idx in df.index[fix_mask]:
                corrections.setdefault(idx, []).append("到店数修正（到店>获客）")

    # ---------- 5. 异常检测：负数 ----------
    for col in NUMERIC_FIELDS:
        if col not in df.columns:
            continue
        for idx in df.index[df[col] < 0]:
            issues.append({
                "行号": int(idx) + 1,
                "门店名称": _get_store_name(df, idx),
                "字段": col,
                "问题": "数值为负",
                "说明": f"{col}为负数（{df.loc[idx, col]}），请核实数据来源",
            })

    # ---------- 6. 异常检测：转化率超 100% ----------
    if "成交人数" in df.columns and "到店数量" in df.columns:
        # 成交转化率 = 成交人数 / 到店数量，大于 1 即为异常
        mask = df["成交人数"] > df["到店数量"]
        # 比率用安全除法计算（分母为 0 时返回 NaN，避免除零警告与 inf% 显示）
        conv_rate = metrics_mod.safe_div(df["成交人数"], df["到店数量"])
        for idx in df.index[mask]:
            rate_val = conv_rate.loc[idx]
            rate_txt = f"{rate_val:.1%}" if pd.notna(rate_val) else "无法计算（到店数量为 0）"
            issues.append({
                "行号": int(idx) + 1,
                "门店名称": _get_store_name(df, idx),
                "字段": "成交人数 / 到店数量",
                "问题": "转化率超100%",
                "说明": f"成交人数（{df.loc[idx, '成交人数']}）大于到店数量（{df.loc[idx, '到店数量']}），"
                        f"成交转化率 {rate_txt} 超 100%",
            })

    if "到店数量" in df.columns and "获客数量" in df.columns:
        # 到店转化率 = 到店数量 / 获客数量，大于 1 即为异常
        mask = df["到店数量"] > df["获客数量"]
        dd_rate = metrics_mod.safe_div(df["到店数量"], df["获客数量"])
        for idx in df.index[mask]:
            rate_val = dd_rate.loc[idx]
            rate_txt = f"{rate_val:.1%}" if pd.notna(rate_val) else "无法计算（获客数量为 0）"
            issues.append({
                "行号": int(idx) + 1,
                "门店名称": _get_store_name(df, idx),
                "字段": "到店数量 / 获客数量",
                "问题": "转化率超100%",
                "说明": f"到店数量（{df.loc[idx, '到店数量']}）大于获客数量（{df.loc[idx, '获客数量']}），"
                        f"到店转化率 {rate_txt} 超 100%",
            })

    # ---------- 7. 组装「异常标记」与「数据异常标记」列 ----------
    issue_by_row = {}  # {行索引: [问题描述, ...]}
    for issue in issues:
        issue_by_row.setdefault(issue["行号"] - 1, []).append(f"{issue['字段']}：{issue['问题']}")

    df["异常标记"] = [
        "；".join(issue_by_row.get(idx, [])) for idx in df.index
    ]
    # 数据异常标记：仅记录口径修正过的行，正常行留空
    df["数据异常标记"] = [
        "；".join(corrections.get(idx, [])) for idx in df.index
    ]

    # 汇总异常明细表
    issues_df = pd.DataFrame(issues, columns=["行号", "门店名称", "字段", "问题", "说明"])

    logger.debug(
        "数据清洗完成：%d 行（口径修正 %d 行，异常记录 %d 条）",
        len(df), len(corrections), len(issues),
    )
    return df, issues_df
