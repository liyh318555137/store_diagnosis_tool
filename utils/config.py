# -*- coding: utf-8 -*-
"""
业务配置中心 —— 换零售业态 / 调口径时只改本文件，不碰算法代码

本模块是全部业务参数的「单一事实源」：
    - 字段体系（标准字段 / 渠道字段 / 客群字段 / 描述字段 / 别名映射）
    - 分层模型（五维配置、分级分界、标签阈值）
    - 诊断引擎（规则、优势候选、建议库）
    - 应用与主题（标题 / 图标 / 配色）

各业务模块（metrics / leveling / report / data_process）只从本模块读取，
不在自身代码中定义业务常量，保证「改配置即换业态」。

换业态示例（餐饮）：
    - CHANNEL_FIELDS / CUSTOMER_FIELDS 换成该业态的渠道与客群拆分口径
    - FIELD_ALIASES / CHANNEL_NAME_MAP 同步替换
    - DIMENSIONS 调整维度与权重（如人效 / 坪效维度）
    - SUGGESTION_BANK 建议文案改为该业态可落地的说法
    改完后运行 validate_config() 自动校验一致性，通过即可直接使用。

使用方式：
    from . import config as cfg
    cfg.CHANNEL_FIELDS / cfg.DIMENSIONS / cfg.THEME_PRIMARY_BLUE ...
"""

# ==================== 一、字段体系 ====================

# 输入标准字段（5 个）：界面「字段映射」强制映射，分层与诊断的基础。
# 客单价为派生字段，不在此列：由清洗阶段按 销售额 / 成交人数 自动计算
STANDARD_FIELDS = ["门店名称", "获客数量", "到店数量", "成交人数", "销售额"]

# 引擎必选字段（标准字段 + 派生字段客单价，下游指标计算依赖）
REQUIRED_FIELDS = ["门店名称", "获客数量", "到店数量", "成交人数", "销售额", "客单价"]

# 可选渠道字段：按获客来源拆分（6 大渠道）
CHANNEL_FIELDS = [
    "自然流量获客", "线上引流获客", "转介绍获客", "异业合作获客", "线下拓客获客", "活动获客",
]

# 可选客群字段：按客户类型拆分成交
CUSTOMER_FIELDS = ["老客成交数", "会员成交数", "高客单成交数"]

# 描述性字段（非指标，穿透保留供明细展示：门店类型、门店店长等）
DESCRIPTIVE_FIELDS = ["门店类型", "门店店长"]

# 优质渠道：转介绍 + 异业合作（高转化、低成本，分层诊断时重点关注）
QUALITY_CHANNELS = ["转介绍获客", "异业合作获客"]

# 固定上传字段的别名映射（业务字段名 → 引擎标准字段名）
# 上传文件中出现左侧列名时，读取后自动标准化为右侧标准名，
# 使渠道 / 客群指标计算与分层模型无需感知业务命名差异。
FIELD_ALIASES = {
    # 渠道字段（6 大渠道：线上引流 / 转介绍 / 自然流量 / 异业合作 / 线下拓客 / 活动营销）
    "线上引流": "线上引流获客",
    "转介绍": "转介绍获客",
    "自然流量": "自然流量获客",
    "异业合作": "异业合作获客",
    "线下拓客": "线下拓客获客",
    "活动营销": "活动获客",
    # 客群字段（业务口径近似映射）
    "会员人数": "会员成交数",
    "套购成交数": "高客单成交数",
}

# 渠道标准字段名 → 展示短名（标签 / 图表使用）
CHANNEL_NAME_MAP = {
    "自然流量获客": "自然流量",
    "线上引流获客": "线上引流",
    "转介绍获客": "转介绍",
    "异业合作获客": "异业合作",
    "线下拓客获客": "线下拓客",
    "活动获客": "活动营销",
}

# 统一保留的小数位数（指标计算与展示）
DECIMAL_PLACES = 2

# ==================== 二、数据导入 ====================

# 上传文件大小上限：20MB
MAX_FILE_SIZE = 20 * 1024 * 1024

# 映射下拉框中「不导入」选项的占位文案
NOT_IMPORTED = "（不导入）"

# 最小样本量：清洗后门店数低于该值时，提示分层结果仅供参考
MIN_STORE_SAMPLE = 5

# ==================== 三、分层模型（一级五维 + 二级标签） ====================

# 五维配置：name 维度名 / weight 权重 / indicators 候选指标（按优先级取第一个可用的）
DIMENSIONS = [
    {"name": "营收规模", "weight": 0.25, "indicators": ["销售额"]},
    {"name": "获客能力", "weight": 0.20, "indicators": ["获客数量"]},
    {"name": "转化效率", "weight": 0.25, "indicators": ["成交转化率", "总转化率"]},
    {
        "name": "客群质量",
        "weight": 0.15,
        "indicators": ["老客成交数占比", "会员成交数占比", "高客单成交数占比", "客单价"],
    },
    {"name": "渠道健康度", "weight": 0.15, "indicators": ["渠道丰富度", "优质渠道占比"]},
]

# 分级比例分界点（S/A/B 的排名百分比上限，C 级为剩余部分）
GRADE_RATIOS = [0.2, 0.5, 0.8]
GRADE_LABELS = ["S", "A", "B", "C"]

# 标签判定阈值
TAG_THRESHOLDS = {
    "channel_drive_ratio": 0.40,      # 渠道驱动型：最高渠道占比阈值
    "channel_single_max": 2,          # 渠道单一型：有效渠道数上限
    "old_customer_ratio": 0.40,       # 老客复购型：老客占比阈值
    "high_value_multiple": 1.5,       # 高净值型：客单价超全店均值的倍数
    "channel_malformed_ratio": 0.70,  # 渠道畸形：最高渠道占比阈值
    "channel_malformed_max": 1,       # 渠道畸形：有效渠道数上限
}

# ==================== 四、诊断引擎（规则 / 建议库） ====================

# 指标列名 → 诊断文案展示名（对外输出使用业务口径）
METRIC_DISPLAY_NAMES = {
    "销售额": "销售额",
    "获客数量": "获客量",
    "到店数量": "到店量",
    "成交人数": "成交量",
    "到店转化率": "到店转化率",
    "成交转化率": "成交转化率",
    "总转化率": "获客转化率",
    "客单价": "客单价",
    "渠道丰富度": "渠道丰富度",
    "优质渠道占比": "高价值渠道占比",
    "会员成交数占比": "会员渗透率",
    "高客单成交数占比": "套购率",
    "老客成交数占比": "老客占比",
}

# 诊断规则：issue 问题名 / cols 候选指标列（按顺序取第一个有数据的）/ direction 比较方向
#   low  = 门店值低于整体均值即命中；high = 门店值高于整体均值即命中
DIAGNOSIS_RULES = [
    # ---- 渠道层面 ----
    {"issue": "渠道单一", "cols": ["渠道丰富度"], "direction": "low"},
    {"issue": "活动过度依赖", "cols": ["活动获客占比"], "direction": "high"},
    {"issue": "高价值渠道占比不足", "cols": ["优质渠道占比"], "direction": "low"},
    # ---- 客群层面 ----
    {"issue": "会员渗透率低", "cols": ["会员成交数占比"], "direction": "low"},
    {"issue": "套购率低", "cols": ["高客单成交数占比"], "direction": "low"},
    {"issue": "新客主导", "cols": ["老客成交数占比"], "direction": "low"},
    # ---- 转化层面 ----
    {"issue": "获客不足", "cols": ["获客数量"], "direction": "low"},
    {"issue": "转化低效", "cols": ["成交转化率", "总转化率"], "direction": "low"},
]
# 规则问题判定顺序（大盘共性问题统计使用，复合规则「高获客低转化」排在最后）
ISSUE_ORDER = [rule["issue"] for rule in DIAGNOSIS_RULES] + ["高获客低转化"]

# 优势候选指标：门店值高于整体均值即记为优势
ADVANTAGE_COLUMNS = [
    "销售额", "获客数量", "到店数量", "成交人数",
    "到店转化率", "成交转化率", "总转化率",
    "客单价", "渠道丰富度", "优质渠道占比",
    "会员成交数占比", "高客单成交数占比", "老客成交数占比",
]

# 命中问题后不再作为优势展示的指标（避免优劣势自相矛盾）
ISSUE_EXCLUDES = {
    "获客不足": ["获客数量"],
    "会员渗透率低": ["会员成交数占比"],
    "套购率低": ["高客单成交数占比"],
    "新客主导": ["老客成交数占比"],
    "渠道单一": ["渠道丰富度"],
    "高价值渠道占比不足": ["优质渠道占比"],
}

# 大盘「共性问题」判定：超过半数（≥50%）有效门店命中即记为共性问题
COMMON_ISSUE_RATE = 0.5

# 建议库：key 为门店标签（渠道 / 客群 / 问题标签）或规则问题名，value 为可落地建议
SUGGESTION_BANK = {
    # ---- 渠道标签 ----
    "渠道单一型": "拓展线上引流与异业合作等新渠道，把获客结构从单一依赖转为多元组合，降低渠道集中风险",
    "自然流量驱动型": "在保持自然流量优势的同时，加大转介绍、异业等高价值渠道投入，提升客群质量与转化",
    "线上引流驱动型": "持续优化线上投放效率，叠加转介绍激励与会员老带新，把公域流量沉淀为私域复购",
    "转介绍驱动型": "转介绍是性价比最高的渠道，建议将老客推荐激励常态化（佣金 / 积分），并复制经验到异业合作",
    "异业合作驱动型": "异业合作成效显著，建议扩展合作商户数量与品类，并用企微 / 社群承接合作流量长期留存",
    "线下拓客驱动型": "线下拓客强劲，建议补强线上承接与回访机制，提升获客后的到店与成交转化",
    "活动营销驱动型": "降低对价格型促销的依赖，用会员体系与转介绍激励替代活动引流，改善毛利与获客质量",
    # ---- 客群标签 ----
    "老客复购型": "强化会员权益（积分 / 专属折扣 / 生日礼）并设立老带新激励，把老客口碑转化为新客增长",
    "高净值型": "为高净值客群提供专属套餐与一对一定制服务，重点经营复购与大单，沉淀标杆案例",
    "泛客流低效型": "客流充足但转化偏低，建议建立到店接待 SOP 与销售话术培训，并对高意向客户建立跟进机制",
    # ---- 问题标签 ----
    "获客不足": "制定月度获客目标并分解到人，重点加投转介绍与异业合作等低成本高转化渠道",
    "转化低效": "梳理从到店到成交的流失环节，开展话术与跟进机制培训，提升成交转化率",
    "客单偏低": "设计套餐组合与升级销售话术，引导连带购买与高客单产品，提升客单价",
    "渠道畸形": "重构渠道结构，压降单一主导渠道占比，分阶段引入 2-3 个新渠道分散风险",
    # ---- 规则问题（补充建议用） ----
    "渠道单一": "拓展线上引流与异业合作等新渠道，把获客结构从单一依赖转为多元组合，降低渠道集中风险",
    "活动过度依赖": "降低对价格型促销的依赖，用会员体系与转介绍激励替代活动引流，改善毛利与获客质量",
    "高价值渠道占比不足": "提高转介绍与异业合作投入占比，逐步替换低效引流渠道，提升获客质量与转化",
    "会员渗透率低": "建立入会激励机制（入会礼 / 积分），到店顾客优先引导注册会员，提升会员渗透率",
    "套购率低": "推出主品 + 配件 / 延保等套购组合，培训员工连带销售话术，提升套购率",
    "新客主导": "新客占比偏高，建立首单回访与会员日复购机制，把一次性客流转化为复购客群",
    "高获客低转化": "获客量充足但转化偏弱，重点提升到店体验与销售专业度，把流量红利转化为成交",
}

# 建议不足 3 条时的通用兜底建议
GENERIC_SUGGESTIONS = [
    "加强门店团队培训，梳理「获客→到店→成交」全流程 SOP，持续提升转化效率",
    "建立周度经营复盘机制，紧盯获客、到店、成交三率与客单价变化，及时调整打法",
]

# ==================== 五、应用与主题 ====================

APP_TITLE = "通用门店运营分层诊断系统"
PAGE_ICON = "🏪"

# 统一配色（深蓝商务主题）：全部卡片 / 标签 / 图表共用，保证全站配色一致。
# 品牌蓝色阶：标题 / 表头 / 主系列 / 网格分隔
PRIMARY_BLUE = "#1F4E79"   # 主深蓝（标题 / 表头 / 卡片描边）
BLUE_600 = "#2E75B6"       # 深蓝辅助
BLUE_500 = "#5B9BD5"       # 中蓝（主系列色）
BLUE_400 = "#8FAADC"       # 浅蓝
BLUE_300 = "#B4C7E7"       # 极浅蓝（网格 / 分隔线）

# 中性色：卡片文字 / 边框 / 表格分隔
INK = "#333333"            # 正文
MUTED_TEXT = "#8A94A6"     # 次要文字（卡片标签）
FAINT_TEXT = "#B0B8C4"     # 弱文字（占比说明）
CARD_BORDER = "#E3EAF2"    # 卡片边框
TABLE_BORDER = "#E8EEF5"   # 表格行分隔线
ROW_ALT_BG = "#F5F8FC"     # 表格斑马纹
ROW_HOVER_BG = "#EAF2FB"   # 表格悬停底色

# 门店等级徽章配色（状态色，全局唯一：S 金 / A 绿 / B 蓝 / C 红）
GRADE_COLORS = {
    "S": "#D4AF37",
    "A": "#2E8B57",
    "B": "#4682B4",
    "C": "#CD5C5C",
}

# 渠道分类色（固定顺序，所有渠道饼图统一使用，勿改顺序）：
# 经相邻色可区分性校验，3 个品牌蓝不再相邻，弱区分度的极浅蓝已替换为紫色
CHANNEL_PIE_COLORS = ["#1F4E79", "#C55A11", "#2E75B6", "#548235", "#8E6FB8", "#129999"]

# 表格标签配色（蓝 = 渠道标签，红 = 问题标签）
TAG_BLUE_BG = "#E3EEF9"
TAG_BLUE_TEXT = PRIMARY_BLUE
TAG_BLUE_BORDER = "#9DC3E6"
TAG_RED_BG = "#FBEAEA"
TAG_RED_TEXT = "#C0504D"
TAG_RED_BORDER = "#E8B4B4"

# 对比差异颜色（高 / 低 / 持平）
DELTA_UP = "#2E8B57"
DELTA_DOWN = "#C0504D"
DELTA_NEUTRAL = MUTED_TEXT


# ==================== 配置校验 ====================
def validate_config() -> list:
    """
    校验配置一致性，返回问题列表（空列表 = 全部通过）。

    在应用启动与测试中调用；配置改错时立即给出明确问题，
    避免「改完配置后分层 / 诊断静默异常」。
    """
    problems = []

    # 1. 标准字段唯一
    if len(set(STANDARD_FIELDS)) != len(STANDARD_FIELDS):
        problems.append(f"STANDARD_FIELDS 存在重复字段：{STANDARD_FIELDS}")

    # 2. 渠道 / 客群 / 描述字段与标准字段不重叠
    standard_set = set(STANDARD_FIELDS)
    for group_name, group in [("CHANNEL_FIELDS", CHANNEL_FIELDS),
                              ("CUSTOMER_FIELDS", CUSTOMER_FIELDS),
                              ("DESCRIPTIVE_FIELDS", DESCRIPTIVE_FIELDS)]:
        overlap = standard_set & set(group)
        if overlap:
            problems.append(f"{group_name} 与 STANDARD_FIELDS 重叠：{sorted(overlap)}")
        if len(set(group)) != len(group):
            problems.append(f"{group_name} 存在重复字段：{group}")

    # 3. 优质渠道必须是渠道字段的子集
    bad_quality = [c for c in QUALITY_CHANNELS if c not in CHANNEL_FIELDS]
    if bad_quality:
        problems.append(f"QUALITY_CHANNELS 不在 CHANNEL_FIELDS 中：{bad_quality}")

    # 4. 别名映射目标必须是渠道 / 客群字段
    alias_targets = set(FIELD_ALIASES.values())
    allowed_targets = set(CHANNEL_FIELDS) | set(CUSTOMER_FIELDS)
    bad_aliases = sorted(alias_targets - allowed_targets)
    if bad_aliases:
        problems.append(f"FIELD_ALIASES 映射目标不在渠道 / 客群字段中：{bad_aliases}")

    # 5. 渠道展示名映射与渠道字段一一对应
    if set(CHANNEL_NAME_MAP.keys()) != set(CHANNEL_FIELDS):
        problems.append("CHANNEL_NAME_MAP 的 key 与 CHANNEL_FIELDS 不完全一致")

    # 6. 分层维度：名称唯一、权重和 ≈ 1、候选指标非空
    dim_names = [d["name"] for d in DIMENSIONS]
    if len(set(dim_names)) != len(dim_names):
        problems.append(f"DIMENSIONS 存在重复维度名：{dim_names}")
    total_weight = sum(d["weight"] for d in DIMENSIONS)
    if abs(total_weight - 1.0) > 1e-6:
        problems.append(f"DIMENSIONS 权重之和为 {total_weight}，应等于 1（当前误差 {total_weight - 1.0:+.2e}）")
    for dim in DIMENSIONS:
        if not dim.get("indicators"):
            problems.append(f"维度「{dim.get('name')}」的 indicators 为空")

    # 7. 分级标签与分界点配套（labels = ratios + 1）
    if len(GRADE_LABELS) != len(GRADE_RATIOS) + 1:
        problems.append(
            f"GRADE_LABELS（{len(GRADE_LABELS)} 个）须比 GRADE_RATIOS（{len(GRADE_RATIOS)} 个）多 1 个"
        )
    if any(not (0 < r < 1) for r in GRADE_RATIOS) or GRADE_RATIOS != sorted(GRADE_RATIOS):
        problems.append(f"GRADE_RATIOS 须为 (0,1) 内的升序列表：{GRADE_RATIOS}")
    if GRADE_LABELS[-1] == "":
        problems.append("GRADE_LABELS 最后一个标签不能为空")

    # 8. 标签阈值 key 完整
    required_threshold_keys = {
        "channel_drive_ratio", "channel_single_max", "old_customer_ratio",
        "high_value_multiple", "channel_malformed_ratio", "channel_malformed_max",
    }
    missing_keys = required_threshold_keys - set(TAG_THRESHOLDS.keys())
    if missing_keys:
        problems.append(f"TAG_THRESHOLDS 缺少配置项：{sorted(missing_keys)}")

    # 9. 建议库必须覆盖所有标签名与规则问题名（诊断结论依赖，缺了会静默少建议）
    #    标签名清单与 leveling 模块的标签产出规则保持同步
    leveling_tags = set()
    for ch in CHANNEL_FIELDS:
        leveling_tags.add(f"{CHANNEL_NAME_MAP[ch]}驱动型")  # 渠道标签（_channel_tags 产出）
    leveling_tags.update([
        "渠道单一型",                                        # 渠道标签
        "老客复购型", "高净值型", "泛客流低效型",            # 客群标签（_customer_tags 产出）
        "获客不足", "转化低效", "客单偏低", "渠道畸形",      # 问题标签（_issue_tags 产出）
    ])
    missing_suggestions = sorted(leveling_tags - set(SUGGESTION_BANK.keys()))
    if missing_suggestions:
        problems.append(f"SUGGESTION_BANK 缺少标签建议：{missing_suggestions}")
    for rule in DIAGNOSIS_RULES:
        if rule["issue"] not in SUGGESTION_BANK:
            problems.append(f"SUGGESTION_BANK 缺少规则问题建议：{rule['issue']}")
    if "高获客低转化" not in SUGGESTION_BANK:
        problems.append("SUGGESTION_BANK 缺少复合问题建议：高获客低转化")

    # 10. 颜色格式校验（#RRGGBB）
    color_values = {
        "PRIMARY_BLUE": PRIMARY_BLUE, "BLUE_600": BLUE_600,
        "BLUE_500": BLUE_500, "BLUE_400": BLUE_400, "BLUE_300": BLUE_300,
        "INK": INK, "MUTED_TEXT": MUTED_TEXT, "FAINT_TEXT": FAINT_TEXT,
        "CARD_BORDER": CARD_BORDER, "TABLE_BORDER": TABLE_BORDER,
        "ROW_ALT_BG": ROW_ALT_BG, "ROW_HOVER_BG": ROW_HOVER_BG,
        "GRADE_COLORS": GRADE_COLORS, "CHANNEL_PIE_COLORS": CHANNEL_PIE_COLORS,
        "TAG_BLUE_BG": TAG_BLUE_BG, "TAG_BLUE_TEXT": TAG_BLUE_TEXT,
        "TAG_BLUE_BORDER": TAG_BLUE_BORDER, "TAG_RED_BG": TAG_RED_BG,
        "TAG_RED_TEXT": TAG_RED_TEXT, "TAG_RED_BORDER": TAG_RED_BORDER,
        "DELTA_UP": DELTA_UP, "DELTA_DOWN": DELTA_DOWN, "DELTA_NEUTRAL": DELTA_NEUTRAL,
    }
    for name, value in color_values.items():
        if isinstance(value, str) and not _is_hex_color(value):
            problems.append(f"颜色常量 {name} 格式应为 #RRGGBB：{value}")
        elif isinstance(value, dict):
            for k, v in value.items():
                if not _is_hex_color(v):
                    problems.append(f"颜色常量 {name}[{k}] 格式应为 #RRGGBB：{v}")
        elif isinstance(value, list):
            for v in value:
                if not _is_hex_color(v):
                    problems.append(f"颜色常量 {name} 元素格式应为 #RRGGBB：{v}")

    return problems


def _is_hex_color(value: str) -> bool:
    """是否为 #RRGGBB 格式颜色（用于配置校验）。"""
    return (isinstance(value, str) and len(value) == 7 and value[0] == "#"
            and all(c in "0123456789abcdefABCDEF" for c in value[1:]))
