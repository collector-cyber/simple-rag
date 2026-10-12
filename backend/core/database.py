"""
SQLite 数据库访问模块

RAG 数据量小、单机部署，选用 SQLite + numpy 内存检索，零外部依赖。
documents 表记录原始文件，chunks 表记录切分文本与向量（JSON 字符串）。
"""
import sqlite3
from contextlib import contextmanager

from config import settings


def _connect() -> sqlite3.Connection:
    """建立连接；写操作可能来自线程池，故关闭同线程检查并由上层串行控制"""
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 启用外键级联删除（chunks 随 documents 删除）
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    """连接上下文：正常结束提交，异常回滚"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化表结构（幂等）"""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_type TEXT,
                file_size INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'processing',
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
            """
        )


def execute(sql: str, params: tuple = ()) -> int:
    """执行写操作，返回 lastrowid 或受影响行数（供上层按需使用）"""
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount


def execute_many(sql: str, seq_params) -> None:
    """批量写操作（如 chunk 入库）"""
    with get_conn() as conn:
        conn.executemany(sql, seq_params)


def fetch_all(sql: str, params: tuple = ()) -> list:
    """查询多行，返回 dict 列表"""
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def fetch_one(sql: str, params: tuple = ()):
    """查询单行，返回 dict 或 None"""
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
