// 统一 API 封装：项目响应契约 {code, msg, data, request_id}
const BASE = '/api';

async function request(url, options = {}) {
  const res = await fetch(BASE + url, options);
  let body;
  try {
    body = await res.json();
  } catch {
    throw new Error(`服务响应异常（HTTP ${res.status}）`);
  }
  if (body.code !== 200) throw new Error(body.msg || '请求失败');
  return body.data;
}

export function listDocuments(keyword, page = 1) {
  const params = new URLSearchParams({ keyword: keyword || '', page: String(page), page_size: '50' });
  return request(`/documents?${params}`);
}

export function getStats() {
  return request('/documents/stats');
}

export function uploadDocuments(files) {
  const form = new FormData();
  for (const f of files) form.append('files', f);
  return request('/documents/upload', { method: 'POST', body: form });
}

export function deleteDocument(docId) {
  return request(`/documents/${docId}`, { method: 'DELETE' });
}

/**
 * SSE 流式问答：解析 `data: {json}` 事件并回调 onEvent
 * 事件类型：status / references / delta / done / error
 */
export async function streamChat(question, onEvent, signal) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!res.ok || !res.body) {
    let msg = `请求失败（HTTP ${res.status}）`;
    try { msg = (await res.json()).msg || msg; } catch { /* 忽略 */ }
    throw new Error(msg);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 事件以空行分隔
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (line.startsWith('data: ')) {
          try { onEvent(JSON.parse(line.slice(6))); } catch { /* 跳过坏帧 */ }
        }
      }
    }
  }
}
