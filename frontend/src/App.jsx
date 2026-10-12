import React, { useState } from 'react';
import Chat from './pages/Chat.jsx';
import Knowledge from './pages/Knowledge.jsx';

// 顶部标签切换：问答 / 知识库管理
export default function App() {
  const [tab, setTab] = useState('chat');

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="logo">◆</span> Simple RAG 知识库
        </div>
        <nav className="tabs">
          <button className={tab === 'chat' ? 'tab active' : 'tab'} onClick={() => setTab('chat')}>
            智能问答
          </button>
          <button className={tab === 'knowledge' ? 'tab active' : 'tab'} onClick={() => setTab('knowledge')}>
            知识库管理
          </button>
        </nav>
      </header>
      <main className="main">{tab === 'chat' ? <Chat /> : <Knowledge />}</main>
    </div>
  );
}
