"""定时任务 —— 用标准库 asyncio 复刻 APScheduler 的调度思路。

UAtool 用的是 APScheduler（cron/interval 触发器，见 scheduler.py），
这里用 asyncio 后台任务演示同样的三件事：
1. 自动拓客巡检（每 N 分钟跑一次挖掘+评论批次）→ 对应 platform_comment_monitor_task
2. 每小时汇总统计（写一份内存快照供看板展示）→ 对应 update_channel_stats
3. 逾期任务标记（每小时）→ 对应 mark_overdue_tasks

学习重点：调度器的本质 = "一个循环 + 一个下次运行时间表"，
APScheduler 只是把这个循环做成了成熟的库（支持 cron 表达式、持久化等）。
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import FollowUpTask, MiningSkill

logger = logging.getLogger("scheduler")

# 内存态：给前端看"调度器还活着"。
scheduler_state = {
    "running": False,
    "last_craft_at": None,
    "last_craft_result": "",
    "next_craft_at": None,
    "last_stats_at": None,
}

CRAFT_INTERVAL_SECONDS = 30          # 自动拓客巡检间隔（demo 用2分钟）
AUTO_CRAFT_ENABLED = True             # 对照 UAtool 的 AUTO_CRAFT_LEAD 总开关


def _run_craft_once() -> dict:
    """执行一轮自动拓客：线索挖掘 + 评论批次 + 高意向自动建跟进。

    对照 UAtool platform_monitor_service.run_auto_craft 的骨架。
    """
    from app.services.intent import run_comment_batch
    from app.services.lead import ensure_follow_ups_for_high_intent
    from app.services.mining import run_mining

    db: Session = SessionLocal()
    try:
        # 1) 线索挖掘（用第一个内置技能 + 演示关键词）
        skill = db.query(MiningSkill).filter(MiningSkill.is_active == True).first()  # noqa: E712
        mining = {"skipped": True}
        if skill:
            mining = run_mining(db, skill, "香港留学")

        # 2) 评论批次：模拟采集 + AI 判定
        comments = run_comment_batch(db)

        # 3) 高意向线索自动生成跟进任务
        tasks = ensure_follow_ups_for_high_intent(db)

        return {"mining": mining, "comments": comments["total"],
                "comments_high": comments["high"], "follow_ups": tasks}
    finally:
        db.close()


def _mark_overdue() -> int:
    """把过了计划时间仍未完成的跟进任务标记为逾期。"""
    db = SessionLocal()
    try:
        now = datetime.now()
        n = db.query(FollowUpTask).filter(
            FollowUpTask.status == "pending",
            FollowUpTask.scheduled_at < now,
        ).update({FollowUpTask.status: "overdue"}, synchronize_session=False)
        db.commit()
        if n:
            logger.info("标记逾期跟进任务 %s 条", n)
        return n
    finally:
        db.close()


async def _scheduler_loop() -> None:
    """调度主循环：每秒检查一次时间表，到点执行对应任务。"""
    next_craft = datetime.now() + timedelta(seconds=CRAFT_INTERVAL_SECONDS)
    scheduler_state["next_craft_at"] = next_craft

    while scheduler_state["running"]:
        now = datetime.now()

        # 任务1：自动拓客巡检（间隔触发）
        if now >= next_craft:
            try:
                result = _run_craft_once()
                scheduler_state["last_craft_result"] = str(result)[:200]
                logger.info("自动拓客巡检完成: %s", result)
            except Exception as e:                      # 巡检失败不拖垮调度器
                scheduler_state["last_craft_result"] = f"error: {e}"
                logger.error("自动拓客巡检失败: %s", e)
            scheduler_state["last_craft_at"] = now
            next_craft = now + timedelta(seconds=CRAFT_INTERVAL_SECONDS)
            scheduler_state["next_craft_at"] = next_craft

        # 任务2：每小时汇总统计（内存快照，不落库）
        if scheduler_state["last_stats_at"] is None or \
                (now - scheduler_state["last_stats_at"]).total_seconds() >= 3600:
            scheduler_state["last_stats_at"] = now

        # 任务3：逾期跟进标记（每小时）
        _mark_overdue()

        await asyncio.sleep(1)


async def start_scheduler() -> None:
    """启动调度循环（由 FastAPI startup 事件调用）。"""
    if scheduler_state["running"]:
        return
    scheduler_state["running"] = True
    asyncio.get_running_loop().create_task(_scheduler_loop())
    logger.info("定时调度器已启动（自动拓客间隔 %ss）", CRAFT_INTERVAL_SECONDS)


def stop_scheduler() -> None:
    scheduler_state["running"] = False
    logger.info("定时调度器已停止")
