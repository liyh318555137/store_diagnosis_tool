# -*- coding: utf-8 -*-
"""
通用门店运营分层诊断系统 —— 主程序入口

功能说明：
    - 侧边栏两页导航：【数据导入】、【分析诊断】
    - 数据导入页：上传 CSV / XLSX（≤20MB）、字段映射、数据清洗、
      异常标记、示例数据一键体验，数据统一持久化到 session_state
    - 分析诊断页：基于已导入数据执行指标计算与门店分层诊断

会话状态（三个固定数据 key）：
    - raw_df          用户上传的原始数据
    - cleaned_df      清洗后的标准字段数据
    - field_mapping   用户配置的字段映射关系

运行方式：
    streamlit run app.py
"""

import io
import logging
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from utils import __version__, data_process, metrics, leveling, report
from utils import config as cfg
from utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)

# ==================== 全局初始化 ====================
# 日志体系：控制台 + logs/app.log（级别可用环境变量 STORE_DIAG_LOG_LEVEL 调整）
setup_logging()
logger.info("应用启动，版本 v%s", __version__)

# 全局页面配置（必须是第一个 Streamlit 命令）
st.set_page_config(
    page_title=cfg.APP_TITLE,
    page_icon=cfg.PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# 启动即校验业务配置：配置改错时给出明确错误而非静默异常（详见 utils/config.py）
_config_problems = cfg.validate_config()
if _config_problems:
    logger.error("业务配置校验未通过：%s", _config_problems)
    st.error("❌ 业务配置校验未通过（见 utils/config.py）：" + "；".join(_config_problems))
    st.stop()


# ==================== 导入数据会话状态管理 ====================
# 数据导入相关的会话 key（清空数据时统一移除）
IMPORT_STATE_KEYS = ["raw_df", "cleaned_df", "issues", "field_mapping", "_data_source"]


def _has_imported_data() -> bool:
    """是否已导入门店数据（cleaned_df 存在且非空）。"""
    return "cleaned_df" in st.session_state and st.session_state["cleaned_df"] is not None


class _NamedFile(io.BytesIO):
    """带文件名的内存文件对象：load_data 依赖 .name 判断文件格式，用于读取内置示例 CSV。"""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _load_sample_data() -> pd.DataFrame:
    """
    加载示例数据：优先读取 data/example_data.csv（15 家模拟门店，列名为业务口径，
    与上传流程一致地经过字段标准化），文件缺失时回退内置生成器。
    """
    csv_path = Path(__file__).resolve().parent / "data" / "example_data.csv"
    if csv_path.exists():
        return data_process.load_data(_NamedFile(csv_path.read_bytes(), "example_data.csv"))
    return data_process.build_sample_data()


def _reset_import_state():
    """清空导入相关的全部会话状态（数据 / 映射 / 异常记录），恢复初始状态。"""
    for key in IMPORT_STATE_KEYS:
        st.session_state.pop(key, None)
    # 同步清空字段映射下拉框的选中值
    for field in data_process.STANDARD_FIELDS:
        st.session_state.pop(f"map_{field}", None)


def _show_current_data():
    """展示当前已导入数据：统计卡片、数据预览、映射状态、清洗异常（只读，不重置任何状态）。"""
    cleaned_df = st.session_state["cleaned_df"]
    raw_df = st.session_state.get("raw_df")
    issues_df = st.session_state.get("issues")
    mapping = st.session_state.get("field_mapping", {})
    source = st.session_state.get("_data_source", "未知来源")

    st.caption(f"数据来源：{source}")

    # 样本量提示：门店数过少时分层结果仅供参考（阈值见 utils/config.py）
    if len(cleaned_df) < cfg.MIN_STORE_SAMPLE:
        st.warning(f"⚠️ 门店样本过少（仅 {len(cleaned_df)} 家门店），分层结果仅供参考")

    # 统计卡片：原始行数 / 清洗后行数 / 异常记录数
    col1, col2, col3 = st.columns(3)
    col1.metric("原始行数", len(raw_df) if raw_df is not None else len(cleaned_df))
    col2.metric("清洗后行数", len(cleaned_df))
    col3.metric("异常记录", len(issues_df) if issues_df is not None else 0)

    # 数据预览（清洗后的完整数据，便于核对）
    st.markdown("**数据预览（清洗后）**")
    st.dataframe(cleaned_df, use_container_width=True)

    # 当前字段映射状态
    if mapping:
        st.markdown("**当前字段映射**")
        mapping_rows = [
            {
                "标准字段": field,
                "已映射源列": (
                    mapping[field]
                    if mapping.get(field) not in (None, data_process.NOT_IMPORTED)
                    else "（未映射）"
                ),
            }
            for field in data_process.STANDARD_FIELDS
        ]
        st.dataframe(pd.DataFrame(mapping_rows), use_container_width=True, hide_index=True)

    # 清洗异常 / 口径修正说明
    if issues_df is not None and len(issues_df) > 0:
        st.warning(f"⚠️ 检测到 {len(issues_df)} 条异常记录，请核实：")
        st.dataframe(issues_df, use_container_width=True)
    else:
        corrected_rows = 0
        if "数据异常标记" in cleaned_df.columns:
            corrected_rows = int((cleaned_df["数据异常标记"].fillna("") != "").sum())
        if corrected_rows > 0:
            st.info(
                f"ℹ️ 已自动修正 {corrected_rows} 行到店数量口径（成交>到店 / 到店>获客），"
                f"详见「数据异常标记」列"
            )
        else:
            st.success("🎉 数据干净，未检测到异常")


# ==================== 页面一：数据导入 ====================
def render_data_import_page():
    """数据导入页面：状态提示、数据管理、文件上传、字段映射、清洗入库。"""
    st.header("📥 数据导入")
    st.caption("上传门店运营数据文件（CSV / XLSX，单文件 ≤ 20MB），并映射到 5 个标准字段")

    # ---------- 顶部状态提示条 ----------
    if _has_imported_data():
        st.success(f"✅ 当前已成功导入 {len(st.session_state['cleaned_df'])} 家门店数据")
    else:
        st.warning("⚠️ 暂未导入数据，请上传文件")

    # ---------- 页面操作区：清空当前数据 / 前往分析诊断 ----------
    op_left, op_right, _ = st.columns([1, 1, 5])
    with op_left:
        if st.button(
            "🗑️ 清空当前数据",
            use_container_width=True,
            help="清空已导入的数据与映射配置，恢复初始状态",
        ):
            # 仅在确有数据时清空并重绘（避免按钮重复触发造成无限重跑）
            had_data = _has_imported_data()
            logger.info("用户清空已导入数据（此前数据状态：%s）", "有数据" if had_data else "无数据")
            _reset_import_state()
            st.session_state["_up_name"] = None
            st.session_state.pop("file_uploader", None)  # 同时清空已上传的文件
            if had_data:
                st.rerun()
    with op_right:
        if st.button(
            "📊 前往分析诊断",
            type="primary",
            use_container_width=True,
            help="切换至分析诊断页查看大盘与分层结果",
        ):
            # 写入待处理 key，下一轮重绘在导航 radio 实例化之前生效；
            # 仅在导航确实变化时重绘（避免按钮重复触发造成无限重跑）
            if st.session_state.get("nav") != "分析诊断":
                st.session_state["_nav_pending"] = "分析诊断"
                st.rerun()

    st.divider()

    # ---------- 已导入数据：直接展示预览与映射状态（不清空、不重置） ----------
    if _has_imported_data():
        _show_current_data()
        st.divider()

    # ---------- 加载示例数据按钮 ----------
    if st.button(
        "✨ 加载示例数据",
        help="加载 data/example_data.csv（15 家模拟门店，含渠道 / 客群字段与典型问题样本），一键体验完整流程",
    ):
        # 已在示例数据状态时不重复加载（避免按钮重复触发造成无限重跑）
        if st.session_state.get("_data_source") != "内置示例数据":
            # 读取示例数据（优先 data/example_data.csv，缺失时回退内置生成器）
            try:
                sample_df = _load_sample_data()
            except Exception:
                logger.exception("示例数据加载失败", exc_info=True)
                st.error("❌ 示例数据加载失败：data/example_data.csv 无法读取，请检查文件内容")
                return

            # 与上传流程一致：字段标准化 → 清洗与异常检测
            with st.spinner("正在加载示例数据并清洗..."):
                cleaned, issues = data_process.clean_data(sample_df)

            # 统一写入三个固定数据 key
            st.session_state["raw_df"] = sample_df
            st.session_state["cleaned_df"] = cleaned
            st.session_state["issues"] = issues
            st.session_state["field_mapping"] = data_process.suggest_mapping(sample_df.columns)
            st.session_state["_data_source"] = "内置示例数据"
            # 与上传控件的当前文件保持一致，避免误触发「文件变化重置」
            current_upload = st.session_state.get("file_uploader")
            st.session_state["_up_name"] = current_upload.name if current_upload is not None else None

            logger.info("示例数据加载完成：%d 家门店，异常记录 %d 条", len(cleaned), len(issues))
            st.success(f"✅ 示例数据已加载并清洗完成（{len(cleaned)} 家门店），可前往分析页")
            st.rerun()

    st.divider()

    # ---------- 文件上传控件 ----------
    uploaded_file = st.file_uploader(
        "选择数据文件",
        type=["csv", "xlsx"],
        key="file_uploader",
        help="支持 CSV（.csv）和 Excel（.xlsx），单文件不超过 20MB",
    )

    # ---------- 文件变化处理：仅在用户上传新文件时重置数据与映射 ----------
    # 仅当上传器中出现「新文件」时才重置；清空上传器（未选择文件）不重置，
    # 已导入数据与映射配置完整保留，避免页面切换 / 误操作导致数据丢失；
    # 需要主动重置时使用页面操作区的「清空当前数据」按钮
    current_name = uploaded_file.name if uploaded_file is not None else None
    if current_name is not None and st.session_state.get("_up_name") != current_name:
        _reset_import_state()
        st.session_state["_up_name"] = current_name

    # 未选择文件时结束本页
    if uploaded_file is None:
        if not _has_imported_data():
            st.info("💡 请上传门店运营数据文件，或点击「加载示例数据」快速体验")
        return

    # ---------- 文件大小限制检查 ----------
    if uploaded_file.size > data_process.MAX_FILE_SIZE:
        st.error(
            f"❌ 文件大小 {uploaded_file.size / 1024 / 1024:.1f}MB，超过 20MB 限制，"
            f"请压缩或拆分后重新上传"
        )
        return

    # ---------- 读取文件（带友好错误提示） ----------
    try:
        df = data_process.load_data(uploaded_file)
    except ValueError as e:
        logger.warning("文件读取被拒绝：%s", e)
        st.error(f"❌ {e}")
        return
    except Exception:
        logger.exception("文件读取失败（非预期异常）", exc_info=True)
        st.error("❌ 文件读取失败，请确认文件格式正确且未损坏")
        return

    # ---------- 原始数据预览（前 5 行） ----------
    st.subheader("📄 原始数据预览（前 5 行）")
    st.dataframe(df.head(5), use_container_width=True)
    st.caption(f"共 {df.shape[0]} 行、{df.shape[1]} 列。若表格显示为空，请检查文件是否包含表头。")

    # ---------- 字段映射 ----------
    st.subheader("🔗 字段映射")
    st.caption(
        "将文件中的列名映射到标准字段。**「（必填）」** 为分层诊断核心字段，"
        "需全部映射后方可完成完整诊断；客单价无需映射，由系统按 销售额 ÷ 成交人数 自动计算；"
        "已根据列名自动推荐映射，可手动调整；「（不导入）」表示忽略该标准字段。"
    )

    # 字段映射说明：标注必填字段与用途（折叠展示，避免占用版面）
    with st.expander("📖 字段映射说明（必填字段与用途）"):
        FIELD_HELP = {
            "门店名称": "门店身份标识，分层与诊断的基础；未映射时无法导入",
            "获客数量": "获客能力评估、获客不足问题判定的核心指标",
            "到店数量": "计算到店转化率，构成转化漏斗（获客 → 到店 → 成交）",
            "成交人数": "计算成交转化率，构成转化漏斗与客群结构分析",
            "销售额": "营收规模评估与 Top 门店排名的基础指标；客单价由 销售额 ÷ 成交人数 自动计算",
        }
        st.dataframe(
            pd.DataFrame(
                {
                    "标准字段": data_process.STANDARD_FIELDS,
                    "是否必填": ["✅ 必填" for _ in data_process.STANDARD_FIELDS],
                    "用途": [FIELD_HELP[f] for f in data_process.STANDARD_FIELDS],
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    # 下拉框选项：不导入 + 文件列名
    options = [data_process.NOT_IMPORTED] + [str(col) for col in df.columns]
    suggestion = data_process.suggest_mapping(df.columns)

    mapping = {}
    col_left, col_right = st.columns(2)
    for i, field in enumerate(data_process.STANDARD_FIELDS):
        # 自动推荐作为默认选中项
        recommended = suggestion.get(field)
        default_index = options.index(str(recommended)) if recommended is not None else 0
        with (col_left if i % 2 == 0 else col_right):
            # 全部标准字段均为必填；客单价为派生字段，无需映射，由清洗阶段自动计算
            mapping[field] = st.selectbox(
                f"标准字段：{field}（必填）",
                options,
                index=default_index,
                key=f"map_{field}",
            )

    # ---------- 确认映射并清洗 ----------
    if st.button("✅ 确认映射并清洗数据", type="primary"):
        # 按映射抽取标准字段列
        mapped_df = data_process.map_columns(df, mapping)

        # 必填字段校验：全部标准字段必须映射（缺失时给出明确提示）；
        # 客单价为派生字段，无需映射，由清洗阶段按 销售额 / 成交人数 自动计算
        missing_required = [
            field for field in data_process.STANDARD_FIELDS
            if mapping.get(field) in (None, data_process.NOT_IMPORTED)
        ]
        if missing_required:
            st.error(
                "❌ 以下必填字段尚未映射，请补齐后再确认："
                + "、".join(missing_required)
            )
            return

        # 门店名称是分层诊断的基础，映射后必须存在有效值
        if "门店名称" not in mapped_df.columns or mapped_df["门店名称"].dropna().empty:
            st.error("❌ 请至少将一列映射为「门店名称」，该字段是诊断分析的基础")
            return

        # 清洗与异常检测（含口径修正），覆盖写入会话状态
        changed = st.session_state.get("_data_source") != uploaded_file.name
        try:
            with st.spinner("正在清洗数据并检测异常..."):
                cleaned, issues = data_process.clean_data(mapped_df)
        except Exception:
            logger.exception("数据清洗失败", exc_info=True)
            st.error("❌ 数据清洗失败：数据中存在无法处理的异常值，请检查文件内容后重试")
            return
        st.session_state["raw_df"] = df
        st.session_state["cleaned_df"] = cleaned
        st.session_state["issues"] = issues
        st.session_state["field_mapping"] = dict(mapping)
        st.session_state["_data_source"] = uploaded_file.name

        logger.info("文件导入成功：%s（%d 行 → 清洗后 %d 行，异常 %d 条）",
                    uploaded_file.name, len(df), len(cleaned), len(issues))
        st.success("✅ 数据导入成功，可前往分析页")
        # 仅在数据来源变化时重绘（避免按钮重复触发造成无限重跑）
        if changed:
            st.rerun()


# ==================== 页面二：分析诊断 ====================
def render_diagnosis_page():
    """分析诊断页面：计算运营指标并输出门店分层诊断结果。"""
    st.header("🔍 分析诊断")
    st.caption("基于已导入的门店运营数据，进行指标计算与分层诊断")

    # 检查是否已导入数据
    if not _has_imported_data():
        st.warning("⚠️ 尚未导入数据，请先在数据导入页上传门店数据，再进行诊断分析。")
        return

    df = st.session_state["cleaned_df"]

    # 样本量提示：门店数过少时分层结果仅供参考（阈值见 utils/config.py）
    if len(df) < cfg.MIN_STORE_SAMPLE:
        st.warning(f"⚠️ 门店样本过少（仅 {len(df)} 家门店），分层结果仅供参考")

    # 指标计算 → 分层 → 报告生成：统一异常兜底，异常数值不向页面抛堆栈；
    # 异常明细写入日志（logs/app.log），调试时设置 STORE_DIAG_LOG_LEVEL=DEBUG 查看
    try:
        # 计算运营指标
        with st.spinner("正在计算运营指标..."):
            metric_df = metrics.calc_basic_metrics(df)
        # 门店分层
        with st.spinner("正在进行门店分层诊断..."):
            level_df = leveling.leveling_stores(metric_df)
        logger.info(
            "诊断流水线完成：%d 家门店 → 指标 %d 列 → 分层 %d 家",
            len(df), len(metric_df.columns), len(level_df),
        )
        # 生成诊断报告
        with st.spinner("正在生成诊断报告..."):
            report.render_report(level_df)
    except Exception:
        logger.exception("诊断计算失败", exc_info=True)
        st.error("❌ 诊断计算失败：数据中存在无法处理的异常值，请检查数据后重试（详细错误见日志 logs/app.log）")


# ==================== 调试日志面板 ====================
def _render_sidebar_log_panel():
    """
    侧边栏日志面板：仅在 STORE_DIAG_LOG_LEVEL=DEBUG 时展示（logs/app.log 尾部 30 行），
    便于联调排查；非 DEBUG 模式下不渲染任何内容。
    """
    if os.environ.get("STORE_DIAG_LOG_LEVEL", "").upper() != "DEBUG":
        return
    # 日志路径与 logging_setup 保持一致（环境变量可覆盖）
    log_dir = Path(os.environ.get(
        "STORE_DIAG_LOG_DIR", Path(__file__).resolve().parent / "logs"))
    log_file = Path(os.environ.get("STORE_DIAG_LOG_FILE", log_dir / "app.log"))
    with st.expander("🔍 调试日志（DEBUG）", expanded=False):
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()[-30:]
            st.code("\n".join(lines), language="text")
        except OSError:
            st.caption("暂无日志文件（logs/app.log）")


# ==================== 主入口 ====================
def main():
    """主函数：设置侧边栏导航，并根据选择渲染对应页面。"""
    # 处理「前往分析诊断」按钮的页面切换请求：
    # 在导航 radio 实例化之前写入其会话 key，避免「widget 实例化后不可修改」冲突
    pending_page = st.session_state.pop("_nav_pending", None)
    if pending_page is not None:
        st.session_state["nav"] = pending_page

    # 侧边栏导航（key 绑定会话状态，支持「前往分析诊断」按钮编程切换）
    with st.sidebar:
        st.title(f"{cfg.PAGE_ICON} {cfg.APP_TITLE}")
        st.divider()
        page = st.radio(
            "功能导航",
            ["数据导入", "分析诊断"],
            index=0,
            key="nav",
        )
        st.divider()
        st.caption(f"版本 v{__version__}")
        _render_sidebar_log_panel()

    # 根据导航选择渲染对应页面
    if page == "数据导入":
        render_data_import_page()
    elif page == "分析诊断":
        render_diagnosis_page()


if __name__ == "__main__":
    main()
