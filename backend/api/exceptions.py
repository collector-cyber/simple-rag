"""
API 业务异常定义与全局异常处理器

路由层通过 raise BusinessError 子类终止请求，
由 main.py 注册的全局 exception_handler 统一渲染为项目标准 JSON 响应。
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class BusinessError(Exception):
    """业务异常基类

    Attributes:
        code: 业务状态码（如 400、404、500）
        msg: 错误信息
        http_status: HTTP 状态码（默认 200，业务错误通过 body 中 code 表达）
    """

    def __init__(self, code: int, msg: str, http_status: int = 200):
        self.code = code
        self.msg = msg
        self.http_status = http_status


class NotFoundError(BusinessError):
    """资源不存在"""

    def __init__(self, msg: str = "资源不存在"):
        super().__init__(404, msg)


class BadRequestError(BusinessError):
    """请求参数错误或业务校验失败"""

    def __init__(self, msg: str = "请求参数错误"):
        super().__init__(400, msg)


class ServiceUnavailableError(BusinessError):
    """依赖服务（LLM/Embedding）不可用"""

    def __init__(self, msg: str = "外部服务暂不可用，请稍后重试"):
        super().__init__(503, msg)


async def business_exception_handler(request: Request, exc: BusinessError) -> JSONResponse:
    """业务异常处理器：统一转换为 {code, msg, data, request_id} 格式"""
    from utils.logger import log

    request_id = getattr(request.state, "request_id", "unknown")

    if exc.code >= 500:
        log.error(f"[{request_id}] 业务异常: [{exc.code}] {exc.msg}")
    else:
        log.warning(f"[{request_id}] 业务异常: [{exc.code}] {exc.msg}")

    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": exc.code,
            "msg": exc.msg,
            "data": None,
            "request_id": request_id,
        },
    )
