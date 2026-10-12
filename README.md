# Simple RAG — 极简知识库问答系统

参考 [clinchoice-ai-knowledge](../clinchoice-ai-knowledge) 的分层架构搭建的轻量级 RAG 项目：
文档上传解析 → 切分向量化 → 余弦相似度召回 → LLM 流式生成带引用的回答。

## 技术选型

| 层 | 方案 | 说明 |
|---|---|---|
| 后端 | FastAPI + uvicorn | 与源项目一致的 `{code, msg, data, request_id}` 响应契约与全局异常处理 |
| 存储 | SQLite + numpy | documents/chunks 两表；向量 JSON 存储，全量载入内存做余弦检索 |
| LLM | OpenAI 兼容协议 | 默认阿里云百炼（qwen-plus + text-embedding-v4），env 可切换任意兼容服务 |
| 生成 | SSE 流式问答 | `POST /api/chat/stream`，先推引用、再推答案增量 |
| 前端 | React 18 + Vite | 聊天页 + 知识库管理页，开发态 vite proxy、生产态由 FastAPI 托管 dist |

## 目录结构

```
simple-rag/
├── backend/
│   ├── main.py               # 应用入口：中间件、路由注册、全局异常处理
│   ├── config.py             # pydantic-settings 配置（.env 覆盖）
│   ├── api/
│   │   ├── responses.py      # ok() 统一成功响应
│   │   ├── exceptions.py     # BusinessError 统一业务异常
│   │   ├── models.py         # Pydantic 请求模型
│   │   └── routes/           # document_routes / chat_routes
│   ├── core/
│   │   ├── database.py       # SQLite 访问与建表
│   │   └── llm.py            # 所有 LLM/Embedding 调用的统一入口（限流+重试）
│   ├── services/
│   │   ├── document_service.py  # 解析、切分、向量化入库
│   │   └── rag_service.py       # 召回缓存、上下文构建、流式问答
│   └── utils/logger.py       # loguru 日志
└── frontend/
    ├── vite.config.js        # /api 代理到 8000 端口
    └── src/
        ├── api.js            # fetch 封装 + SSE 解析
        └── pages/            # Chat.jsx / Knowledge.jsx
```

## 快速开始

### 1. 后端

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填入 OPENAI_API_KEY（百炼 DashScope Key）
python main.py                # http://127.0.0.1:8000/docs
```

### 2. 前端（开发模式）

```bash
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173（/api 自动代理到后端）
```

### 3. 生产模式（单端口部署）

```bash
cd frontend && npm run build  # 产出 dist/
cd ../backend && python main.py  # FastAPI 自动托管 dist，访问 :8000 即可
```

## 核心流程

1. **入库**：上传 txt/md/pdf/docx → `extract_text` 提取文本 → 滑窗切分（500 字 / 80 重叠）
   → `embed_texts` 批量向量化 → 写入 chunks 表。
2. **检索**：问题向量化 → 与内存中的归一化向量矩阵点积（即余弦相似度）→ Top K。
   缓存以 chunks 行数判变更自动重建。
3. **生成**：Top K 拼接为「参考资料」注入 system prompt → qwen 流式生成，
   SSE 依次推送 `references` → `delta`* → `done` 事件。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/documents/upload` | 批量上传并入库（multipart files） |
| GET | `/api/documents` | 分页文档列表（keyword 模糊搜索） |
| GET | `/api/documents/stats` | 知识库统计 |
| DELETE | `/api/documents/{id}` | 删除文档及其向量 |
| POST | `/api/chat` | 非流式问答，返回答案+引用 |
| POST | `/api/chat/stream` | SSE 流式问答 |
| GET | `/health` | 健康检查 |

## CI/CD 与 AWS 部署

项目内置 GitHub Actions 流水线（`.github/workflows/`），采用业界标准的
**CI + CD + ECR + ECS Fargate + OIDC** 组合，密钥零落地。

| 文件 | 作用 |
|---|---|
| `.github/workflows/ci.yml` | CI：PR / push main 时跑后端语法检查+冒烟测试、前端构建 |
| `.github/workflows/deploy.yml` | CD：push main 时构建镜像推 ECR，并触发 ECS 滚动更新 |
| `Dockerfile` | 多阶段构建：Node 打前端 dist → Python 运行时单端口托管 |

架构（A 方案）：

```
git push main → GitHub Actions ──OIDC换临时凭证──► AWS
   ├─ 冒烟测试(python -m pytest)
   ├─ docker build → push Amazon ECR
   └─ aws ecs update-service --force-new-deployment
                                     │
                          ECS Fargate 拉新镜像滚动更新
                          /data 挂载 EFS（rag.db + uploads 持久化）
```

### 一、AWS 侧一次性资源

1. **ECR 私有仓库**：命名 `simple-rag`。
2. **EFS 文件系统**：与安全组同 VPC，创建 `elasticfilesystem:elasticfilesystem:root-access` 之外的挂载点；供 `/data` 持久化。
3. **IAM Task/Execution Role**：ECS 拉镜像（ECR 读 + EFS 写）所需权限。
4. **集群 + 服务 + Task Definition（Fargate）**：
   - 容器镜像填 ECR 仓库的 `:latest`；端口映射 8000；
   - 环境变量：`OPENAI_API_KEY`（放 Secrets Manager，经 `secrets` 注入）；
   - 存储：挂载 EFS 到容器 `/data`；
   - 网络：配 ALB + Security Group，或先临时公网直连验证。

### 二、打通 GitHub ↔ AWS 权限（OIDC，推荐）

> 不用 Access Key，流水线每次跑用一个 15 分钟临时凭证。官方安全做法。

1. IAM → Identity providers → Add → OpenID Connect：
   - Provider URL：`https://token.actions.githubusercontent.com`
   - Audience：`sts.amazonaws.com`
2. 建 IAM Role，信任策略允许你的仓库扮演（关键字段）：
   ```json
   {
     "Effect": "Allow",
     "Principal": {"AWS": "arn:aws:iam::<账号ID>:oidc-provider/token.actions.githubusercontent.com"},
     "Action": "sts:AssumeRoleWithWebIdentity",
     "Condition": {
       "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
       "StringLike": {"token.actions.githubusercontent.com:sub": "repo:<你的GitHub用户名>/simple-rag:*"}
     }
   }
   ```
3. 给该 Role 挂策略：ECR 推送（`AmazonEC2ContainerRegistryPowerUser`）、
   ECS 更新（`AmazonECS_FullAccess`）、`iam:PassRole`（传递 Task/Execution Role）。
4. GitHub 仓库 → Settings → Secrets and variables → Actions → **Variables** 新增：
   - `AWS_ROLE_ARN` = 上面 Role 的 ARN（ARN 非机密，用 variable 不用 secret）。

### 三、本地先验证镜像

```bash
docker build -t simple-rag .
docker run -p 8000:8000 --env-file backend/.env simple-rag
# 访问 http://127.0.0.1:8000/health
```

> ⚠️ 提示：uploads 走 EFS 只是「不改代码就能跑起来」的过渡方案。数据量/并发上来后，
> 建议按业界 B 方案演进：上传文件迁 **S3**、数据库换 **RDS PostgreSQL + pgvector**。

## 已知边界（有意保持简单）

- 向量全量载入内存检索，适合万级以内 chunk；更大规模应换 pgvector / Faiss。
- 切分策略为固定滑窗，未按标题/语义结构切分。
- 无鉴权、无多租户；单机单知识库。
