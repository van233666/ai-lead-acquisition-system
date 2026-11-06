# ua-mini · 轻量 AI 获客系统

> A minimal AI lead-acquisition service: **mining → multi-stage filtering → intent scoring (rule layer + LLM fallback) → CRM-lite follow-up**.
> FastAPI + SQLAlchemy + SQLite，5 张表、16 个接口、1 个单页看板，全部中文注释。

## 一、它解决什么问题

销售每天要在抖音、小红书上人工刷帖子、判断"这个人是不是想咨询"、再一个个私信。
这件事**重复、耗时、容易漏**。ua-mini 把这条链路自动化：

```
公开帖子  →  挖掘  →  四道过滤  →  意向打分  →  入库  →  自动建跟进任务  →  看板
```

跑起来之后，销售看到的已经不是"一堆帖子"，而是"按意向排好序、可直接跟进的客户名单"。

## 二、功能清单

| 能力 | 说明 |
| --- | --- |
| 线索挖掘 | 按技能（关键词组）检索公开帖子，判意向句式、生成线索 |
| 四道过滤 | 隐私（手机号/微信/QQ）→ 广告引流词 → 过短噪音 → 归一化去重，**全部发生在入库前** |
| 过滤可审计 | 每轮返回"抓 N 条 / 合格 N 条 / 广告拦截 N / 隐私拦截 N"，不是黑盒 |
| 双层意向判定 | 规则层打分（零成本、可解释）+ LLM 层（质量高但有延迟），可熔断降级 |
| 熔断降级 | 大模型故障时自动切规则兜底，判定与入库不受影响 |
| 标签系统 | 线索可打多个标签（关联表），支持增/删/查 + `GROUP BY` 统计 |
| CSV 导出 | `Content-Disposition` 浏览器下载 + BOM 兼容 Excel 中文 |
| 定时巡检 | asyncio 长驻调度，按间隔自动"挖掘 + 评论判定 + 建跟进"，无人值守 |
| 单页看板 | 线索池、意向分布、评论、跟进任务、调度状态一屏看完 |

## 三、架构

```
                    ┌──────────────────────────────┐
   定时触发 / 手动点 ─▶│  scheduler.py  asyncio 长驻调度 │
                    └──────────────┬───────────────┘
                                   ▼
  seed.py (MOCK_CORPUS) ──▶ mining.py  ── 四道过滤 ──▶ Lead 入库
                                   │
                                   ├──▶ intent.py  规则打分(0-100) ──▶ Comment
                                   │        └── LLM 生成回复（故障→规则兜底）
                                   ▼
                            lead.py  高意向自动建 FollowUpTask / 逾期标记
                                   ▼
                     main.py  FastAPI 路由 + static/index.html 看板
```

## 四、几个设计决策（面试最常问）

1. **过滤为什么放在入库前？**
   脏数据不进库，后续查询、统计、导出全都是干净的；成本也最低——不用先存再删。

2. **为什么标签要单独一张表？**
   一条线索可以有多个标签，而一列只能装一个值。硬塞成 `"港三冲刺,预算敏感"` 之后：查询只能模糊匹配（会误伤）、无法 `GROUP BY` 统计、删一个标签要重写整串。拆成关联表后，**一行一个标签**，精确匹配、可聚合、可单删。

3. **为什么意向判定先走规则，再走大模型？**
   规则层零成本、毫秒级、可解释、永远可用；LLM 层质量更高但贵、慢、会挂。所以规则是骨架（保证系统不瘫），LLM 是增强。实测把 `LLM_FAULTY` 置 True，回复全部降级为"（规则兜底）"，**判定与入库完全不受影响**。

4. **去重为什么用"归一化正文"而不是原文？**
   同一帖子常有不同排版（多余空格、表情、标点）。先去掉空白与符号再比较，才能把"看起来不一样、其实是同一条"的副本收敛掉。

5. **CSV 为什么要加 BOM？**
   不加 `\ufeff`，Excel 打开 UTF-8 CSV 会把中文显示成乱码——这是"交付给非技术同事"的真实细节。

## 五、数据模型（5 张表）

| 表 | 作用 | 关键字段 |
| --- | --- | --- |
| `mining_skill` | 挖掘技能（关键词组） | name、keywords、is_active |
| `lead` | 线索池 | platform、content、intent_level、intent_score、status |
| `comment` | 评论 + 意向判定结果 | content、intent_level、intent_score、matched_keywords |
| `follow_up_task` | 跟进任务 | lead_id、scheduled_at、status(pending/overdue/done) |
| `lead_tag` | 标签（关联表） | lead_id、name |

## 六、API 一览（16 个，`/docs` 可直接调）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/api/mining/run` | 跑一次挖掘（返回抓取/合格/拦截数量） |
| GET | `/api/mining/skills` | 技能列表 |
| GET | `/api/leads?limit=&level=` | 线索列表，支持按意向等级过滤 |
| GET | `/api/leads/top` | 最近的高意向线索 |
| POST | `/api/leads/{id}/tags` | 给线索打标签 |
| DELETE | `/api/leads/{id}/tags` | 删除标签（不存在返回 404） |
| GET | `/api/tags` | 标签使用统计（GROUP BY） |
| GET | `/api/leads/export` | 导出 CSV（BOM 兼容 Excel） |
| POST | `/api/leads/{id}/followups` | 手动建跟进任务 |
| POST | `/api/comments/analyze` | 跑一批评论 + 意向判定 |
| GET | `/api/comments` | 评论列表 |
| GET | `/api/followups` | 跟进任务列表 |
| POST | `/api/followups/{id}/done` | 标记任务完成 |
| GET | `/api/stats` | 看板汇总（总量/意向分布/平台分布/趋势/调度状态） |
| GET | `/` | 单页看板 |

## 七、快速开始

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m uvicorn app.main:app --port 8765
```

打开 <http://127.0.0.1:8765> ，接口文档 <http://127.0.0.1:8765/docs> 。

> Windows 用户也可以直接双击 `启动ua-mini.bat`（自动起服务并打开页面）。
> 首次启动会自动建表、灌入演示语料；数据库文件 `ua_mini.db` 不入库（见 `.gitignore`）。

## 八、实测数据

- 一轮挖掘：抓 7 条 → 合格 4 条（强需求 2 条；**广告拦截 1、隐私拦截 2**），含手机号帖子 100% 不落库。
- 去重前后：同一语料连续跑两次，线索数稳定在 503（不再翻倍）。
- 数据治理：503 条历史重复收敛为 **5 条有效线索**，人工标签全部保留，孤儿跟进任务连带清理。
- 熔断实验：`LLM_FAULTY = True` 时回复降级为规则兜底，判定/入库正常；复位后恢复话术分支。

## 九、已知限制 / Roadmap

- 挖掘目前用 `seed.py` 的模拟语料，**未接真实抓取**（真实抓取涉及平台风控与合规，见下条）。
- 未做登录鉴权与多用户；`allow_origins=["*"]` 仅为本地演示。
- 线索列表逐行查标签，属 N+1 查询，数据量大时应改为 join / 预加载。
- 缺测试：过滤规则（隐私/广告/去重）应补 pytest 用例。
- 合规边界：只处理公开内容；**含手机号、微信号的帖子一律丢弃**，不做私信自动化。

## 十、目录结构

```
ua-mini/
├── app/
│   ├── main.py          FastAPI 入口 + 全部路由
│   ├── database.py      SQLite 引擎与会话
│   ├── models.py        5 张表
│   ├── seed.py          内置技能 + 模拟语料
│   ├── services/
│   │   ├── mining.py    挖掘流水线 + 四道过滤
│   │   ├── intent.py    意向判定（规则层 + mock LLM）
│   │   ├── lead.py      去重 / 跟进 / 统计
│   │   └── scheduler.py asyncio 定时巡检
│   └── static/
│       └── index.html   单页看板
├── clean_duplicates.py  历史重复数据清理（先备份、保护人工标签）
├── requirements.txt
└── 启动ua-mini.bat      Windows 一键启动
```

## License

MIT
