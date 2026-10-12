"""
Simple RAG 后端主入口

分层与源项目保持一致：api/routes（编排）→ services（业务）→ core（DB/LLM）。
统一响应 {code, msg, data, request_id}，业务异常由全局 handler 渲染。
"""
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.exceptions import BusinessError, business_exception_handler
from config import settings
from core.database import init_db
from utils.logger import log


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 SQLite 表结构"""
    init_db()
    log.info(f"启动 {settings.app_name} v{settings.app_version}")
    log.info(f"文档地址: http://127.0.0.1:{settings.app_port}/docs")
    yield
    log.info("关闭应用")


class RequestIdMiddleware:
    """轻量 ASGI 中间件：注入 request_id 并记录访问日志（不读取响应体，兼容 SSE）"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = f"{time.time():.6f}"
        # 兼容不同 Starlette 版本：确保 scope 中存在 state 字典
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.time()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            method = scope.get("method", "")
            path = scope.get("path", "")
            cost = (time.time() - start) * 1000
            log.info(f"[{request_id}] {method} {path} | {cost:.1f}ms")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="极简 RAG 知识库问答服务：文档入库 + 向量召回 + LLM 生成",
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from api.routes import chat_routes, document_routes  # noqa: E402

app.include_router(document_routes.router)
app.include_router(chat_routes.router)


# ==================== 全局异常处理 ====================

@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    """业务异常处理器（BusinessError 及其子类）"""
    return await business_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求参数验证异常处理器（Pydantic 校验错误）"""
    request_id = getattr(request.state, "request_id", "unknown")
    errors = exc.errors()
    msg = errors[0].get("msg", "参数验证失败") if errors else "参数验证失败"
    log.warning(f"[{request_id}] 参数验证错误: {msg}")
    return JSONResponse(
        status_code=200,
        content={"code": 400, "msg": f"请求参数错误: {msg}", "data": None, "request_id": request_id},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局兜底异常处理器"""
    request_id = getattr(request.state, "request_id", "unknown")
    log.exception(f"[{request_id}] 全局异常捕获: {exc}")
    return JSONResponse(
        status_code=500,
        content={"code": 500, "msg": "服务器内部错误", "data": None, "request_id": request_id},
    )


@app.get("/health")
async def health():
    """健康检查与基础信息（前端由静态目录接管根路径）"""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


# 生产模式下托管前端构建产物（frontend/dist 存在时）
_dist = os.path.abspath(settings.frontend_dist)
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        timeout_keep_alive=120,
    )
