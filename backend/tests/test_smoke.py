"""
冒烟测试（CI 用）

验证应用可正常 import、启动并响应 /health，不触碰任何外部 LLM/Embedding 接口
（core/llm.py 为懒加载，只有真正调用问答时才会读取 OPENAI_API_KEY）。
"""
import os

from fastapi.testclient import TestClient

from main import app


def test_health():
    """健康检查应返回 200 且 status=running"""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert "version" in body
