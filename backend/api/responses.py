"""
统一 API 响应封装

路由层通过 ok() 快速构造标准成功响应，契约与源项目保持一致：
{"code": 200, "msg": ..., "data": ..., "request_id": ...}
"""

from typing import Any, Optional


def get_request_id(request) -> str:
    """从请求状态中获取 request_id"""
    return getattr(request.state, "request_id", "unknown")


def ok(
    data: Any = None,
    msg: str = "success",
    request_id: Optional[str] = None,
    **extra,
) -> dict:
    """构造标准成功响应"""
    return {
        "code": 200,
        "msg": msg,
        "data": data,
        "request_id": request_id or "",
        **extra,
    }
