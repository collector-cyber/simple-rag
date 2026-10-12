"""
RAG 问答服务：向量召回 + 上下文构建 + LLM 生成

检索采用全量向量内存缓存 + numpy 余弦相似度：
以 chunks 表行数作为缓存版本，数据变化后自动重建，简单可靠。
"""
import json
from typing import Generator

import numpy as np

from config import settings
from core import database as db
from core.llm import chat_completion, chat_stream, embed_texts
from utils.logger import log

# 向量检索缓存：count 变化即失效重建
_cache = {"count": -1, "ids": None, "doc_ids": None, "contents": None, "matrix": None}


def _ensure_cache() -> None:
    """保证内存向量矩阵与 chunks 表一致（按行数判变更）"""
    count = db.fetch_one("SELECT COUNT(*) AS c FROM chunks")["c"]
    if _cache["count"] == count and _cache["matrix"] is not None:
        return

    rows = db.fetch_all("SELECT id, doc_id, content, embedding FROM chunks")
    if not rows:
        _cache.update(count=0, ids=[], doc_ids=[], contents=[], matrix=np.zeros((0, 0), dtype=np.float32))
        return

    matrix = np.array([json.loads(r["embedding"]) for r in rows], dtype=np.float32)
    # 入库向量归一化，检索时点积即余弦相似度
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.maximum(norms, 1e-8)
    _cache.update(
        count=count,
        ids=[r["id"] for r in rows],
        doc_ids=[r["doc_id"] for r in rows],
        contents=[r["content"] for r in rows],
        matrix=matrix,
    )
    log.info(f"向量缓存已重建: {count} 个 chunk")


def retrieve(query: str, top_k: int) -> list:
    """
    向量召回：问题向量化后与全量 chunk 求余弦相似度，返回 Top K

    Returns:
        [{"chunk_id", "doc_id", "content", "score"}]，按分数降序
    """
    _ensure_cache()
    matrix = _cache["matrix"]
    if matrix.size == 0:
        return []

    q_vec = embed_texts([query])[0]
    q_vec = q_vec / max(float(np.linalg.norm(q_vec)), 1e-8)
    scores = matrix @ q_vec
    k = min(top_k, len(scores))
    top_idx = np.argpartition(-scores, k - 1)[:k]
    top_idx = top_idx[np.argsort(-scores[top_idx])]
    return [
        {
            "chunk_id": _cache["ids"][i],
            "doc_id": _cache["doc_ids"][i],
            "content": _cache["contents"][i],
            "score": float(scores[i]),
        }
        for i in top_idx
    ]


def _lookup_filenames(doc_ids: list) -> dict:
    """批量查询 chunk 对应源文件名，用于前端展示引用来源"""
    if not doc_ids:
        return {}
    marks = ",".join("?" for _ in doc_ids)
    rows = db.fetch_all(f"SELECT id, filename FROM documents WHERE id IN ({marks})", tuple(doc_ids))
    return {r["id"]: r["filename"] for r in rows}


def _build_messages(question: str, hits: list) -> list:
    """把召回结果拼装为 OpenAI 消息列表（带总长度截断）"""
    context_parts = []
    total = 0
    for i, hit in enumerate(hits, 1):
        block = f"[资料{i}] {hit['content']}"
        if total + len(block) > settings.rag_context_max_chars:
            break
        context_parts.append(block)
        total += len(block)
    context = "\n\n".join(context_parts) if context_parts else "（无参考资料）"

    return [
        {"role": "system", "content": settings.rag_system_prompt.format(context=context)},
        {"role": "user", "content": question},
    ]


def _reference_payload(hits: list) -> list:
    """构造返回给前端的引用列表（附源文件名）"""
    filenames = _lookup_filenames([h["doc_id"] for h in hits])
    return [
        {**h, "filename": filenames.get(h["doc_id"], "未知文档")}
        for h in hits
    ]


def answer(question: str, top_k: int = None) -> dict:
    """
    非流式 RAG 问答：召回 → 生成 → 一次性返回答案与引用
    """
    top_k = top_k or settings.rag_top_k
    hits = retrieve(question, top_k)
    messages = _build_messages(question, hits)
    content = chat_completion(messages)
    return {"answer": content, "references": _reference_payload(hits)}


def stream_events(question: str, top_k: int = None) -> Generator[dict, None, None]:
    """
    流式 RAG 问答，yield 事件字典（供 SSE 路由消费）：
    - {"type": "references", ...}   召回完成，先推引用
    - {"type": "delta", "text"}     答案增量
    - {"type": "done"}              正常结束
    - {"type": "error", "message"}  生成失败
    """
    top_k = top_k or settings.rag_top_k
    try:
        yield {"type": "status", "stage": "retrieving"}
        hits = retrieve(question, top_k)
        yield {"type": "references", "references": _reference_payload(hits)}

        messages = _build_messages(question, hits)
        for delta in chat_stream(messages):
            yield {"type": "delta", "text": delta}
        yield {"type": "done"}
    except Exception as e:
        log.exception(f"流式问答失败: question={question[:50]} 错误: {e}")
        yield {"type": "error", "message": str(e)}
