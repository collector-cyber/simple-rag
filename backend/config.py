"""
配置管理模块

所有配置均可通过 backend/.env 或环境变量覆盖；
LLM/Embedding 走 OpenAI 兼容协议，默认对接阿里云百炼（DashScope）。
"""
import os
from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend 目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Settings(BaseSettings):
    """应用配置"""

    # 应用配置
    app_name: str = "simple-rag"
    app_version: str = "0.1.0"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    # 日志配置
    log_level: str = "INFO"
    log_path: str = os.path.join(BASE_DIR, "data", "logs")

    # OpenAI 兼容协议配置（默认百炼 DashScope，可切换任意兼容服务）
    openai_api_key: str = ""
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_model: str = "qwen-plus"  # 聊天模型
    openai_embedding_model: str = "text-embedding-v4"  # 嵌入模型
    openai_embedding_batch_size: int = 10  # 向量批次大小（百炼单批上限有限制）

    # LLM 全局限流：单进程内并发调用 LLM/Embedding 的最大请求数
    llm_max_concurrent: int = 5

    # RAG 参数
    rag_chunk_size: int = 500  # 切分块大小（字符）
    rag_chunk_overlap: int = 80  # 相邻块重叠字符数
    rag_top_k: int = 4  # 默认召回条数
    rag_context_max_chars: int = 4000  # 拼入提示词的上下文总长上限
    rag_system_prompt: str = (
        "你是严谨的知识库问答助手。请根据下面提供的参考资料回答用户问题。\n"
        "要求：\n"
        "1. 只依据参考资料作答，资料中没有的内容不要编造；\n"
        "2. 如果参考资料不足以回答，明确告知用户「知识库中没有找到相关信息」；\n"
        "3. 回答使用中文，条理清晰，可适当引用资料中的表述。\n\n"
        "## 参考资料\n{context}\n"
    )

    # 存储路径
    data_dir: str = os.path.join(BASE_DIR, "data")
    # 前端构建产物目录（存在则由 FastAPI 托管静态站点）
    frontend_dist: str = os.path.join(BASE_DIR, "..", "frontend", "dist")

    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @cached_property
    def upload_dir(self) -> str:
        """原始上传文件目录"""
        return os.path.join(self.data_dir, "uploads")

    @cached_property
    def sqlite_path(self) -> str:
        """SQLite 数据库文件路径"""
        return os.path.join(self.data_dir, "rag.db")


settings = Settings()

# 确保数据目录存在
os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.upload_dir, exist_ok=True)
os.makedirs(settings.log_path, exist_ok=True)
