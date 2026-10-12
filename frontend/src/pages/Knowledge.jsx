import React, { useCallback, useEffect, useRef, useState } from 'react';
import { deleteDocument, getStats, listDocuments, uploadDocuments } from '../api.js';

const STATUS_TEXT = { ready: '已完成', failed: '失败', processing: '处理中' };

export default function Knowledge() {
  const [docs, setDocs] = useState([]);
  const [stats, setStats] = useState({ document_count: 0, chunk_count: 0 });
  const [keyword, setKeyword] = useState('');
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const fileRef = useRef(null);

  const refresh = useCallback(async (kw) => {
    try {
      const [list, st] = await Promise.all([listDocuments(kw || ''), getStats()]);
      setDocs(list.items);
      setStats(st);
    } catch (e) {
      setMessage(`加载失败：${e.message}`);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onUpload() {
    const files = fileRef.current?.files;
    if (!files || !files.length) return;
    setUploading(true);
    setMessage('正在解析并向量化，大文件可能需要一会儿…');
    try {
      const results = await uploadDocuments(files);
      const failed = results.filter((r) => r.status === 'failed');
      setMessage(
        failed.length
          ? `完成 ${results.length - failed.length} 个，失败：${failed.map((f) => `${f.filename}(${f.error})`).join('；')}`
          : `全部上传成功（共 ${results.length} 个文件）`
      );
      fileRef.current.value = '';
      await refresh(keyword);
    } catch (e) {
      setMessage(`上传失败：${e.message}`);
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(doc) {
    if (!window.confirm(`确定删除「${doc.filename}」及其全部向量数据？`)) return;
    try {
      await deleteDocument(doc.id);
      await refresh(keyword);
    } catch (e) {
      setMessage(`删除失败：${e.message}`);
    }
  }

  function formatSize(bytes) {
    if (!bytes) return '-';
    return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
  }

  return (
    <div className="knowledge">
      <div className="stats">
        <div className="stat-card">
          <div className="num">{stats.document_count}</div>
          <div className="label">已入库文档</div>
        </div>
        <div className="stat-card">
          <div className="num">{stats.chunk_count}</div>
          <div className="label">向量分块数</div>
        </div>
      </div>

      <div className="upload-box">
        <input ref={fileRef} type="file" multiple accept=".txt,.md,.pdf,.docx" />
        <button className="btn" onClick={onUpload} disabled={uploading}>
          {uploading ? '处理中…' : '上传入库'}
        </button>
      </div>
      {message && <p style={{ fontSize: 13, color: '#6b7280', marginBottom: 12 }}>{message}</p>}

      <div className="toolbar">
        <input
          value={keyword}
          placeholder="按文件名搜索"
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && refresh(keyword)}
        />
        <button className="btn ghost" style={{ color: '#3b6cf0' }} onClick={() => refresh(keyword)}>
          搜索
        </button>
      </div>

      <table className="doc-table">
        <thead>
          <tr>
            <th>文件名</th>
            <th>类型</th>
            <th>大小</th>
            <th>分块数</th>
            <th>状态</th>
            <th>入库时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {docs.length === 0 && (
            <tr>
              <td colSpan="7" style={{ textAlign: 'center', color: '#6b7280' }}>
                暂无文档，请上传 txt / md / pdf / docx 文件
              </td>
            </tr>
          )}
          {docs.map((d) => (
            <tr key={d.id}>
              <td title={d.error_message || ''}>{d.filename}</td>
              <td>{d.file_type}</td>
              <td>{formatSize(d.file_size)}</td>
              <td>{d.chunk_count}</td>
              <td>
                <span className={`badge ${d.status}`}>{STATUS_TEXT[d.status] || d.status}</span>
              </td>
              <td>{d.created_at}</td>
              <td>
                <button className="btn ghost" onClick={() => onDelete(d)}>
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
