"""
知识库文档服务：解析、切分、向量化与入库

上传的原始文件落盘到 data/uploads，切分后的文本块与向量存入 SQLite。
"""
import json
import os
import uuid
from pathlib import Path
from typing import List

from config import settings
from core import database as db
from core.llm import embed_texts
from utils.logger import log

# 支持解析的文件类型
ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def extract_text(file_path: Path) -> str:
    """按扩展名提取纯文本，不支持的类型抛出 ValueError"""
    suffix = file_path.suffix.lower()
    if suffix in (".txt", ".md", ".markdown"):
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        import docx

        document = docx.Document(str(file_path))
        parts = [p.text for p in document.paragraphs]
        # 表格内容也一并提取，避免漏掉结构化信息
        for table in document.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    raise ValueError(f"不支持的文件类型: {suffix}")


def chunk_text(text: str) -> List[str]:
    """
    简单滑窗切分：按段落聚合至 chunk_size，超长段落按窗口硬切，
    相邻块保留 chunk_overlap 重叠，避免语义在边界处被截断。
    """
    text = text.strip()
    if not text:
        return []

    size = settings.rag_chunk_size
    overlap = settings.rag_chunk_overlap

    # 先按段落合并成不超过 size 的单元
    units: List[str] = []
    buffer = ""
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        # 超长段落直接滑窗硬切
        while len(para) > size:
            if buffer:
                units.append(buffer)
                buffer = ""
            units.append(para[:size])
            para = para[size - overlap:]
        if len(buffer) + len(para) + 1 > size:
            units.append(buffer)
            buffer = para
        else:
            buffer = f"{buffer}\n{para}" if buffer else para
    if buffer:
        units.append(buffer)
    return units


def ingest_file(filename: str, content: bytes) -> dict:
    """
    单文件入库：落盘 → 解析 → 切分 → 向量化 → 写库

    失败不抛出，返回 status=failed 的结果，供批量上传逐文件汇报。
    """
    doc_id = uuid.uuid4().hex
    suffix = Path(filename).suffix.lower()
    result = {
        "doc_id": doc_id,
        "filename": filename,
        "status": "failed",
        "chunk_count": 0,
        "error": None,
    }

    if suffix not in ALLOWED_EXTENSIONS:
        result["error"] = f"不支持的文件类型: {suffix or '(无扩展名)'}"
        return result

    db.execute(
        "INSERT INTO documents (id, filename, file_type, file_size, status) VALUES (?, ?, ?, ?, 'processing')",
        (doc_id, filename, suffix, len(content)),
    )
    stored_path = Path(settings.upload_dir) / f"{doc_id}{suffix}"
    try:
        # 原始文件落盘后从磁盘解析，保证解析失败时仍保留原文件供排查
        stored_path.write_bytes(content)
        text = extract_text(stored_path)
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("未能从文件中提取到有效文本")

        vectors = embed_texts(chunks)
        rows = [
            (doc_id, i, c, json.dumps(v.tolist()))
            for i, (c, v) in enumerate(zip(chunks, vectors))
        ]
        db.execute_many(
            "INSERT INTO chunks (doc_id, chunk_index, content, embedding) VALUES (?, ?, ?, ?)",
            rows,
        )
        db.execute(
            "UPDATE documents SET chunk_count = ?, status = 'ready' WHERE id = ?",
            (len(chunks), doc_id),
        )
        result.update(status="ready", chunk_count=len(chunks), error=None)
        log.info(f"文档入库成功: {filename} doc_id={doc_id} chunks={len(chunks)}")
    except Exception as e:
        log.exception(f"文档入库失败: {filename} doc_id={doc_id} 错误: {e}")
        db.execute(
            "UPDATE documents SET status = 'failed', error_message = ? WHERE id = ?",
            (str(e)[:500], doc_id),
        )
        result["error"] = str(e)
    return result


def list_documents(keyword: str = "", page: int = 1, page_size: int = 20) -> dict:
    """分页查询文档列表，支持文件名模糊搜索"""
    where, params = "", []
    if keyword:
        where = "WHERE filename LIKE ?"
        params.append(f"%{keyword}%")
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM documents {where}", tuple(params))["c"]
    rows = db.fetch_all(
        f"SELECT id, filename, file_type, file_size, chunk_count, status, error_message, created_at "
        f"FROM documents {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (page_size, (page - 1) * page_size),
    )
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


def get_document(doc_id: str) -> dict | None:
    """按 ID 查询单个文档"""
    return db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))


def delete_document(doc_id: str) -> None:
    """删除文档（chunks 级联删除）并清理原始文件"""
    doc = get_document(doc_id)
    if not doc:
        return
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    # 清理落盘的原始文件
    for path in Path(settings.upload_dir).glob(f"{doc_id}*"):
        try:
            os.remove(path)
        except OSError:
            pass
    log.info(f"文档已删除: doc_id={doc_id} filename={doc['filename']}")


def get_stats() -> dict:
    """知识库整体统计"""
    docs = db.fetch_one("SELECT COUNT(*) AS c FROM documents WHERE status = 'ready'")["c"]
    chunks = db.fetch_one("SELECT COUNT(*) AS c FROM chunks")["c"]
    return {"document_count": docs, "chunk_count": chunks}

