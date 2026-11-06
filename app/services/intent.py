"""意向判定与 AI 回复 —— 复刻 UAtool 的两层设计。

UAtool 的 ai_service.py 核心分层：
1. 规则层（judge_intent / _judge_intent_rule）：关键词命中 + 表单字段 → 秒判意向，
   零成本、可解释、离线可用 —— 这是兜底，永远可用。
2. LLM 层（judge_intent_llm / _call_llm_structured）：调用大模型做结构化判断，
   质量更高但花钱、有延迟、可能熔断 —— 是增强，不是必需。
真实系统用 token_manager 做密钥轮换/配额/熔断；ua-mini 只保留规则层 +
一个"mock LLM"演示层，让你看清两层怎么协作。
"""
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Comment

logger = logging.getLogger("intent")

# ===== 熔断降级演示开关（第 13 天任务用）=====
# 改成 True 模拟"大模型 API 故障"，看系统如何用规则兜底，不会瘫。
LLM_FAULTY = False

# ---------- 意向关键词库（规则层） ----------
# 对照 UAtool 的 _judge_intent_rule 和 keyword_library 配置。
HIGH_CUES = [  # 强意向：明确购买/咨询/预算/时间诉求
    "多少钱", "报价", "价格", "怎么收费", "预算", "求推荐", "想申请",
    "准备申请", "需要", "求助", "哪家好", "有没有", "咨询", "报名",
    "来得及", "怎么办", "求支招","有戏",
]
NORMAL_CUES = [  # 中意向：一般性提问，可能是潜在客户
    "怎么样", "如何", "流程", "材料", "要求", "难不难", "值不值",
    "对比", "区别", "经验",
]
LOW_CUES = [  # 低意向/噪音：闲聊、无信息量
    "哈哈哈", "路过", "看看", "顶", "沙发", "不错",
]

# 评分基础：命中 high 句式 +40，normal +15，low 不计分；上限 100
SCORE_BASE = 30
SCORE_HIGH = 40
SCORE_NORMAL = 15


def judge_intent_by_rule(text: str) -> tuple[str, int, list[str]]:
    """规则层意向判定。

    返回 (intent_level, score, matched_keywords)。
    对照 UAtool 的 _judge_intent_rule：规则命中优先于 LLM 兜底。
    """
    matched = []
    score = SCORE_BASE
    level = "low"

    for cue in HIGH_CUES:
        if cue in text:
            matched.append(cue)
            score += SCORE_HIGH
    for cue in NORMAL_CUES:
        if cue in text:
            matched.append(cue)
            score += SCORE_NORMAL
    for cue in LOW_CUES:
        if cue in text:
            matched.append(cue)
            score -= 10

    score = max(0, min(100, score))          # 夹到 0-100
    if score >= 70:
        level = "high"
    elif score >= 45:
        level = "normal"
    else:
        level = "low"
    return level, score, matched


def mock_llm_reply(text: str, matched: list[str]) -> str:
    """演示"AI 接待回复"层。

    真实系统：调用大模型 API，把 SOP 话术模板 + 知识库检索结果拼进
    system prompt，让模型生成自然回复（见 ai_service._build_system_prompt_v2）。
    这里用模板拼接演示同样的效果：命中不同句式 → 走不同话术分支。
    """
    if LLM_FAULTY:                       # 模拟大模型 API 故障
        raise RuntimeError("模拟 LLM API 故障：密钥熔断")
    if not matched:
        return "感谢您的关注，请问您具体想了解哪方面呢？"
    if any(k in ("多少钱", "报价", "价格", "怎么收费", "预算") for k in matched):
        return "您好！我们根据目标和背景提供差异化方案，一般预算区间在 X 万起，方便说说您的具体情况吗？"
    # 新增话术分支：命中"来得及" → 走时间线安抚话术
    if "来得及" in matched:
        return "时间来得及：港校按轮次录取，现在准备还能赶上下一轮。要不要先帮您做个背景评估？"

    if any(k in ("求推荐", "哪家好", "有没有", "怎么办", "求支招") for k in matched):
        return "您好！看到您正在挑选，我们可以先免费帮您评估背景并给出选校建议，需要帮您看看吗？"
    return "您好！已收到您的咨询，我们会安排顾问尽快联系您，请问方便提供更多背景信息吗？"


def analyze_comment(db: Session, platform: str, nickname: str, content: str) -> dict:
    """处理一条新评论：规则判定意向 + 打分 + 记录。

    对照 UAtool 的 platform_monitor_service._analyze_new_comments：
    采集到的新评论先过 AI 判定，高意向优先进入线索池 / 触发通知。
    """
    level, score, matched = judge_intent_by_rule(content)
    comment = Comment(
        platform=platform,
        nickname=nickname,
        content=content,
        intent_level=level,
        intent_score=score,
        matched_keywords=",".join(matched),
        is_processed=False,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # 先尝试"LLM 生成"，失败自动降级到规则兜底 —— 这就是 UAtool 的双层设计
    try:
        reply = mock_llm_reply(content, matched)
    except Exception as e:
        logger.warning("LLM 回复失败，走规则兜底: %s", e)
        reply = "（规则兜底）已收到您的咨询，顾问会尽快联系您。"
    return {
        "id": comment.id,
        "intent_level": level,
        "intent_score": score,
        "matched_keywords": matched,
        "ai_reply": reply,
    }


# ---------- 演示用评论池（真实系统由 Playwright 抓取） ----------
DEMO_COMMENTS = [
    ("xiaohongshu", "西瓜不甜", "请问申请香港硕士多少钱？中介费大概什么水平"),
    ("xiaohongshu", "远山", "有没有推荐的文书老师，之前踩过坑"),
    ("douyin", "柠檬精", "想申请25fall，现在准备还来得及吗"),
    ("douyin", "清风", "这视频讲得不错，路过看看"),
    ("xiaohongshu", "小王同学", "求问双非均分90申港三有戏吗"),
    ("douyin", "广告菌", "加我微信免费领取选校攻略"),
]


def run_comment_batch(db: Session) -> dict:
    """模拟一次评论采集+判定批次（对应定时任务 platform_comment_monitor_task）。"""
    results = []
    for platform, nickname, content in DEMO_COMMENTS:
        # 演示数据每轮都新入库；真实系统会用 comment_id 做幂等去重
        r = analyze_comment(db, platform, nickname, content)
        results.append({"platform": platform, "nickname": nickname,
                        "content": content, **r})
    high = sum(1 for r in results if r["intent_level"] == "high")
    return {"total": len(results), "high": high, "items": results}
