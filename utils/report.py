# -*- coding: utf-8 -*-
"""
诊断报告生成与展示模块 —— 运营大盘

页面结构（自上而下）：
    1. 顶部：4 个核心 KPI 卡片（总销售额、总获客、整体成交转化率、平均客单价）
    2. 第二行：扩展指标卡片（渠道数量、优质渠道占比、老客成交占比，无数据自动隐藏）
    3. 图表区 2×2：
        - 左上：转化漏斗图（获客 → 到店 → 成交）
        - 右上：整体获客渠道结构饼图
        - 左下：销售额 Top5 门店柱状图
        - 右下：获客转化率 Top5 门店柱状图
    4. 底部：全部门店核心指标明细表（含「门店等级」预留位）
    5. 二、门店多级分层结果：筛选 / 等级统计 / 图表 / 明细表 / 导出
    6. 三、单门店画像诊断：下拉选店 → 基础信息卡片 / 五维雷达图 / 渠道饼图 /
       关键指标对比卡片 / 自动诊断结论与建议（全部联动实时刷新）

兼容性：
    - 渠道 / 客群字段未映射时，对应卡片与图表自动隐藏，只展示基础指标，不报错
    - 全部图表统一深蓝色商务配色
    - 自动诊断规则引擎（get_store_diagnosis / get_overall_summary）：单店与大盘诊断，
      全部判定基于与全量数据整体均值的对比，指标缺失（0 / 空）时自动跳过对应判断，不报错
    - 规则 / 建议库 / 配色等业务参数唯一来源为 utils/config.py（换业态只改配置）
"""

import html
import json
import logging
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit.components.v1 import html as st_html

from . import config as cfg
from . import metrics as metrics_mod

logger = logging.getLogger(__name__)

# ==================== 业务参数与配色（唯一来源：utils/config.py） ====================
# 诊断规则 / 建议库 / 字段体系 / 配色全部在 config.py 中定义，换业态只改 config.py；
# 此处仅绑定短名供展示层使用（函数体保持引用短名，行为不变），保证单一事实源。
PRIMARY_BLUE = cfg.PRIMARY_BLUE   # 主深蓝（标题 / 表头 / 卡片描边）
BLUE_600 = cfg.BLUE_600           # 深蓝辅助
BLUE_500 = cfg.BLUE_500           # 中蓝（主系列色）
BLUE_400 = cfg.BLUE_400           # 浅蓝
BLUE_300 = cfg.BLUE_300           # 极浅蓝（网格 / 分隔线）
INK = cfg.INK                     # 正文
MUTED_TEXT = cfg.MUTED_TEXT       # 次要文字（卡片标签）
FAINT_TEXT = cfg.FAINT_TEXT       # 弱文字（占比说明）
CARD_BORDER = cfg.CARD_BORDER     # 卡片边框
TABLE_BORDER = cfg.TABLE_BORDER   # 表格行分隔线
ROW_ALT_BG = cfg.ROW_ALT_BG       # 表格斑马纹
ROW_HOVER_BG = cfg.ROW_HOVER_BG   # 表格悬停底色
GRADE_COLORS = cfg.GRADE_COLORS   # 等级徽章配色（S 金 / A 绿 / B 蓝 / C 红）
GRADE_LABELS = cfg.GRADE_LABELS
CHANNEL_PIE_COLORS = cfg.CHANNEL_PIE_COLORS
TAG_BLUE_BG = cfg.TAG_BLUE_BG
TAG_BLUE_TEXT = cfg.TAG_BLUE_TEXT
TAG_BLUE_BORDER = cfg.TAG_BLUE_BORDER
TAG_RED_BG = cfg.TAG_RED_BG
TAG_RED_TEXT = cfg.TAG_RED_TEXT
TAG_RED_BORDER = cfg.TAG_RED_BORDER
DELTA_UP = cfg.DELTA_UP           # 对比差异颜色（高）
DELTA_DOWN = cfg.DELTA_DOWN       # 对比差异颜色（低）
DELTA_NEUTRAL = cfg.DELTA_NEUTRAL  # 对比差异颜色（持平）
CHANNEL_FIELDS = cfg.CHANNEL_FIELDS
CHANNEL_NAME_MAP = cfg.CHANNEL_NAME_MAP

# 明细表中的比率列（显示时转换为百分比）
RATE_COLUMNS = ["到店转化率", "成交转化率", "总转化率"]

# 明细表核心列（按业务顺序排列，仅展示实际存在的列）
TABLE_COLUMNS = [
    "门店名称", "销售额", "获客数量", "到店数量", "成交人数", "客单价",
    "到店转化率", "成交转化率", "总转化率", "门店等级",
]


# ==================== 数据工具 ====================
def _column_total(df: pd.DataFrame, col: str) -> float:
    """返回指定列的总量；列不存在或全为空时返回 NaN。"""
    if col not in df.columns or not df[col].notna().any():
        return float("nan")
    return float(df[col].sum())


def _fmt_number(value: float) -> str:
    """数值格式化：NaN / 无穷显示为 --，否则保留千分位。"""
    if value is None or pd.isna(value) or math.isinf(value):
        return "--"
    return f"{value:,.0f}"


def _fmt_percent(value: float) -> str:
    """百分比格式化：NaN / 无穷显示为 --，否则保留 1 位小数百分比。"""
    if value is None or pd.isna(value) or math.isinf(value):
        return "--"
    return f"{value:.1%}"


def _has_data(df: pd.DataFrame, col: str) -> bool:
    """列存在且有有效数据（至少一个非 NaN 值）。"""
    return col in df.columns and df[col].notna().any()


def _style_figure(fig, title: str, height: int = 340):
    """统一图表样式：深蓝标题、去网格底、商务配色。"""
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=PRIMARY_BLUE)),
        height=height,
        margin=dict(l=10, r=10, t=55, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=12),
        showlegend=False,
    )
    return fig


# ==================== 报告渲染入口 ====================
def render_report(level_df: pd.DataFrame):
    """
    渲染分析诊断页完整报告（运营大盘）。

    参数：
        level_df: 已附加「门店等级」的指标表（calc_basic_metrics → leveling_stores）
    """
    logger.debug("开始渲染诊断报告：%d 家门店", len(level_df))
    st.subheader("一、运营大盘")

    # ---------- 1. 顶部：4 个核心 KPI 卡片 ----------
    _render_core_kpi_cards(level_df)

    # ---------- 2. 第二行：扩展指标卡片（无数据自动隐藏） ----------
    _render_extra_kpi_cards(level_df)

    st.divider()

    # ---------- 3. 图表区 2×2 ----------
    _render_charts(level_df)

    st.divider()

    # ---------- 4. 底部：全部门店核心指标明细表 ----------
    _render_store_table(level_df)

    st.divider()

    # ---------- 5. 门店分层结果板块 ----------
    render_leveling_section(level_df)

    st.divider()

    # ---------- 6. 单门店画像诊断板块 ----------
    render_single_store_section(level_df)


# ==================== KPI 卡片区 ====================
def _render_core_kpi_cards(df: pd.DataFrame):
    """顶部 4 个核心 KPI 卡片：总销售额、总获客、整体成交转化率、平均客单价。"""
    summary = metrics_mod.calc_summary_metrics(df)

    col1, col2, col3, col4 = st.columns(4)

    # 总销售额
    total_sales = summary.get("总销售额")
    col1.metric("💰 总销售额（元）", _fmt_number(total_sales))

    # 总获客数量
    total_hk = summary.get("总获客数量")
    col2.metric("👥 总获客数量", _fmt_number(total_hk))

    # 整体成交转化率（成交 / 到店）
    rate = summary.get("整体成交转化率")
    col3.metric("📈 整体成交转化率", _fmt_percent(rate))

    # 平均客单价
    avg_price = summary.get("平均客单价")
    col4.metric("💵 平均客单价（元）", "--" if pd.isna(avg_price) else f"{avg_price:,.2f}")


def _render_extra_kpi_cards(df: pd.DataFrame):
    """
    第二行扩展指标卡片：渠道数量、优质渠道占比、老客成交占比。
    对应数据缺失时自动隐藏该卡片。
    """
    cards = []  # (标签, 值) 列表，按实际数据动态组装

    # 渠道数量：大盘口径下各渠道总量 > 0 的渠道个数
    present_channels = [c for c in CHANNEL_FIELDS if _has_data(df, c)]
    if present_channels:
        channel_count = int((df[present_channels].sum() > 0).sum())
        cards.append(("🔀 渠道数量", f"{channel_count} 个"))

    # 优质渠道占比（转介绍 + 异业）
    summary = metrics_mod.calc_summary_metrics(df)
    quality_rate = summary.get("优质渠道总占比")
    if pd.notna(quality_rate):
        cards.append(("⭐ 优质渠道占比", _fmt_percent(quality_rate)))

    # 老客成交占比
    old_customer_rate = summary.get("老客成交数占比")
    if pd.notna(old_customer_rate):
        cards.append(("👴 老客成交占比", _fmt_percent(old_customer_rate)))

    # 无任何扩展数据时不渲染卡片区
    if not cards:
        return

    cols = st.columns(len(cards))
    for col, (label, value) in zip(cols, cards):
        col.metric(label, value)


# ==================== 图表区（2×2） ====================
def _render_charts(df: pd.DataFrame):
    """图表区 2×2 布局：漏斗 / 渠道饼图 / 销售额Top5 / 转化率Top5。"""
    top_left, top_right = st.columns(2)
    bottom_left, bottom_right = st.columns(2)

    with top_left:
        _render_funnel_chart(df)
    with top_right:
        _render_channel_pie_chart(df)
    with bottom_left:
        _render_top5_bar_chart(df, "销售额", "销售额Top5门店", BLUE_600)
    with bottom_right:
        _render_top5_bar_chart(df, "总转化率", "获客转化率Top5门店", BLUE_500)


def _render_funnel_chart(df: pd.DataFrame):
    """左上：转化漏斗图（获客 → 到店 → 成交），缺字段时自动隐藏。"""
    # 三个环节缺一不可，否则整图无意义
    if not all(_has_data(df, c) for c in ["获客数量", "到店数量", "成交人数"]):
        st.info("缺少获客 / 到店 / 成交字段，转化漏斗图暂不展示")
        return

    hk, dd, cj = (_column_total(df, c) for c in ["获客数量", "到店数量", "成交人数"])

    fig = go.Figure(go.Funnel(
        y=["获客数量", "到店数量", "成交人数"],
        x=[hk, dd, cj],
        textinfo="value+percent initial",
        textfont=dict(color="white"),
        marker=dict(color=[PRIMARY_BLUE, BLUE_600, BLUE_500]),
        connector=dict(line=dict(color=BLUE_300, width=1)),
    ))
    st.plotly_chart(_style_figure(fig, "转化漏斗（获客 → 到店 → 成交）"), use_container_width=True)


def _render_channel_pie_chart(df: pd.DataFrame):
    """右上：整体获客渠道结构饼图，无渠道数据时自动隐藏。"""
    present_channels = [c for c in CHANNEL_FIELDS if _has_data(df, c)]
    if not present_channels:
        st.info("未映射渠道字段，渠道结构图暂不展示")
        return

    # 各渠道总获客，合计为 0 的渠道剔除（避免饼图空段）
    channel_totals = {ch: _column_total(df, ch) for ch in present_channels}
    valid = {ch: v for ch, v in channel_totals.items() if v > 0}

    if not valid:
        st.info("渠道数据均为空，渠道结构图暂不展示")
        return

    fig = go.Figure(go.Pie(
        labels=list(valid.keys()),
        values=list(valid.values()),
        hole=0.42,  # 环形图，商务风格
        textinfo="label+percent",
        marker=dict(colors=CHANNEL_PIE_COLORS[: len(valid)], line=dict(color="white", width=1)),
    ))
    st.plotly_chart(_style_figure(fig, "整体获客渠道结构"), use_container_width=True)


def _render_top5_bar_chart(df: pd.DataFrame, value_col: str, title: str, color: str):
    """左下 / 右下：指定指标 Top5 门店柱状图，缺字段或全空时自动隐藏。"""
    if not _has_data(df, value_col):
        st.info(f"缺少「{value_col}」字段，{title}暂不展示")
        return

    # 取 Top5 并按值降序（占比类指标顺带过滤掉无效行）
    top5 = df[["门店名称", value_col]].dropna().nlargest(5, value_col)

    fig = px.bar(
        top5,
        x="门店名称",
        y=value_col,
        color="门店名称",
        color_discrete_sequence=[color],
        text=[_fmt_number(v) for v in top5[value_col]],
    )
    fig.update_traces(marker_line_width=0)
    # 门店名较长时自动调整坐标轴边距，避免标签溢出
    fig.update_xaxes(automargin=True)
    st.plotly_chart(_style_figure(fig, title), use_container_width=True)


# ==================== 门店明细表 ====================
def _render_store_table(df: pd.DataFrame):
    """底部：全部门店核心指标明细表，含「门店等级」预留位。"""
    st.subheader("🏬 全部门店核心指标明细")

    # 仅保留实际存在的列（兼容字段缺失场景）
    table_cols = [c for c in TABLE_COLUMNS if c in df.columns]
    table = df[table_cols].copy()

    # 比率列转换为百分比显示
    for col in RATE_COLUMNS:
        if col in table.columns:
            table[col] = (table[col] * 100).round(1)

    # 列配置：金额/比率格式化，门店等级突出显示
    column_config = {
        "销售额": st.column_config.NumberColumn(format="%.0f"),
        "客单价": st.column_config.NumberColumn(format="%.2f"),
        **{col: st.column_config.NumberColumn(format="%.1f%%") for col in RATE_COLUMNS if col in table.columns},
    }
    st.dataframe(table, use_container_width=True, column_config=column_config, hide_index=True)

    # 门店等级为分层结果预留位，给出提示
    if "门店等级" in table.columns and table["门店等级"].eq("未诊断").any():
        st.caption("ℹ️ 「门店等级」为分层诊断预留位，将根据分层规则自动填充（标杆店 / 成长店 / 一般店 / 落后店）。")


# ==================== 二、门店分层结果板块 ====================
# 分层明细表列定义（key 传给前端 JS，type 决定排序方式）
LEVEL_TABLE_COLUMNS = [
    {"key": "rank", "label": "排名", "type": "num"},
    {"key": "name", "label": "门店名称", "type": "text"},
    {"key": "manager", "label": "门店店长", "type": "text"},
    {"key": "store_type", "label": "门店类型", "type": "text"},
    {"key": "sales_wan", "label": "销售额(万)", "type": "num"},
    {"key": "conv_rate", "label": "获客转化率", "type": "num"},
    {"key": "price_wan", "label": "客单价(万)", "type": "num"},
    {"key": "score", "label": "综合得分", "type": "num"},
    {"key": "grade", "label": "门店等级", "type": "text"},
    {"key": "channels", "label": "渠道标签", "type": "text"},
    {"key": "issues", "label": "问题标签", "type": "text"},
]


def _to_str(value) -> str:
    """None / NaN → 空字符串，其余转为字符串（供标签、描述字段显示）。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value)


def render_leveling_section(level_df: pd.DataFrame):
    """
    门店分层结果板块：筛选栏 + 等级统计卡片 + 图表 + 明细表 + 导出 CSV。

    参数：
        level_df: leveling_stores 输出的完整分层结果（含原始字段与计算指标）
    """
    # ---------- 无数据状态 ----------
    if level_df is None or level_df.empty:
        st.info("请先在数据导入页上传门店数据")
        return

    # 板块标题（加粗 + 分隔线，与上方运营大盘视觉区分）
    st.markdown("**二、门店多级分层结果**")
    st.divider()

    # ---------- 顶部筛选栏 ----------
    filter_col1, filter_col2 = st.columns(2)
    # 门店等级筛选：全部 / S / A / B / C
    grade_options = ["全部"] + GRADE_LABELS
    grade_filter = filter_col1.selectbox("门店等级", grade_options, key="lv_grade_filter")
    # 门店类型筛选：从上传数据中自动提取
    type_options = ["全部"]
    if "门店类型" in level_df.columns:
        type_options += [str(t) for t in level_df["门店类型"].dropna().unique()]
    type_filter = filter_col2.selectbox("门店类型", type_options, key="lv_type_filter")

    # 筛选后实时重算（卡片 / 图表 / 表格共用同一份过滤数据）
    filtered = level_df.copy()
    if grade_filter != "全部":
        filtered = filtered[filtered["门店等级"] == grade_filter]
    if type_filter != "全部":
        filtered = filtered[filtered["门店类型"].astype(str) == type_filter]

    # ---------- 第一行：等级统计卡片 ----------
    _render_grade_cards(filtered)

    # ---------- 第二行：左右双栏图表 ----------
    chart_left, chart_right = st.columns(2)
    with chart_left:
        _render_grade_pie(filtered)
    with chart_right:
        _render_channel_pie(filtered)

    # ---------- 第三行：明细表 + 导出按钮（右下角） ----------
    _render_level_table(filtered)
    export_col1, export_col2 = st.columns([3, 1])
    with export_col2:
        st.download_button(
            "📥 导出分层结果CSV",
            data=level_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="门店分层结果.csv",
            mime="text/csv",
            help="导出包含全部原始字段 + 计算指标 + 分层结果的完整表格",
        )


def _render_grade_cards(filtered: pd.DataFrame):
    """第一行：4 个等级统计卡片（数量 + 占比），配色与等级徽章一致。"""
    total = len(filtered)
    cols = st.columns(4)
    for col, grade in zip(cols, GRADE_LABELS):
        count = int((filtered["门店等级"] == grade).sum())
        pct = count / total if total else 0
        color = GRADE_COLORS[grade]
        col.markdown(
            f"""
            <div style="background:#FFFFFF;border:1px solid {CARD_BORDER};border-left:4px solid {color};
                        border-radius:8px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
                <div style="color:{MUTED_TEXT};font-size:13px;margin-bottom:4px">{grade}级门店</div>
                <div style="font-size:28px;font-weight:700;color:{color};line-height:1.2">{count}</div>
                <div style="color:{FAINT_TEXT};font-size:12px;margin-top:4px">占比 {pct:.1%}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_grade_pie(filtered: pd.DataFrame):
    """左侧：门店等级分布饼图（沿用等级配色，显示数量与占比）。"""
    counts = {g: int((filtered["门店等级"] == g).sum()) for g in GRADE_LABELS}
    fig = go.Figure(go.Pie(
        labels=[f"{g}级" for g in GRADE_LABELS],
        values=[counts[g] for g in GRADE_LABELS],
        hole=0.45,
        textinfo="label+value+percent",
        marker=dict(
            colors=[GRADE_COLORS[g] for g in GRADE_LABELS],
            line=dict(color="white", width=1),
        ),
    ))
    st.plotly_chart(_style_figure(fig, "门店等级分布"), use_container_width=True)


def _render_channel_pie(filtered: pd.DataFrame):
    """右侧：全区域获客渠道结构饼图（6 大渠道总获客占比，无渠道数据自动隐藏）。"""
    present = [c for c in CHANNEL_FIELDS if _has_data(filtered, c)]
    if not present:
        st.info("未映射渠道字段，渠道结构图暂不展示")
        return
    # 各渠道总获客，合计为 0 的渠道剔除
    totals = {ch: _column_total(filtered, ch) for ch in present}
    valid = {ch: v for ch, v in totals.items() if v > 0}
    if not valid:
        st.info("渠道数据均为空，渠道结构图暂不展示")
        return

    labels = [CHANNEL_NAME_MAP.get(ch, ch) for ch in valid]
    fig = go.Figure(go.Pie(
        labels=labels,
        values=list(valid.values()),
        hole=0.42,
        textinfo="label+percent",
        marker=dict(
            colors=CHANNEL_PIE_COLORS[: len(valid)],
            line=dict(color="white", width=1),
        ),
    ))
    st.plotly_chart(_style_figure(fig, "全区域获客渠道结构"), use_container_width=True)


def _to_finite_float(value):
    """数值安全转换：None / NaN / 无穷 → None（保证 JSON 序列化与前端显示安全）。"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(value) or math.isinf(value):
        return None
    return value


def _build_table_rows(filtered: pd.DataFrame) -> list:
    """构建明细表行数据（单位转换：销售额 / 客单价 → 万，转化率 → 百分比数值）。"""
    rows = []
    for _, r in filtered.iterrows():
        rank = _to_finite_float(r.get("综合排名"))
        sales = _to_finite_float(r.get("销售额"))
        rate = _to_finite_float(r.get("总转化率"))
        price = _to_finite_float(r.get("客单价"))
        score = _to_finite_float(r.get("综合得分"))
        rows.append({
            "rank": int(rank) if rank is not None else None,
            "name": _to_str(r.get("门店名称")),
            "manager": _to_str(r.get("门店店长")),
            "store_type": _to_str(r.get("门店类型")),
            "sales_wan": round(sales / 10000, 2) if sales is not None else None,
            "conv_rate": round(rate * 100, 1) if rate is not None else None,
            "price_wan": round(price / 10000, 4) if price is not None else None,
            "score": score,
            "grade": _to_str(r.get("门店等级")),
            "channels": _to_str(r.get("渠道标签")),
            "issues": _to_str(r.get("问题标签")),
        })
    return rows


def _level_table_html(rows: list) -> str:
    """
    构建明细表 HTML：点击表头排序（原生 JS）+ 等级彩色徽章 + 渠道/问题圆角彩色标签。
    使用占位符替换方式注入数据，避免与 JS 大括号冲突。
    """
    # 表头（点击排序）
    thead = "".join(
        f'<th onclick="sortBy({i},\'{col["type"]}\')">{col["label"]} <span class="arrow">⇅</span></th>'
        for i, col in enumerate(LEVEL_TABLE_COLUMNS)
    )

    template = """
<style>
  .lv-scroll { max-height: 480px; overflow: auto; border: 1px solid __CARD_BORDER__; border-radius: 8px; }
  .lv-table { width: 100%; border-collapse: collapse; font-size: 13px; color: __INK__;
              font-family: "Microsoft YaHei", "PingFang SC", sans-serif; }
  .lv-table thead th { background: __PRIMARY_BLUE__; color: #FFFFFF; padding: 8px 12px; cursor: pointer;
                       user-select: none; text-align: left; white-space: nowrap; position: sticky;
                       top: 0; z-index: 1; font-weight: 600; }
  .lv-table thead th:hover { background: __BLUE_600__; }
  .lv-table thead th .arrow { font-size: 10px; opacity: 0.7; margin-left: 2px; }
  .lv-table tbody td { padding: 6px 12px; border-bottom: 1px solid __TABLE_BORDER__; white-space: nowrap; }
  /* 标签列允许换行（多标签不撑破表格），长门店名省略号截断（修复排版溢出） */
  .lv-table tbody td.td-tags { white-space: normal; min-width: 120px; max-width: 300px; }
  .lv-table tbody td.td-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
  .lv-table tbody tr:nth-child(even) td { background: __ROW_ALT_BG__; }
  .lv-table tbody tr:hover td { background: __ROW_HOVER_BG__; }
  .badge { display: inline-block; min-width: 26px; text-align: center; padding: 2px 10px;
           border-radius: 10px; color: #FFFFFF; font-weight: 700; font-size: 12px; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 12px;
         margin: 1px 4px 1px 0; white-space: nowrap; }
  .tag-blue { background: __TAG_BLUE_BG__; color: __TAG_BLUE_TEXT__; border: 1px solid __TAG_BLUE_BORDER__; }
  .tag-red { background: __TAG_RED_BG__; color: __TAG_RED_TEXT__; border: 1px solid __TAG_RED_BORDER__; }
  .muted { color: __FAINT_TEXT__; }
</style>
<div class="lv-scroll">
  <table class="lv-table">
    <thead><tr>__THEAD__</tr></thead>
    <tbody id="lvBody"></tbody>
  </table>
</div>
<script>
  const COLS = __COLS__;
  const DATA = __DATA__;
  const GRADE_COLORS = __GRADE_COLORS__;
  const asc = {};

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
  }

  function renderBadges(tags, cls) {
    if (!tags) return '<span class="muted">—</span>';
    const list = String(tags).split('；').filter(t => t && t.trim());
    if (!list.length) return '<span class="muted">—</span>';
    return list.map(t => '<span class="tag ' + cls + '">' + esc(t) + '</span>').join('');
  }

  function cellHtml(key, v) {
    if (key === 'grade') {
      return v ? '<span class="badge" style="background:' + (GRADE_COLORS[v] || '#999999') + '">' + esc(v) + '</span>'
               : '<span class="muted">—</span>';
    }
    if (key === 'channels') return renderBadges(v, 'tag-blue');
    if (key === 'issues') return renderBadges(v, 'tag-red');
    if (v === null || v === undefined || v === '') return '<span class="muted">—</span>';
    if (key === 'conv_rate') return esc(v) + '%';
    if (key === 'sales_wan' || key === 'score') return Number(v).toFixed(2);
    if (key === 'price_wan') return Number(v).toFixed(4);
    return esc(v);
  }

  function renderRows() {
    const tb = document.getElementById('lvBody');
    tb.innerHTML = DATA.map(r => {
      const tds = COLS.map(c => {
        const v = r[c.key];
        const sortVal = (v === null || v === undefined || v === '') ? '' : esc(v);
        // 标签列允许换行、门店名省略显示（与 CSS 类配套，修复排版溢出）
        const cls = (c.key === 'channels' || c.key === 'issues') ? ' class="td-tags"'
                  : (c.key === 'name' ? ' class="td-name"' : '');
        return '<td' + cls + ' data-v="' + sortVal + '">' + cellHtml(c.key, v) + '</td>';
      }).join('');
      return '<tr>' + tds + '</tr>';
    }).join('');
  }

  function sortBy(i, type) {
    asc[i] = !asc[i];
    document.querySelectorAll('.lv-table thead th').forEach((th, j) => {
      const sp = th.querySelector('.arrow');
      if (sp) sp.textContent = (j === i) ? (asc[i] ? '↑' : '↓') : '⇅';
    });
    const tb = document.getElementById('lvBody');
    const rows = Array.from(tb.rows);
    rows.sort((a, b) => {
      const x = a.cells[i].dataset.v;
      const y = b.cells[i].dataset.v;
      let cmp;
      if (type === 'num') {
        const xn = parseFloat(x), yn = parseFloat(y);
        if (isNaN(xn) && isNaN(yn)) cmp = 0;
        else if (isNaN(xn)) cmp = 1;
        else if (isNaN(yn)) cmp = -1;
        else cmp = xn - yn;
      } else {
        cmp = String(x).localeCompare(String(y), 'zh');
      }
      return asc[i] ? cmp : -cmp;
    });
    rows.forEach(r => tb.appendChild(r));
  }

  renderRows();
</script>
"""
    return (
        template
        .replace("__THEAD__", thead)
        .replace("__COLS__", json.dumps(LEVEL_TABLE_COLUMNS, ensure_ascii=False))
        .replace("__DATA__", json.dumps(rows, ensure_ascii=False))
        .replace("__GRADE_COLORS__", json.dumps(GRADE_COLORS))
        .replace("__PRIMARY_BLUE__", PRIMARY_BLUE)
        .replace("__BLUE_600__", BLUE_600)
        .replace("__INK__", INK)
        .replace("__FAINT_TEXT__", FAINT_TEXT)
        .replace("__CARD_BORDER__", CARD_BORDER)
        .replace("__TABLE_BORDER__", TABLE_BORDER)
        .replace("__ROW_ALT_BG__", ROW_ALT_BG)
        .replace("__ROW_HOVER_BG__", ROW_HOVER_BG)
        .replace("__TAG_BLUE_BG__", TAG_BLUE_BG)
        .replace("__TAG_BLUE_TEXT__", TAG_BLUE_TEXT)
        .replace("__TAG_BLUE_BORDER__", TAG_BLUE_BORDER)
        .replace("__TAG_RED_BG__", TAG_RED_BG)
        .replace("__TAG_RED_TEXT__", TAG_RED_TEXT)
        .replace("__TAG_RED_BORDER__", TAG_RED_BORDER)
    )


def _render_level_table(filtered: pd.DataFrame):
    """第三行：分层结果明细表（HTML 渲染，支持点击表头排序与筛选联动）。"""
    rows = _build_table_rows(filtered)
    html = _level_table_html(rows)
    # 行高约 34px，最多展开 15 行，超出部分滚动
    table_height = min(len(rows), 15) * 34 + 60
    st_html(html, height=table_height, scrolling=False)


# ==================== 三、自动诊断规则引擎 ====================
# 基于「与全量数据整体均值对比」的单店 / 大盘自动诊断。
# 容错约定：指标缺失（列不存在 / 全列空 / 门店值为 0 或空）时自动跳过对应判断，不报错；
# 所有判定阈值均来自数据集整体均值，无任何硬编码数值。

# 诊断规则 / 优势候选 / 建议库等业务配置（唯一来源：utils/config.py），
# 换业态调整规则与建议文案时只改 config.py，本处仅绑定短名。
METRIC_DISPLAY_NAMES = cfg.METRIC_DISPLAY_NAMES
DIAGNOSIS_RULES = cfg.DIAGNOSIS_RULES
ADVANTAGE_COLUMNS = cfg.ADVANTAGE_COLUMNS
ISSUE_EXCLUDES = cfg.ISSUE_EXCLUDES
COMMON_ISSUE_RATE = cfg.COMMON_ISSUE_RATE
SUGGESTION_BANK = cfg.SUGGESTION_BANK
GENERIC_SUGGESTIONS = cfg.GENERIC_SUGGESTIONS

# 规则问题判定顺序（大盘共性问题统计使用，复合规则「高获客低转化」排在最后）
ISSUE_ORDER = [rule["issue"] for rule in DIAGNOSIS_RULES] + ["高获客低转化"]


def _col_value(row, col):
    """
    取行内指定列数值；列缺失 / 值为 0 或空 / 非数值时返回 None（容错核心）。
    兼容 pd.Series（DataFrame.iterrows / .loc 产出）与 dict 两种行结构。
    """
    if hasattr(row, "index"):
        if col not in row.index:
            return None
    elif col not in row:
        return None
    value = pd.to_numeric(row[col], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def _overall_means(df_all: pd.DataFrame) -> dict:
    """全量数据各相关指标列的均值；列缺失或全空时跳过（无硬编码口径）。"""
    cols = {"综合得分"}
    for rule in DIAGNOSIS_RULES:
        cols.update(rule["cols"])
    cols.update(ADVANTAGE_COLUMNS)
    means = {}
    for col in cols:
        if col in df_all.columns and df_all[col].notna().any():
            means[col] = float(df_all[col].mean())
    return means


def _resolve_rule_cols(df_all: pd.DataFrame) -> dict:
    """为每条规则解析实际使用的指标列（按候选顺序取第一个有数据的）。"""
    rule_cols = {}
    for rule in DIAGNOSIS_RULES:
        col = next(
            (c for c in rule["cols"] if c in df_all.columns and df_all[c].notna().any()),
            None,
        )
        if col:
            rule_cols[rule["issue"]] = col
    return rule_cols


def _detect_issues(row, means: dict, rule_cols: dict) -> list:
    """单门店规则判定：命中问题列表（门店值或整体均值缺失的规则自动跳过）。"""
    issues = []
    for rule in DIAGNOSIS_RULES:
        col = rule_cols.get(rule["issue"])
        if not col:
            continue
        value, mean = _col_value(row, col), means.get(col)
        if value is None or mean is None:
            continue
        hit = (value > mean) if rule["direction"] == "high" else (value < mean)
        if hit:
            issues.append(rule["issue"])
    # 复合规则：高获客低转化 = 获客量高于均值 且 转化率低于均值
    rate_col = rule_cols.get("转化低效")
    hk, m_hk = _col_value(row, "获客数量"), means.get("获客数量")
    rate, m_rate = _col_value(row, rate_col) if rate_col else None, means.get(rate_col) if rate_col else None
    if all(v is not None for v in (hk, m_hk, rate, m_rate)) and hk > m_hk and rate < m_rate:
        issues.append("高获客低转化")
    return issues


def _format_advantage(col: str, value: float, mean: float) -> str:
    """优势文案：'高价值渠道占比高于均值22%'；差距不足 1% 显示为略高于；均值极小时退化为绝对领先。"""
    name = METRIC_DISPLAY_NAMES.get(col, col)
    if mean > 0:
        pct = (value / mean - 1) * 100
        if pct >= 1:
            return f"{name}高于均值{pct:.0f}%"
        return f"{name}略高于均值"
    return f"{name}为全店最强（{value:,.0f}）"


def _detect_advantages(row, means: dict, issues: list, rule_cols: dict, top_n: int = 4) -> list:
    """对比整体均值的优势列表：排除已命中问题对应的指标，按相对差距取前 top_n 项。"""
    excluded = set()
    for issue, cols in ISSUE_EXCLUDES.items():
        if issue in issues:
            excluded.update(cols)
    # 转化率列按实际使用动态排除（转化低效 / 高获客低转化命中时）
    if "转化低效" in issues or "高获客低转化" in issues:
        rate_col = rule_cols.get("转化低效")
        if rate_col:
            excluded.add(rate_col)

    candidates = []
    for col in ADVANTAGE_COLUMNS:
        if col in excluded:
            continue
        value, mean = _col_value(row, col), means.get(col)
        if value is None or mean is None or value <= mean:
            continue
        # 相对差距作为排序分（均值极小时退化为绝对差距）
        score = (value - mean) / mean if mean > 0 else value
        candidates.append((col, value, mean, score))
    candidates.sort(key=lambda item: item[3], reverse=True)
    return [_format_advantage(col, value, mean) for col, value, mean, _ in candidates[:top_n]]


def _collect_tags(row) -> list:
    """合并渠道 / 客群 / 问题三类标签（去重），供诊断结论与建议选择使用。"""
    tags = []
    for col in ["渠道标签", "客群标签", "问题标签"]:
        for tag in _to_str(row.get(col)).split("；"):
            tag = tag.strip()
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def _build_conclusion(row, means: dict, advantages: list, issues: list) -> str:
    """120 字左右的中文综合诊断结论；数据缺失时自动降级保留核心信息。"""
    name = _to_str(row.get("门店名称")) or "该门店"
    score = row.get("综合得分")
    grade = _to_str(row.get("门店等级"))

    parts = []
    # 1) 总分句：综合得分 + 等级 + 与全店均值对比（评价不依赖硬编码分档）
    if pd.notna(score):
        score_f = float(score)
        head = f"「{name}」综合得分{score_f:.1f}分"
        if grade:
            head += f"（{grade}级）"
        score_mean = means.get("综合得分")
        if pd.notna(score_mean):
            if score_f > score_mean:
                head += f"，高于全店均值{score_f - score_mean:.1f}分"
            elif score_f < score_mean:
                head += f"，低于全店均值{score_mean - score_f:.1f}分"
            else:
                head += "，与全店均值持平"
    else:
        head = f"「{name}」"
    parts.append(head)

    # 2) 优势 / 3) 短板（结论内分别展示前 2 / 前 3 项）
    parts.append(f"优势：{'、'.join(advantages[:2]) or '无明显领先项'}")
    parts.append(f"短板：{'、'.join(issues[:3]) if issues else '无明显短板'}")

    # 4) 门店特征（标签画像）
    tags = _collect_tags(row)
    if tags:
        parts.append(f"特征：{'、'.join(tags)}")

    # 5) 行动方向
    if issues:
        parts.append(f"建议优先解决「{issues[0]}」问题")
    else:
        parts.append("建议保持当前打法并持续优化")

    conclusion = "，".join(parts) + "。"
    # 长度控制：超过 140 字时从尾部裁剪非核心部分（特征 / 建议），保留总分句与优劣势
    while len(conclusion) > 140 and len(parts) > 2:
        parts.pop()
        conclusion = "，".join(parts) + "。"
    return conclusion


def _build_suggestions(row, issues: list) -> list:
    """
    3 条改进建议：优先取自门店标签（问题 > 客群 > 渠道，贴合标签画像），
    其次由规则问题补齐，最后用通用建议兜底；内容重复的自动去重。
    """
    picked, seen = [], set()
    for col in ["问题标签", "客群标签", "渠道标签"]:
        for tag in _to_str(row.get(col)).split("；"):
            tag = tag.strip()
            suggestion = SUGGESTION_BANK.get(tag)
            if suggestion and tag not in seen and suggestion not in picked:
                seen.add(tag)
                picked.append(suggestion)
    for issue in issues:
        suggestion = SUGGESTION_BANK.get(issue)
        if suggestion and issue not in seen and suggestion not in picked:
            seen.add(issue)
            picked.append(suggestion)
    for generic in GENERIC_SUGGESTIONS:
        if len(picked) >= 3:
            break
        if generic not in picked:
            picked.append(generic)
    return picked[:3]


def get_store_diagnosis(row, df_all: pd.DataFrame) -> dict:
    """
    单门店自动诊断：与全量数据整体均值对比，输出优势 / 问题 / 结论 / 建议。

    参数：
        row: 单门店数据行（pd.Series 或 dict，calc_basic_metrics + leveling_stores
             产出的分层表行，含原始字段、计算指标与分层标签）
        df_all: 全量门店分层表（同一流水线产出，用于计算整体均值）

    返回：
        dict: 门店名称 / 综合得分 / 门店等级 /
              优势列表（对比整体均值，如「销售额高于均值45%」）/
              问题列表（命中规则问题）/
              诊断结论（120 字左右中文结论）/
              改进建议（3 条，贴合渠道 / 客群 / 问题标签）
    """
    means = _overall_means(df_all)
    rule_cols = _resolve_rule_cols(df_all)
    issues = _detect_issues(row, means, rule_cols)
    advantages = _detect_advantages(row, means, issues, rule_cols)
    return {
        "门店名称": _to_str(row.get("门店名称")),
        "综合得分": row.get("综合得分"),
        "门店等级": _to_str(row.get("门店等级")),
        "优势": advantages,
        "问题": issues,
        "诊断结论": _build_conclusion(row, means, advantages, issues),
        "改进建议": _build_suggestions(row, issues),
    }


def _rule_valid(row, issue: str, rule_cols: dict, means: dict) -> bool:
    """该门店是否具备判断指定规则的数据（门店指标与整体均值均有效）。"""
    if issue == "高获客低转化":
        rate_col = rule_cols.get("转化低效")
        return bool(
            rate_col
            and _col_value(row, "获客数量") is not None
            and _col_value(row, rate_col) is not None
            and means.get("获客数量") is not None
            and means.get(rate_col) is not None
        )
    col = rule_cols.get(issue)
    return bool(col and _col_value(row, col) is not None and means.get(col) is not None)


def get_overall_summary(df_all: pd.DataFrame) -> dict:
    """
    大盘整体诊断：整体亮点 + 整体共性问题。

    参数：
        df_all: 全量门店分层表（calc_basic_metrics + leveling_stores 产出）

    返回：
        dict: {"highlights": [str, ...], "problems": [str, ...]}
            highlights - 整体亮点（规模 / 转化最强环节 / 渠道结构 / 等级分布）
            problems   - 整体共性问题（漏斗最大漏损 / 半数以上门店命中的规则问题 / 结构性观察）
    """
    highlights, problems = [], []
    if df_all is None or df_all.empty:
        return {"highlights": [], "problems": ["暂无门店数据，无法生成大盘诊断"]}

    logger.debug("开始生成大盘诊断：%d 家门店", len(df_all))

    summary = metrics_mod.calc_summary_metrics(df_all)
    n = len(df_all)

    # ---------- 整体亮点（基于实际数值的事实描述，不设阈值） ----------
    total_sales = summary.get("总销售额")
    if pd.notna(total_sales):
        avg_sales = total_sales / n
        highlights.append(
            f"大盘合计销售额 {total_sales / 10000:,.1f} 万元，"
            f"{n} 家门店单店平均 {avg_sales / 10000:,.1f} 万元"
        )
    avg_price = summary.get("平均客单价")
    if pd.notna(avg_price):
        highlights.append(f"整体平均客单价 {avg_price:,.0f} 元")

    # 转化漏斗：两环节对比，较强一环记为亮点，较弱一环记为漏损
    dd_rate = summary.get("整体到店转化率")
    cj_rate = summary.get("整体成交转化率")
    if pd.notna(dd_rate) and pd.notna(cj_rate):
        if dd_rate >= cj_rate:
            highlights.append(f"转化漏斗「获客→到店」环节转化率 {dd_rate:.1%}，引流承接是当前最强环节")
            problems.append(f"到店→成交环节转化率仅 {cj_rate:.1%}，销售促成是全盘最大漏损点")
        else:
            highlights.append(f"转化漏斗「到店→成交」环节转化率 {cj_rate:.1%}，销售促成能力突出")
            problems.append(f"获客→到店环节转化率仅 {dd_rate:.1%}，引流承接是全盘最大漏损点")

    # 渠道结构：主渠道占比与高价值渠道占比
    present_channels = [c for c in CHANNEL_FIELDS if _has_data(df_all, c)]
    if present_channels:
        top_ch = max(present_channels, key=lambda c: _column_total(df_all, c))
        top_share = summary.get(f"{top_ch}获客占比")
        if pd.notna(top_share):
            highlights.append(
                f"获客以「{CHANNEL_NAME_MAP.get(top_ch, top_ch)}」为主，"
                f"占整体获客 {top_share:.1%}"
            )
    quality_rate = summary.get("优质渠道总占比")
    if pd.notna(quality_rate):
        highlights.append(f"转介绍+异业等高价值渠道合计占整体获客 {quality_rate:.1%}")

    # 等级分布（综合得分均值 + S/A 级占比）
    if "综合得分" in df_all.columns and df_all["综合得分"].notna().any():
        highlights.append(f"门店综合得分均值 {df_all['综合得分'].mean():.1f} 分")
    if "门店等级" in df_all.columns:
        grade_counts = df_all["门店等级"].value_counts()
        s_count = int(grade_counts.get("S", 0))
        a_count = int(grade_counts.get("A", 0))
        highlights.append(f"S/A 级门店共 {s_count + a_count} 家，占比 {(s_count + a_count) / n:.0%}")

    # ---------- 整体共性问题 ----------
    # 1. 规则命中率：超过半数有效门店命中的问题记为共性问题
    means = _overall_means(df_all)
    rule_cols = _resolve_rule_cols(df_all)
    hit = {issue: 0 for issue in ISSUE_ORDER}
    valid = {issue: 0 for issue in ISSUE_ORDER}
    for _, row in df_all.iterrows():
        for issue in _detect_issues(row, means, rule_cols):
            hit[issue] += 1
        for issue in ISSUE_ORDER:
            if _rule_valid(row, issue, rule_cols, means):
                valid[issue] += 1
    for issue in ISSUE_ORDER:
        total_valid = valid[issue]
        if total_valid >= 2 and hit[issue] / total_valid >= COMMON_ISSUE_RATE:
            problems.append(
                f"「{issue}」是普遍问题：{hit[issue]} / {total_valid} 家门店命中"
                f"（{hit[issue] / total_valid:.0%}）"
            )

    # 2. 获客质量结构观察：活动营销占比高于高价值渠道占比 → 偏价格驱动
    act_share = summary.get("活动获客占比")
    if pd.notna(act_share) and pd.notna(quality_rate) and act_share > quality_rate:
        problems.append(
            f"活动营销获客占比（{act_share:.1%}）高于高价值渠道占比（{quality_rate:.1%}），"
            f"获客结构偏价格驱动，可持续性存疑"
        )

    logger.debug("大盘诊断完成：亮点 %d 条，共性问题 %d 条", len(highlights), len(problems))
    return {"highlights": highlights, "problems": problems}


# ==================== 四、单门店画像诊断板块（页面第三板块） ====================
# 「三、单门店画像诊断」：下拉选择门店后，联动展示该门店
# 基础信息卡片 / 五维能力雷达图 / 渠道获客结构饼图 / 关键指标对比卡片 / 诊断结论与建议。
# 指标对比全部基于与全量数据整体均值的对比（与自动诊断规则引擎口径一致），
# 数据缺失时自动降级展示（维度取中性 50 分 / 暂无数据 / 提示语），不报错。

# 雷达图五维（随 config.DIMENSIONS 自动派生，调整维度后雷达图自动同步）
RADAR_DIMENSIONS = [dim["name"] for dim in cfg.DIMENSIONS]

# 关键指标对比卡片：label 展示名 / col 指标列 / kind 值格式（percent 或 currency）
SINGLE_METRIC_CARDS = [
    {"label": "获客转化率", "col": "总转化率", "kind": "percent"},
    {"label": "客单价", "col": "客单价", "kind": "currency"},
    {"label": "套购率", "col": "高客单成交数占比", "kind": "percent"},
    {"label": "会员渗透率", "col": "会员成交数占比", "kind": "percent"},
]

# 对比卡片差异颜色（高于 / 低于 / 持平，与全局配色统一）
_DELTA_COLORS = {"up": DELTA_UP, "down": DELTA_DOWN, "neutral": DELTA_NEUTRAL}


def _metric_value_text(value: float, kind: str) -> str:
    """指标值文本：百分比 / 货币格式。"""
    if kind == "percent":
        return f"{value:.1%}"
    return f"{value:,.2f}"


def _mean_delta(value: float, mean):
    """
    门店值相对整体均值的差异：返回 (文案, 颜色标识)。
    均值缺失 → 无标注；均值 ≤ 0 时退化为「高于均值 / 与均值持平」。
    """
    if mean is None or pd.isna(mean):
        return None, "neutral"
    if mean <= 0:
        return ("高于均值" if value > 0 else "与均值持平"), "up"
    rel = (value / mean - 1) * 100
    if abs(rel) < 1:
        return "与均值持平", "neutral"
    if rel > 0:
        return f"高于均值 {rel:.0f}%", "up"
    return f"低于均值 {-rel:.0f}%", "down"


def _info_card_html(label: str, value: str) -> str:
    """基础信息卡片 HTML：白色圆角卡片 + 左侧深蓝描边（与分层板块风格一致）。"""
    return f"""
    <div style="background:#FFFFFF;border:1px solid {CARD_BORDER};border-left:4px solid {PRIMARY_BLUE};
                border-radius:8px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
        <div style="color:{MUTED_TEXT};font-size:13px;margin-bottom:4px">{label}</div>
        <div style="font-size:20px;font-weight:700;color:{PRIMARY_BLUE};line-height:1.2;word-break:break-all">{html.escape(value)}</div>
    </div>
    """


def _grade_card_html(label: str, grade: str, color: str) -> str:
    """门店等级卡片 HTML：彩色徽章（配色与分层明细表徽章一致）。"""
    return f"""
    <div style="background:#FFFFFF;border:1px solid {CARD_BORDER};border-left:4px solid {color};
                border-radius:8px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
        <div style="color:{MUTED_TEXT};font-size:13px;margin-bottom:6px">{label}</div>
        <span style="display:inline-block;background:{color};color:#FFFFFF;font-weight:700;font-size:18px;
                     padding:2px 20px;border-radius:12px">{html.escape(grade)}</span>
    </div>
    """


def _metric_card_html(label: str, value_text: str, delta_text, delta_color: str) -> str:
    """关键指标对比卡片 HTML：数值 + 高于 / 低于整体均值标注（彩色箭头）。"""
    delta_html = ""
    if delta_text:
        color = _DELTA_COLORS.get(delta_color, DELTA_NEUTRAL)
        arrow = "▲" if delta_color == "up" else ("▼" if delta_color == "down" else "")
        delta_html = f'<div style="color:{color};font-size:12px;margin-top:4px">{arrow} {delta_text}</div>'
    return f"""
    <div style="background:#FFFFFF;border:1px solid {CARD_BORDER};border-left:4px solid {PRIMARY_BLUE};
                border-radius:8px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
        <div style="color:{MUTED_TEXT};font-size:13px;margin-bottom:4px">{label}</div>
        <div style="font-size:24px;font-weight:700;color:{PRIMARY_BLUE};line-height:1.2">{value_text}</div>
        {delta_html}
    </div>
    """


def _render_single_info_cards(row: pd.Series):
    """第一行：门店基础信息卡片（名称 / 店长 / 类型 / 等级彩色徽章）。"""
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(_info_card_html("🏪 门店名称", _to_str(row.get("门店名称")) or "—"), unsafe_allow_html=True)
    col2.markdown(_info_card_html("👤 门店店长", _to_str(row.get("门店店长")) or "—"), unsafe_allow_html=True)
    col3.markdown(_info_card_html("🏷️ 门店类型", _to_str(row.get("门店类型")) or "—"), unsafe_allow_html=True)
    grade = _to_str(row.get("门店等级")) or "未诊断"
    grade_color = GRADE_COLORS.get(grade, "#999999")
    col4.markdown(_grade_card_html("🏅 门店等级", grade, grade_color), unsafe_allow_html=True)


def _render_single_radar(row: pd.Series):
    """左栏：五维能力雷达图（维度标准化得分 ×100，缺失维度取中性 50 分）。"""
    values, missing = [], []
    for dim in RADAR_DIMENSIONS:
        score = row.get(f"{dim}得分")
        if pd.notna(score):
            values.append(round(float(score) * 100, 1))
        else:
            values.append(50.0)
            missing.append(dim)
    fig = go.Figure(go.Scatterpolar(
        r=values + values[:1],
        theta=RADAR_DIMENSIONS + RADAR_DIMENSIONS[:1],
        fill="toself",
        line=dict(color=BLUE_500, width=2),
        fillcolor="rgba(91,155,213,0.30)",
    ))
    fig.update_layout(polar=dict(
        radialaxis=dict(range=[0, 100], showticklabels=True, ticks="", gridcolor=BLUE_300),
        angularaxis=dict(gridcolor=BLUE_300, tickfont=dict(size=13)),
        bgcolor="rgba(0,0,0,0)",
    ))
    st.plotly_chart(_style_figure(fig, "五维能力雷达图", height=360), use_container_width=True)
    if missing:
        st.caption(f"ℹ️ 「{'、'.join(missing)}」维度无数据，按中性 50 分展示")


def _render_single_channel_pie(row: pd.Series):
    """右栏：该门店渠道获客结构饼图（6 大渠道，无数据自动提示）。"""
    valid = {}
    for ch in CHANNEL_FIELDS:
        value = _col_value(row, ch)
        if value is not None and value > 0:
            valid[ch] = value
    if not valid:
        st.info("该门店暂无渠道获客数据，渠道结构图暂不展示")
        return
    labels = [CHANNEL_NAME_MAP.get(ch, ch) for ch in valid]
    fig = go.Figure(go.Pie(
        labels=labels,
        values=list(valid.values()),
        hole=0.42,
        textinfo="label+percent",
        marker=dict(colors=CHANNEL_PIE_COLORS[: len(valid)], line=dict(color="white", width=1)),
    ))
    st.plotly_chart(_style_figure(fig, "该门店渠道获客结构"), use_container_width=True)


def _render_single_metric_cards(row: pd.Series, level_df: pd.DataFrame):
    """第三行：关键指标对比卡片（门店值 + 高于 / 低于整体均值标注）。"""
    cols = st.columns(len(SINGLE_METRIC_CARDS))
    for col, metric in zip(cols, SINGLE_METRIC_CARDS):
        value = _col_value(row, metric["col"])
        if value is None:
            col.markdown(_metric_card_html(metric["label"], "暂无数据", None, "neutral"), unsafe_allow_html=True)
            continue
        mean = None
        if metric["col"] in level_df.columns and level_df[metric["col"]].notna().any():
            mean = float(level_df[metric["col"]].mean())
        delta_text, delta_color = _mean_delta(value, mean)
        col.markdown(
            _metric_card_html(metric["label"], _metric_value_text(value, metric["kind"]), delta_text, delta_color),
            unsafe_allow_html=True,
        )


def _render_single_diagnosis(row: pd.Series, level_df: pd.DataFrame):
    """第四行：自动诊断结论 + 核心优势 / 主要问题 / 优化建议（调用诊断规则引擎）。"""
    diagnosis = get_store_diagnosis(row, level_df)
    st.info(f"📋 诊断结论：{diagnosis['诊断结论']}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**🔹 核心优势**")
        if diagnosis["优势"]:
            st.markdown("\n".join(f"- {a}" for a in diagnosis["优势"]))
        else:
            st.markdown("未识别出明显领先项，整体与全店均值持平")
    with col2:
        st.markdown("**⚠️ 主要问题**")
        if diagnosis["问题"]:
            st.markdown("\n".join(f"- {p}" for p in diagnosis["问题"]))
        else:
            st.markdown("✅ 未发现明显短板，保持当前打法")
    with col3:
        st.markdown("**💡 优化建议**")
        for i, suggestion in enumerate(diagnosis["改进建议"], 1):
            st.markdown(f"{i}. {suggestion}")


def render_single_store_section(level_df: pd.DataFrame):
    """
    三、单门店画像诊断板块：下拉选择门店，全部画像与诊断联动实时刷新。

    参数：
        level_df: leveling_stores 输出的完整分层结果（含原始字段、计算指标与分层标签）
    """
    st.markdown("**三、单门店画像诊断**")
    st.divider()

    # ---------- 无数据状态 ----------
    if level_df is None or level_df.empty or "门店名称" not in level_df.columns:
        st.info("暂无门店数据，请先在数据导入页上传门店数据")
        return

    # 全量门店列表（按综合排名升序，作为等级筛选与「下一家」按钮的基础）
    ordered = level_df.copy()
    if "综合排名" in ordered.columns and ordered["综合排名"].notna().any():
        ordered = ordered.sort_values("综合排名", na_position="last")
    all_names = [n for n in (_to_str(v) for v in ordered["门店名称"]) if n]
    if not all_names:
        st.info("暂无门店数据，请先在数据导入页上传门店数据")
        return

    # ---------- 筛选与选择区：等级筛选 + 门店下拉 + 下一家按钮（同一行三列） ----------
    filter_col, select_col, next_col = st.columns([2, 3, 1.5])

    # 一级筛选：门店等级（全部 / S级 / A级 / B级 / C级，默认全部）
    grade_options = ["全部"] + [f"{g}级" for g in GRADE_LABELS]
    grade_filter = filter_col.selectbox("门店等级筛选", grade_options, key="single_grade_filter")

    # 按等级过滤门店列表；选「全部」展示全部门店
    if grade_filter != "全部":
        grade = grade_filter[:-1]  # 「S级」→「S」
        filtered_rows = ordered[ordered["门店等级"].astype(str) == grade]
    else:
        filtered_rows = ordered
    names = [n for n in (_to_str(v) for v in filtered_rows["门店名称"]) if n]

    # 边界：筛选后该等级无门店时友好提示（等级下拉保留，可更换筛选条件）
    if not names:
        st.info("该等级暂无门店数据，请更换筛选条件")
        return

    # 数据变更 / 等级切换后旧选中值可能已失效：清除后回退到过滤列表第一条（排名最优），避免下拉越界
    if st.session_state.get("single_store_select") not in names:
        st.session_state.pop("single_store_select", None)
    selected = select_col.selectbox("🏪 选择门店", names, key="single_store_select")

    # 下一个同等级门店按钮：点击直接切换到同等级列表中的下一家（列表末尾循环回第一家）
    if next_col.button(
        "⏭️ 下一个同等级门店",
        use_container_width=True,
        help="切换到同等级门店中的下一家（列表末尾自动回到第一家）",
    ):
        current = st.session_state.get("single_store_select")
        if current in names:
            next_name = names[(names.index(current) + 1) % len(names)]
            st.session_state["single_store_select"] = next_name
            st.rerun()

    # 当前门店行（按名称匹配，取第一行）
    row = level_df[level_df["门店名称"].astype(str) == selected].iloc[0]

    # 排名 / 得分说明
    info = []
    rank = row.get("综合排名")
    score = row.get("综合得分")
    if pd.notna(rank):
        info.append(f"综合排名第 {int(rank)} 位")
    if pd.notna(score):
        info.append(f"综合得分 {float(score):.1f} 分")
    if info:
        st.caption(" ｜ ".join(info))

    st.divider()

    # ---------- 第一行：基础信息卡片 ----------
    _render_single_info_cards(row)

    # ---------- 第二行：五维雷达图 + 渠道结构饼图 ----------
    radar_col, pie_col = st.columns(2)
    with radar_col:
        _render_single_radar(row)
    with pie_col:
        _render_single_channel_pie(row)

    st.divider()

    # ---------- 第三行：关键指标对比卡片 ----------
    _render_single_metric_cards(row, level_df)

    st.divider()

    # ---------- 第四行：诊断结论 + 优势 / 问题 / 建议 ----------
    _render_single_diagnosis(row, level_df)
