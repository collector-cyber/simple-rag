"""
知识库文档管理路由

上传为 CPU/网络混合型重任务（解析+向量化），放入线程池执行，避免阻塞事件循环。
"""
import asyncio

from fastapi import APIRouter, File, Query, Request, UploadFile

from api.exceptions import BadRequestError, NotFoundError
from api.responses import get_request_id, ok
from services import document_service

# 单文件大小上限 20MB，防止误传超大文件拖垮解析
_MAX_FILE_SIZE = 20 * 1024 * 1024


router = APIRouter(prefix="/api/documents", tags=["知识库文档"])


@router.post("/upload")
async def upload_documents(request: Request, files: list[UploadFile] = File(...)):
    """批量上传文档并入库（逐文件返回处理结果）"""
    if not files:
        raise BadRequestError("未选择任何文件")

    loop = asyncio.get_running_loop()
    results = []
    for f in files:
        content = await f.read()
        if len(content) > _MAX_FILE_SIZE:
            results.append({
                "doc_id": None,
                "filename": f.filename,
                "status": "failed",
                "chunk_count": 0,
                "error": "文件超过 20MB 上限",
            })
            continue
        # 向量化为同步阻塞调用，放入线程池执行
        result = await loop.run_in_executor(
            None, document_service.ingest_file, f.filename, content
        )
        results.append(result)

    success = sum(1 for r in results if r["status"] == "ready")
    return ok(
        data=results,
        msg=f"上传完成：成功 {success} 个，失败 {len(results) - success} 个",
        request_id=get_request_id(request),
    )


@router.get("")
async def list_documents(
    request: Request,
    keyword: str = Query("", description="文件名模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """分页查询文档列表"""
    data = document_service.list_documents(keyword, page, page_size)
    return ok(data=data, request_id=get_request_id(request))


@router.get("/stats")
async def document_stats(request: Request):
    """知识库统计（文档数/分块数）"""
    return ok(data=document_service.get_stats(), request_id=get_request_id(request))


@router.delete("/{doc_id}")
async def delete_document(request: Request, doc_id: str):
    """删除指定文档及其向量数据"""
    if not document_service.get_document(doc_id):
        raise NotFoundError("文档不存在")
    document_service.delete_document(doc_id)
    return ok(msg="删除成功", request_id=get_request_id(request))
