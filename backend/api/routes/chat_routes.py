"""
RAG 问答路由

提供非流式与 SSE 流式两种问答接口。流式接口把阻塞的
「召回 + LLM 生成」放到线程中执行，通过 asyncio.Queue 转发事件。
"""
import asyncio
import json
import threading

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from api.models import ChatRequest
from api.responses import get_request_id, ok
from services import rag_service

router = APIRouter(prefix="/api/chat", tags=["RAG问答"])


@router.post("")
async def chat(request: Request, body: ChatRequest):
    """非流式问答：一次性返回答案与引用来源"""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, rag_service.answer, body.question, body.top_k)
    return ok(data=result, request_id=get_request_id(request))


@router.post("/stream")
async def chat_stream(request: Request, body: ChatRequest):
    """
    SSE 流式问答事件协议（每条为 data: {json}）：
    - {"type": "status", "stage": "retrieving"}  开始检索
    - {"type": "references", "references": [...]} 召回引用
    - {"type": "delta", "text": "..."}           答案增量
    - {"type": "done"}                            结束
    - {"type": "error", "message": "..."}         失败
    """
    question, top_k = body.question, body.top_k

    async def event_source():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def worker():
            # 同步生成器在工作线程中消费，事件经线程安全方式回灌到事件循环
            for event in rag_service.stream_events(question, top_k):
                loop.call_soon_threadsafe(queue.put_nowait, event)
            loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=worker, daemon=True, name="rag-stream").start()

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
