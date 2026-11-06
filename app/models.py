"""数据模型 —— 用最少的 4 张表，复刻 UAtool 的核心业务闭环。

对照表（UAtool 完整版 → ua-mini）：
- mining_skill      → MiningSkill   线索挖掘技能（关键词 + 意向句式 + 目标平台）
- mining_lead       → Lead          挖掘到的公开意向线索
- platform_comment  → Comment       平台评论（采集 + AI 意向判定）
- follow_up_task    → FollowUpTask  跟进任务（高意向自动建任务）

UAtool 还多出 visitor / conversation_record / sop_template / knowledge_base /
auto_reach_rule / platform_account / client_tag 等表，这里全部砍掉，
只保留"挖掘→判定→入库→跟进"这条主干，学完再加。
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Index,
                        Integer, String, Text)

from app.database import Base


class MiningSkill(Base):
    """线索挖掘技能。

    类比 UAtool 的 mining_skill 表 + 内置技能种子数据：
    一次挖掘 = "选一个技能 + 一个业务关键词"，技能里存的是
    意向句式（cue）和允许挖掘的平台。
    """
    __tablename__ = "mining_skill"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, comment="技能名称")
    skill_code = Column(String(64), unique=True, nullable=False, comment="技能代码")
    keywords = Column(JSON, nullable=False, comment="意向句式关键词列表，如 ['求推荐','想申请']")
    platforms = Column(JSON, nullable=False, comment="平台列表，如 ['douyin','xiaohongshu']")
    max_leads = Column(Integer, default=12, comment="单轮最多入库线索条数")
    is_active = Column(Boolean, default=True, nullable=False)
    run_count = Column(Integer, default=0, comment="累计执行次数")
    last_run_at = Column(DateTime, comment="最后执行时间")


class Lead(Base):
    """挖掘到的公开意向线索。

    对照 UAtool 的 mining_lead 表：只保存公开信息（来源、诉求片段、公开链接），
    禁止保存手机号/微信/QQ 等隐私字段 —— 这是系统内置的合规红线。
    """
    __tablename__ = "lead"

    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("mining_skill.id"), index=True, comment="所属技能")
    keyword = Column(String(255), nullable=False, index=True, comment="业务关键词")
    platform = Column(String(64), nullable=False, index=True, comment="来源平台")
    content = Column(Text, nullable=False, comment="用户公开诉求片段")
    content_url = Column(String(500), comment="公开帖子链接")
    author_name = Column(String(128), comment="作者昵称（仅展示）")
    demand_level = Column(String(20), default="low", index=True,
                          comment="需求判断 high=强需求 / low=弱需求")
    matched_cue = Column(String(255), comment="命中的意向句式")
    status = Column(String(20), default="new", index=True,
                    comment="new=待处理 / contacted=已触达 / converted=已转化 / invalid=无效")
    created_at = Column(DateTime, default=datetime.now, index=True)


class Comment(Base):
    """平台评论 —— 评论监控 + AI 意向判定的载体。

    对照 UAtool 的 platform_comment 表：采集到评论后，先判意向（high/normal/low），
    高意向进入线索池。ua-mini 用模拟评论源演示，真实版由 Playwright 抓取。
    """
    __tablename__ = "comment"

    id = Column(Integer, primary_key=True)
    platform = Column(String(32), nullable=False, index=True, comment="平台")
    nickname = Column(String(128), comment="评论者昵称")
    content = Column(Text, nullable=False, comment="评论内容")
    intent_level = Column(String(20), index=True, comment="AI 判定意向 high/normal/low")
    intent_score = Column(Integer, comment="意向评分 0-100")
    matched_keywords = Column(String(500), comment="命中关键词")
    is_processed = Column(Boolean, default=False, index=True, comment="是否已处理")
    created_at = Column(DateTime, default=datetime.now, index=True)


class FollowUpTask(Base):
    """跟进任务 —— 让每条线索都有"下一步动作"。

    对照 UAtool 的 follow_up_task 表：高意向线索自动生成跟进任务，
    定时提醒（demo 里用"预计完成时间"字段演示），销售照单执行。
    """
    __tablename__ = "follow_up_task"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), index=True, comment="关联线索")
    task_type = Column(String(20), default="wechat", comment="跟进方式 wechat/call/visit")
    title = Column(String(128), nullable=False, comment="任务标题")
    content = Column(Text, comment="任务详情（含 AI 生成的话术建议）")
    status = Column(String(20), default="pending", index=True,
                    comment="pending=待办 / done=已完成 / overdue=已逾期")
    scheduled_at = Column(DateTime, index=True, comment="计划跟进时间")
    created_at = Column(DateTime, default=datetime.now)


class LeadTag(Base):
    """线索标签 —— 销售自己给的分类（如"港三冲刺""预算敏感"）。

    对照 UAtool 的 client_tag 表：标签是人的判断，和系统的自动判定
    （Lead.demand_level）并存，一个偏客观、一个偏主观。
    """
    __tablename__ = "lead_tag"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), index=True, comment="关联线索")
    name = Column(String(64), nullable=False, index=True, comment="标签名")
    created_at = Column(DateTime, default=datetime.now)
