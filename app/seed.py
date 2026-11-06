"""种子数据 —— 内置挖掘技能 + 模拟平台语料。

两部分：
1. ensure_builtin_skills：首次启动写入内置技能（对照 UAtool 的
   lead_mining_service.ensure_builtin_skills）。
2. MOCK_CORPUS：模拟"公开平台帖子"语料。真实系统里这一步是
   Playwright 打开抖音/小红书搜索页抓回来的；这里用内置语料替代，
   让你专注理解"抓回来后怎么过滤、怎么判需求"这一层。

语料特意混入 5 类样本，正好演示完整的过滤流水线：
- 强需求（命中意向句式）→ high
- 弱需求（只含业务词）  → low
- 广告营销              → 直接丢弃
- 含隐私信息（手机号/微信）→ 直接丢弃（合规红线）
- 无关噪音              → 直接丢弃
"""
import logging

from sqlalchemy.orm import Session

from app.models import MiningSkill

logger = logging.getLogger("seed")

BUILTIN_SKILLS = [
    {
        "name": "留学意向客户挖掘",
        "skill_code": "edu-study-abroad-lead",
        "keywords": ["求推荐", "想申请", "准备申请", "预算", "需要", "求助",
                     "哪家好", "有没有", "怎么收费", "咨询", "帮忙看看", "来得及"],
        "platforms": ["douyin", "xiaohongshu"],
        "max_leads": 12,
    },
    {
        "name": "雅思培训意向挖掘",
        "skill_code": "edu-ielts-lead",
        "keywords": ["求推荐", "想报", "报名", "费用", "多少钱", "怎么学",
                     "求助", "考了几次", "老师", "机构"],
        "platforms": ["douyin", "zhihu"],
        "max_leads": 10,
    },
]

# 模拟语料：每个条目 = 一条公开帖子。
# 字段对齐真实抓取结果：platform / title(正文) / author / url / like_count / comment_count
MOCK_CORPUS = [
    # ---- 强需求（命中意向句式）----
    {"platform": "xiaohongshu", "author": "小鹿乱撞", "title": "大二均分88，求推荐靠谱的香港留学中介，预算10万以内",
     "url": "https://xhslink.com/demo/001", "like_count": 32, "comment_count": 12},
    {"platform": "douyin", "author": "李雷", "title": "香港留学求推荐，急，电话13800138000",
     "url": "https://v.douyin.com/demo/100", "like_count": 2, "comment_count": 1},
    {"platform": "douyin", "author": "我的昵称", "title": "双非大三，均分85，想申请香港的AI硕士，加我微信聊",
     "url": "https://v.douyin.com/demo/099", "like_count": 5, "comment_count": 3},
    {"platform": "xiaohongshu", "author": "阿哲", "title": "想申请25fall香港计算机硕士，有没有学长学姐帮忙看看背景",
     "url": "https://xhslink.com/demo/002", "like_count": 8, "comment_count": 5},
    {"platform": "douyin", "author": "Momo", "title": "准备申请港中文了，需要准备哪些材料？中介怎么收费？",
     "url": "https://v.douyin.com/demo/003", "like_count": 21, "comment_count": 40},
    {"platform": "douyin", "author": "Lucas", "title": "雅思6.5想冲港大，还来得及吗？求支招",
     "url": "https://v.douyin.com/demo/004", "like_count": 15, "comment_count": 9},
    {"platform": "xiaohongshu", "author": "奶绿", "title": "有预算想找香港留学机构做文书，哪家性价比高",
     "url": "https://xhslink.com/demo/005", "like_count": 44, "comment_count": 18},
    # ---- 弱需求（只含业务词，没有明确购买句式）----
    {"platform": "douyin", "author": "路人甲", "title": "香港留学是不是越来越卷了",
     "url": "https://v.douyin.com/demo/006", "like_count": 66, "comment_count": 3},
    {"platform": "xiaohongshu", "author": "飞鱼", "title": "聊聊香港留学的花费问题",
     "url": "https://xhslink.com/demo/007", "like_count": 12, "comment_count": 7},
    # ---- 广告营销（直接丢弃）----
    {"platform": "douyin", "author": "机构小助手", "title": "香港留学限时优惠，扫码免费领取选校方案，全网最低价",
     "url": "https://v.douyin.com/demo/008", "like_count": 0, "comment_count": 1},
    {"platform": "xiaohongshu", "author": "X教育", "title": "加微信免费送香港留学白皮书，私我领取",
     "url": "https://xhslink.com/demo/009", "like_count": 2, "comment_count": 0},
    # ---- 含隐私字段（合规红线，直接丢弃）----
    {"platform": "douyin", "author": "匿名用户", "title": "求推荐中介，我的微信是abc12345，加我详聊",
     "url": "https://v.douyin.com/demo/010", "like_count": 1, "comment_count": 0},
    {"platform": "xiaohongshu", "author": "小周", "title": "想申请香港硕士，电话13800138000 求联系",
     "url": "https://xhslink.com/demo/011", "like_count": 3, "comment_count": 0},
    # ---- 无关噪音（直接丢弃）----
    {"platform": "douyin", "author": "美食博主", "title": "今天打卡香港茶餐厅，菠萝油yyds",
     "url": "https://v.douyin.com/demo/012", "like_count": 200, "comment_count": 30},
    {"platform": "xiaohongshu", "author": "旅行家", "title": "香港三天两夜旅游攻略分享",
     "url": "https://xhslink.com/demo/013", "like_count": 500, "comment_count": 88},
]


def ensure_builtin_skills(db: Session) -> None:
    """首次启动写入内置技能（幂等：已有技能就跳过）。"""
    existing = db.query(MiningSkill).count()
    if existing > 0:
        return
    for item in BUILTIN_SKILLS:
        db.add(MiningSkill(**item))
    db.commit()
    logger.info("已写入 %s 个内置挖掘技能", len(BUILTIN_SKILLS))
