"""一次性清理：删掉历史重复线索，每种内容只留一条。

规则：
1. 按"归一化正文"分组（合并多余空格），同内容算同一条；
2. 每组保留一条：有人工标签的线索优先保留，否则保留最早入库的那条；
3. 删重复线索时，连带删掉它名下的跟进任务，避免孤儿数据。

先备份再跑：copy ua_mini.db ua_mini.db.bak
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal
from app.models import FollowUpTask, Lead, LeadTag


def main():
    db = SessionLocal()
    try:
        all_leads = db.query(Lead).order_by(Lead.id).all()

        groups = {}
        for l in all_leads:
            key = " ".join(l.content.split())
            groups.setdefault(key, []).append(l)

        protected = {t.lead_id for t in db.query(LeadTag).all()}

        removed = 0
        for key, items in groups.items():
            keep = next((x for x in items if x.id in protected), items[0])
            for l in items:
                if l.id == keep.id:
                    continue
                for f in db.query(FollowUpTask).filter(FollowUpTask.lead_id == l.id).all():
                    db.delete(f)
                db.delete(l)
                removed += 1
        db.commit()

        remain = db.query(Lead).count()
        print(f"清理前 {len(all_leads)} 条 -> 保留 {remain} 条，删除重复 {removed} 条")
        print("保留的线索 id：", [l.id for l in db.query(Lead).order_by(Lead.id).all()])
    finally:
        db.close()


if __name__ == "__main__":
    main()
