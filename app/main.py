"""FastAPI 入口 —— 复刻 UAtool main.py 的骨架。

对照 UAtool：
- 启动流程：建表 + seed + 启动调度 + 注册路由 + 托管静态页
- 本 demo 把 API 集中在入口文件，方便你一次看完"一个请求怎么走"
  （真实工程会拆到 app/api/*.py，每个模块一个 router，见 UAtool backend/app/api/）。
"""
import asyncio
import logging
import os
import csv
import io

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.models import Comment, FollowUpTask, Lead, LeadTag, MiningSkill
from app.seed import ensure_builtin_skills
from app.services import intent, lead as lead_service, mining
from app.services.scheduler import (scheduler_state, start_scheduler,
                                    stop_scheduler)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("ua-mini")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="ua-mini · 迷你AI获客系统", version="0.1.0",
              description="学习用迷你版：挖掘 → 判定 → 入库 → 跟进 全链路")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # demo 放开，生产需收敛
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 启动 / 关闭 ====================

@app.on_event("startup")
async def on_startup():
    Base.metadata.create_all(bind=engine)   # 建表（UAtool 用 init_database + 迁移）
    db = SessionLocal()
    try:
        ensure_builtin_skills(db)
    finally:
        db.close()
    await start_scheduler()                 # 启动后台调度
    logger.info("ua-mini 启动完成")


@app.on_event("shutdown")
async def on_shutdown():
    stop_scheduler()


@app.get("/health")
def health():
    return {"code": 0, "message": "ok", "data": {"status": "healthy"}}


# ==================== 线索挖掘 ====================

@app.post("/api/mining/run")
def api_run_mining(keyword: str, skill_id: int | None = None,
                   db: Session = Depends(get_db)):
    """运行一次线索挖掘。前端按钮触发，对应 UAtool 的挖掘技能执行接口。"""
    skill = None
    if skill_id:
        skill = db.query(MiningSkill).filter(MiningSkill.id == skill_id).first()
    if skill is None:
        skill = db.query(MiningSkill).filter(MiningSkill.is_active == True).first()  # noqa: E712
    if skill is None:
        raise HTTPException(400, "没有可用的挖掘技能，请先初始化种子数据")
    result = mining.run_mining(db, skill, keyword)
    # 挖掘完成后：高意向自动生成跟进任务
    if result["success"]:
        result["follow_ups"] = lead_service.ensure_follow_ups_for_high_intent(db)
    return {"code": 0, "data": result}


@app.get("/api/mining/skills")
def api_list_skills(db: Session = Depends(get_db)):
    skills = db.query(MiningSkill).all()
    return {"code": 0, "data": [
        {"id": s.id, "name": s.name, "skill_code": s.skill_code,
         "keywords": s.keywords, "platforms": s.platforms,
         "max_leads": s.max_leads, "run_count": s.run_count,
         "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
        for s in skills
    ]}


# ==================== 线索管理 ====================

@app.get("/api/leads")
def api_list_leads(limit: int = 50, level: str | None = None,
                   db: Session = Depends(get_db)):
    q = db.query(Lead).order_by(Lead.created_at.desc())
    if level:                                  # 传 ?level=high 就只返回高意向
        q = q.filter(Lead.demand_level == level)
    leads = q.limit(limit).all()

    return {"code": 0, "data": [
        {"id": l.id, "keyword": l.keyword, "platform": l.platform,
         "content": l.content, "author_name": l.author_name,
         "demand_level": l.demand_level, "matched_cue": l.matched_cue,
         "status": l.status,
         "tags": [t.name for t in
                  db.query(LeadTag).filter(LeadTag.lead_id == l.id).all()],
         "created_at": l.created_at.isoformat() if l.created_at else None}
        for l in leads
    ]}


@app.get("/api/leads/top")
def api_top_leads(limit: int = 3, db: Session = Depends(get_db)):
    """练习：返回最近的高意向线索（这是我自己加的接口）"""
    rows = (db.query(Lead)
            .filter(Lead.demand_level == "high")
            .order_by(Lead.created_at.desc())
            .limit(limit).all())
    return {"code": 0, "data": [
        {"id": r.id, "content": r.content, "author": r.author_name}
        for r in rows
    ]}

@app.post("/api/leads/{lead_id}/tags")
def api_add_lead_tag(lead_id: int, name: str, db: Session = Depends(get_db)):
    """给线索打一个标签：路径带线索 id，标签名走查询参数 ?name=xxx"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "线索不存在")
    tag = LeadTag(lead_id=lead_id, name=name)
    db.add(tag)
    db.commit()
    return {"code": 0, "data": {"id": tag.id, "lead_id": lead_id, "name": tag.name}}

@app.delete("/api/leads/{lead_id}/tags")
def api_del_lead_tag(lead_id: int, name: str, db: Session = Depends(get_db)):
    """删除某条线索身上的一个标签"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "线索不存在")

    tag = (db.query(LeadTag)
             .filter(LeadTag.lead_id == lead_id, LeadTag.name == name)
             .first())
    if not tag:
        raise HTTPException(404, "标签不存在")

    db.delete(tag)
    db.commit()
    return {"code": 0, "message": "deleted"}

@app.get("/api/tags")
def api_tag_stats(db: Session = Depends(get_db)):
    """统计每个标签被几条线索用过"""
    rows = (db.query(LeadTag.name, func.count(LeadTag.id))
              .group_by(LeadTag.name)
              .order_by(func.count(LeadTag.id).desc())
              .all())
    return {"code": 0, "data": [{"name": n, "count": c} for n, c in rows]}

@app.get("/api/leads/export")
def api_export_leads(db: Session = Depends(get_db)):
    """导出线索为 CSV（Excel 可直接打开，中文不乱码）"""
    rows = db.query(Lead).order_by(Lead.created_at.desc()).limit(2000).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "平台", "正文", "需求等级", "命中句式", "状态", "标签", "抓取时间"])
    for l in rows:
        tags = ",".join(t.name for t in
                        db.query(LeadTag).filter(LeadTag.lead_id == l.id).all())
        w.writerow([l.id, l.platform, l.content, l.demand_level,
                    l.matched_cue or "", l.status, tags,
                    l.created_at.strftime("%Y-%m-%d %H:%M")])
    data = "\ufeff" + buf.getvalue()
    return Response(content=data.encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="leads.csv"'})


@app.patch("/api/leads/{lead_id}/status")
def api_update_lead_status(lead_id: int, status: str, db: Session = Depends(get_db)):
    """更新线索状态：contacted / converted / invalid。"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "线索不存在")
    lead.status = status
    db.commit()
    return {"code": 0, "message": "ok"}


@app.post("/api/leads/{lead_id}/followups")
def api_create_followup(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "线索不存在")
    task = lead_service.create_follow_up(db, lead)
    return {"code": 0, "data": {"id": task.id, "title": task.title,
                                "scheduled_at": task.scheduled_at.isoformat()}}


# ==================== 评论监控（模拟批次） ====================

@app.post("/api/comments/analyze")
def api_analyze_comments(db: Session = Depends(get_db)):
    """跑一批模拟评论：采集 + AI 意向判定。对应 UAtool 的评论监控定时任务。"""
    result = intent.run_comment_batch(db)
    return {"code": 0, "data": result}


@app.get("/api/comments")
def api_list_comments(limit: int = 30, db: Session = Depends(get_db)):
    comments = db.query(Comment).order_by(Comment.created_at.desc()).limit(limit).all()
    return {"code": 0, "data": [
        {"id": c.id, "platform": c.platform, "nickname": c.nickname,
         "content": c.content, "intent_level": c.intent_level,
         "intent_score": c.intent_score, "matched_keywords": c.matched_keywords,
         "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in comments
    ]}


# ==================== 跟进任务 ====================

@app.get("/api/followups")
def api_list_followups(limit: int = 30, db: Session = Depends(get_db)):
    tasks = db.query(FollowUpTask).order_by(FollowUpTask.created_at.desc()).limit(limit).all()
    return {"code": 0, "data": [
        {"id": t.id, "lead_id": t.lead_id, "title": t.title, "content": t.content,
         "status": t.status,
         "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None}
        for t in tasks
    ]}


@app.post("/api/followups/{task_id}/done")
def api_done_followup(task_id: int, db: Session = Depends(get_db)):
    task = db.query(FollowUpTask).filter(FollowUpTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    task.status = "done"
    db.commit()
    return {"code": 0, "message": "ok"}


# ==================== 看板统计 ====================

@app.get("/api/stats")
def api_stats(db: Session = Depends(get_db)):
    data = lead_service.stats(db)
    # 评论意向分布
    dist = dict(db.query(Comment.intent_level, func.count(Comment.id))
                .group_by(Comment.intent_level).all())
    data["comment_intent_dist"] = dist
    data["scheduler"] = {
        "running": scheduler_state["running"],
        "last_craft_at": scheduler_state["last_craft_at"].isoformat()
        if scheduler_state["last_craft_at"] else None,
        "next_craft_at": scheduler_state["next_craft_at"].isoformat()
        if scheduler_state["next_craft_at"] else None,
        "last_result": scheduler_state["last_craft_result"],
    }
    return {"code": 0, "data": data}


# ==================== 静态前端 ====================

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# 托管 static 目录下的静态资源（可选，前端已全部内联，这里留作扩展）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)
