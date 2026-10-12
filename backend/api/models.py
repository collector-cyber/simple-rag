"""
API 请求/响应模型（Pydantic）
"""
from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """RAG 问答请求"""

    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    top_k: Optional[int] = Field(None, ge=1, le=20, description="召回条数，默认取配置值")
