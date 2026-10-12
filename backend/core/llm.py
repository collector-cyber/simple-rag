"""
LLM / Embedding 统一调用入口

项目中所有 LLM 与向量调用都必须经过本模块（与源项目 core/embeddings.py 同构）：
- 进程级信号量限流，防止并发打爆外部接口
- thread-local 客户端，避免多线程共享 httpx.Client 引发竞争
- 指数退避重试
"""
import threading
import time
from typing import List, Optional

import numpy as np
from openai import OpenAI

from config import settings
from utils.logger import log

# 重试配置
_MAX_RETRIES = 4
_BASE_DELAY = 2  # 基础等待秒数
_MAX_DELAY = 30  # 最大等待秒数

# 全局并发限流信号量（懒加载单例）
_semaphore: Optional[threading.Semaphore] = None
_semaphore_lock = threading.Lock()


def _get_semaphore() -> threading.Semaphore:
    """获取进程级 LLM 并发限流信号量"""
    global _semaphore
    if _semaphore is None:
        with _semaphore_lock:
            if _semaphore is None:
                _semaphore = threading.Semaphore(settings.llm_max_concurrent)
    return _semaphore


# 线程隔离的 OpenAI 客户端：httpx.Client 不保证线程安全，按线程懒加载
_tls = threading.local()


def _get_client() -> OpenAI:
    """获取当前线程的 OpenAI 客户端"""
    client = getattr(_tls, "client", None)
    if client is None:
        if not settings.openai_api_key:
            raise RuntimeError("未配置 OPENAI_API_KEY，请在 backend/.env 中设置")
        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        _tls.client = client
    return client


def _with_retry(func, desc: str):
    """通用重试包装：指数退避，超过最大次数后抛出"""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with _get_semaphore():
                return func()
        except Exception as e:
            delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
            if attempt < _MAX_RETRIES:
                log.warning(f"{desc} 失败（第{attempt}次），{delay}s 后重试: {e}")
                time.sleep(delay)
            else:
                log.error(f"{desc} 失败，已达最大重试次数（{_MAX_RETRIES}）: {e}")
                raise


def embed_texts(texts: List[str]) -> np.ndarray:
    """
    批量生成文本向量（自动分批 + 重试）

    Args:
        texts: 文本列表

    Returns:
        形状为 (len(texts), dim) 的 float32 向量矩阵
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    client = _get_client()
    all_vectors = []
    batch = settings.openai_embedding_batch_size
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]

        def _call(chunk=chunk):
            resp = client.embeddings.create(model=settings.openai_embedding_model, input=chunk)
            return [item.embedding for item in resp.data]

        all_vectors.extend(_with_retry(_call, f"Embedding 调用（批次 {i // batch + 1}）"))
    return np.array(all_vectors, dtype=np.float32)


def chat_completion(
    messages: List[dict],
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> str:
    """
    非流式聊天补全，返回完整文本

    Args:
        messages: OpenAI 格式消息列表
        temperature: 生成温度，RAG 问答默认低温度保证稳定
        max_tokens: 最大输出 token 数，None 不限制
        model: 模型名称，None 使用配置默认值
    """
    client = _get_client()

    def _call():
        kwargs = {
            "model": model or settings.openai_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    return _with_retry(_call, "LLM 聊天调用").strip()


def chat_stream(messages: List[dict], temperature: float = 0.3):
    """
    流式聊天补全：逐段 yield 增量文本（在线程中安全调用）

    注意：流式响应不套用重试包装，建连失败会直接抛出，由上层转成错误事件。
    """
    client = _get_client()
    with _get_semaphore():
        stream = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for event in stream:
            delta = event.choices[0].delta.content if event.choices else None
            if delta:
                yield delta
