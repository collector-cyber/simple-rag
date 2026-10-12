# ============================================================================
# Simple RAG — 生产镜像（多阶段构建）
#   Stage 1: 用 Node 构建前端 dist
#   Stage 2: Python 运行时，FastAPI 单端口同时托管 API 与前端静态站点
# 构建：docker build -t simple-rag .
# 运行：docker run -p 8000:8000 --env-file backend/.env simple-rag
# ============================================================================

# ---------- Stage 1: 前端构建 ----------
FROM node:20-alpine AS frontend-build
WORKDIR /frontend
# 先只拷依赖清单，最大化利用 Docker 层缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# 再拷源码并构建
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: 后端运行时 ----------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先装依赖（requirements 不变时命中缓存）
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r ./backend/requirements.txt

# 拷后端代码
COPY backend/ ./backend/
# 从 Stage 1 取前端构建产物，放到 config.frontend_dist 默认解析路径 /app/frontend/dist
COPY --from=frontend-build /frontend/dist ./frontend/dist

# 有状态数据统一写到 /data（ECS 侧把 EFS 挂载到这里）
# LOG_PATH 覆盖 config.py 中默认的 BASE_DIR/data/logs
ENV DATA_DIR=/data \
    LOG_PATH=/data/logs \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

# 以非 root 运行，并预建数据目录（挂 EFS 时会被覆盖，本地运行时可用）
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# 健康检查复用应用自身的 /health（slim 无 curl，用 python 标准库）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

WORKDIR /app/backend
CMD ["python", "main.py"]
