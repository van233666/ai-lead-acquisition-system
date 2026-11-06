"""线索挖掘服务 —— 复刻 UAtool 的 lead_mining_service.run_skill 主流程。

真实系统流程（UAtool）：
    选技能+关键词 → Playwright 打开平台搜索页 → 抓取公开帖子标题/链接
    → 去重 → 隐私过滤 → 广告过滤 → 意向句式匹配 → 需求分级 → 入库

ua-mini 用 MOCK_CORPUS 模拟"抓取结果"，其余步骤完全复刻，
这样你能一行行看懂每道过滤是干什么的、为什么这么设计。
"""
import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Lead, MiningSkill
from app.services.lead import lead_exists
from app.seed import MOCK_CORPUS

logger = logging.getLogger("mining")

# ---------- 过滤规则（和 UAtool 同源设计） ----------

# 隐私红线：命中即丢弃。手机号 + 微信号/QQ 是最典型的隐私字段。
PRIVACY_PATTERNS = [
    r"1[3-9]\d{9}",          # 大陆手机号
    r"微信\s*[:：]?\s*\w{4,}",  # 微信号
    r"[Vv][Xx]\s*[:：]?\s*\w{4,}",  # VX 缩写
    r"[Qq][Qq]号?\s*[:：]?\s*\d{5,}",  # QQ 号
]

# 广告营销特征：命中即丢弃（加我/扫码/免费领/限时等引流词）
AD_CUES = ["加我", "加微信", "扫码", "免费领取", "免费送", "限时",
           "全网最低", "私我", "低价", "优惠", "白皮书", "选校方案"]

# 弱化词：帖子正文太短、没有信息量也直接丢弃（防垃圾条目入库）
MIN_CONTENT_LEN = 4


def _contains_privacy(text: str) -> bool:
    """合规红线：任何隐私字段都不入库。"""
    for pattern in PRIVACY_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def _is_ad_content(text: str) -> bool:
    """广告营销内容：直接丢弃，避免垃圾线索污染线索池。"""
    return any(cue in text for cue in AD_CUES)


def _match_cue(text: str, cue_keywords: list) -> str:
    """意向句式匹配：命中任一意向句式即认为有强需求信号。

    返回命中的句式（用于展示和分析），没命中返回空字符串。
    对照 UAtool lead_mining_service._match_cue。
    """
    for cue in cue_keywords:
        if cue and cue in text:
            return cue
    return ""


def _normalize(text: str) -> str:
    """归一化：去掉空白和标点，用于去重比较。"""
    return re.sub(r"[\s\u3000，。！？、,.!?;；:：'\"']", "", text or "")


def _dedup_items(items: list) -> list:
    """按正文归一化后去重（同一帖子可能被多个检索词重复抓到）。"""
    seen = set()
    result = []
    for it in items:
        key = _normalize(it.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(it)
    return result


def run_mining(db: Session, skill: MiningSkill, keyword: str) -> dict:
    """执行一次线索挖掘（对应 UAtool run_skill 的步骤1-4）。

    流程：
      步骤1 记录业务关键词
      步骤2 模拟检索：用关键词在语料里捞候选（真实系统=浏览器搜索抓取）
      步骤3 强制过滤：去重 → 隐私 → 广告 → 长度 → 意向句式匹配 → 需求分级
      步骤4 按技能 max_leads 截断入库
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"success": False, "message": "请提供业务关键词，例如：香港留学"}

    cue_keywords = [k for k in (skill.keywords or []) if k]

    # ---- 步骤2：模拟检索（真实系统调用 browser_service.search_and_scrape）----
    raw_items = [
        it for it in MOCK_CORPUS
        if keyword in it["title"]
    ]

    # ---- 步骤3：过滤流水线 ----
    kept, dropped_ad, dropped_privacy = [], 0, 0
    for it in _dedup_items(raw_items):
        text = (it.get("title") or "").strip()
        if len(text) < MIN_CONTENT_LEN:
            continue
        if _contains_privacy(text):
            dropped_privacy += 1
            continue                # 隐私红线：直接丢弃
        if _is_ad_content(text):
            dropped_ad += 1
            continue                # 广告营销：直接丢弃
        cue = _match_cue(text, cue_keywords)
        kept.append({
            "platform": it["platform"],
            "content": text[:500],
            "content_url": it.get("url", ""),
            "author_name": it.get("author", ""),
            "demand_level": "high" if cue else "low",   # 命中句式=强需求
            "matched_cue": cue or "",
        })

    # ---- 步骤4：强需求优先，截断到 max_leads，入库 ----
    kept.sort(key=lambda x: 0 if x["demand_level"] == "high" else 1)
    final_leads = kept[: skill.max_leads]

    now = datetime.now()
    for lead in final_leads:
        if lead_exists(db, lead["content"]):  # 已入库过的同一条帖子 → 跳过
            continue
        db.add(Lead(skill_id=skill.id, keyword=keyword, created_at=now, **lead))

    skill.last_run_at = now
    skill.run_count = (skill.run_count or 0) + 1
    db.commit()

    high_count = sum(1 for l in final_leads if l["demand_level"] == "high")
    logger.info("挖掘完成: keyword=%s raw=%d kept=%d ad=%d privacy=%d high=%d",
                keyword, len(raw_items), len(final_leads), dropped_ad, dropped_privacy, high_count)

    return {
        "success": True,
        "keyword": keyword,
        "raw_count": len(raw_items),
        "kept_count": len(final_leads),
        "high_count": high_count,
        "dropped_ad": dropped_ad,
        "dropped_privacy": dropped_privacy,
        "message": f"抓取 {len(raw_items)} 条，合格 {len(final_leads)} 条（强需求 {high_count} 条；广告拦截 {dropped_ad}、隐私拦截 {dropped_privacy}）",
    }
