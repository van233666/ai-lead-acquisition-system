"""线索管理与统计 —— 复刻 UAtool 的 lead 相关服务。

核心能力：
1. 去重入库（对照 UAtool 的 LEAD_DUPLICATE_FILTER 配置）
2. 高意向自动生成跟进任务（对照 follow_up_service / 自动拓客的 auto_craft_leads）
3. 统计看板数据（对照 dashboard / reports）
"""
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import FollowUpTask, Lead

logger = logging.getLogger("lead")


def _normalize(text: str) -> str:
    """归一化：去空白和标点，用于查重比较。"""
    return re.sub(r"[\s\u3000，。！？、,.!?;；:：'\"']", "", text or "")


def lead_exists(db: Session, content: str) -> bool:
    """查重：正文归一化后完全一致视为同一条线索（demo 规模直接全表比较）。"""
    key = _normalize(content)
    if not key:
        return True
    existing = db.query(Lead.content).all()
    return any(_normalize(c[0] or "") == key for c in existing)


def create_follow_up(db: Session, lead: Lead) -> FollowUpTask:
    """为一条线索生成跟进任务。

    对照 UAtool follow_up_service：跟进任务=线索的"下一步动作"，
    高意向线索自动建任务 + 定时提醒，避免销售遗漏。
    """
    task = FollowUpTask(
        lead_id=lead.id,
        task_type="wechat",
        title=f"跟进高意向线索：{lead.author_name or '匿名用户'}",
        content=f"线索来源：{lead.platform} / 关键词：{lead.keyword}\n"
                f"诉求：{lead.content[:100]}\n"
                f"建议话术：您好，看到您咨询{lead.keyword}，我们可以免费评估背景…",
        status="pending",
        scheduled_at=datetime.now() + timedelta(hours=1),  # 1小时后提醒

    )
    db.add(task)
    lead.status = "contacted"
    db.commit()
    db.refresh(task)
    return task


def ensure_follow_ups_for_high_intent(db: Session) -> int:
    """把近期 high 意向且尚未建立跟进任务的线索，自动生成跟进任务。

    对应 UAtool 自动拓客里的 auto_craft_leads（自动入库 + 自动建跟进）。
    """
    leads = db.query(Lead).filter(
        Lead.demand_level == "high",
        Lead.status == "new",
    ).all()
    created = 0
    for lead in leads:
        has_task = db.query(FollowUpTask).filter(FollowUpTask.lead_id == lead.id).first()
        if not has_task:
            create_follow_up(db, lead)
            created += 1
    if created:
        logger.info("自动生成跟进任务 %s 条", created)
    return created


def stats(db: Session) -> dict:
    """看板统计：线索总量、意向分布、平台分布、近7日趋势、待办跟进。"""
    total = db.query(func.count(Lead.id)).scalar() or 0
    high = db.query(func.count(Lead.id)).filter(Lead.demand_level == "high").scalar() or 0
    contacted = db.query(func.count(Lead.id)).filter(Lead.status == "contacted").scalar() or 0

    intent_dist = dict(db.query(Lead.demand_level, func.count(Lead.id))
                       .group_by(Lead.demand_level).all())
    platform_dist = dict(db.query(Lead.platform, func.count(Lead.id))
                         .group_by(Lead.platform).all())
    comment_dist = {"high": 0, "normal": 0, "low": 0}   # 由评论接口单独统计

    pending_tasks = db.query(func.count(FollowUpTask.id)).filter(
        FollowUpTask.status == "pending").scalar() or 0

    # 近7日新增线索趋势（日期 → 数量）
    since = datetime.now() - timedelta(days=6)
    rows = db.query(func.date(Lead.created_at).label("d"), func.count(Lead.id)) \
        .filter(Lead.created_at >= since).group_by("d").all()
    trend = {str(r[0]): r[1] for r in rows}

    return {
        "total": total,
        "high": high,
        "contacted": contacted,
        "pending_tasks": pending_tasks,
        "intent_dist": intent_dist,
        "platform_dist": platform_dist,
        "trend": trend,
    }
