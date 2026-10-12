import React, { useEffect, useRef, useState } from 'react';
import { streamChat } from '../api.js';

// 引用来源卡片：展示文件名、相似度与原文片段
function References({ refs }) {
  if (!refs || !refs.length) return null;
  return (
    <details className="refs" open>
      <summary>参考来源（{refs.length}）</summary>
      {refs.map((r) => (
        <div className="ref" key={r.chunk_id}>
          <div className="ref-head">
            <span>📄 {r.filename}</span>
            <span>相似度 {(r.score * 100).toFixed(1)}%</span>
          </div>
          <div className="ref-content">{r.content}</div>
        </div>
      ))}
    </details>
  );
}

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    // 消息更新后滚动到底部
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  async function send() {
    const question = input.trim();
    if (!question || loading) return;
    setInput('');
    setLoading(true);
    // 先占位一条机器人消息，随流式事件逐步填充
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'bot', content: '', references: [], stage: 'retrieving' },
    ]);

    abortRef.current = new AbortController();
    const appendLast = (patch) =>
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        next[next.length - 1] = typeof patch === 'function' ? patch(last) : { ...last, ...patch };
        return next;
      });

    try {
      await streamChat(
        question,
        (event) => {
          if (event.type === 'references') appendLast({ references: event.references, stage: null });
          else if (event.type === 'delta') appendLast((m) => ({ ...m, content: m.content + event.text }));
          else if (event.type === 'error')
            appendLast((m) => ({ ...m, content: m.content || `回答生成失败：${event.message}`, error: true }));
        },
        abortRef.current.signal
      );
    } catch (e) {
      appendLast((m) => ({ ...m, content: m.content || `请求失败：${e.message}`, error: true }));
    } finally {
      appendLast((m) => ({ ...m, stage: null, done: true }));
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    // Enter 发送，Shift+Enter 换行
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="chat">
      <div className="messages" ref={listRef}>
        {messages.length === 0 && (
          <div className="empty-tip">
            先在「知识库管理」上传文档，<br />然后在这里提问即可获得基于资料的答案。
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'msg user' : 'msg bot'}>
            <span className="role">{m.role === 'user' ? '我' : 'AI 助手'}</span>
            <div className="bubble">
              {m.stage ? '正在检索知识库…' : m.content || '…'}
            </div>
            {m.role === 'bot' && m.done && <References refs={m.references} />}
          </div>
        ))}
      </div>
      <div className="composer">
        <textarea
          value={input}
          placeholder="输入问题，Enter 发送 / Shift+Enter 换行"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button onClick={send} disabled={loading || !input.trim()}>
          {loading ? '生成中' : '发送'}
        </button>
      </div>
    </div>
  );
}
