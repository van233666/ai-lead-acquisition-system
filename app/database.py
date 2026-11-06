"""数据库连接与会话 —— 迷你版只有 SQLite。

对照 UAtool 的 backend/app/database.py：
- UAtool 支持通过 .env 的 DB_URL 切换 MySQL；这里固定 SQLite，原理一样：
  SQLAlchemy 引擎负责"连哪个库"，sessionmaker 负责"怎么开事务"。
- check_same_thread=False 是 SQLite 在 FastAPI 多线程下必须的选项（允许跨线程使用连接）。
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# SQLite 文件放在项目根目录，方便查看和删除重置
DB_PATH = "ua_mini.db"
DB_URL = f"sqlite:///./{DB_PATH}"

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},  # SQLite 专用：允许 FastAPI 多线程访问
    echo=False,                                 # 想看 SQL 就改成 True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入：每个请求一个会话，用完自动关闭。

    这是 FastAPI 里最标准的写法，UAtool 一模一样（见其 database.py 的 get_db）。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
