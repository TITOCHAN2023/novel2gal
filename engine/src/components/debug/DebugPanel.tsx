import { useRef, useEffect, useState } from 'react';
import { useBackendStore } from '../../hooks/useBackend';
import './DebugPanel.css';

export default function DebugPanel() {
  const logs = useBackendStore((s) => s.logs);
  const connected = useBackendStore((s) => s.connected);
  const clearLogs = useBackendStore((s) => s.clearLogs);
  const [minimized, setMinimized] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && !minimized) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll, minimized]);

  const getLevelColor = (level?: string) => {
    switch (level) {
      case 'ERROR': return '#ff6b6b';
      case 'WARNING': return '#ffa94d';
      case 'INFO': return '#69db7c';
      case 'DEBUG': return '#748ffc';
      default: return '#868e96';
    }
  };

  const formatTime = (ts?: number) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
  };

  if (minimized) {
    return (
      <div className="debug-panel debug-panel--minimized" onClick={() => setMinimized(false)}>
        <span className={`debug-dot ${connected ? 'debug-dot--on' : 'debug-dot--off'}`} />
        <span>Debug</span>
        <span className="debug-count">{logs.length}</span>
      </div>
    );
  }

  return (
    <div className="debug-panel">
      <div className="debug-header">
        <span className={`debug-dot ${connected ? 'debug-dot--on' : 'debug-dot--off'}`} />
        <span className="debug-title">后端调试工作台</span>
        <div className="debug-actions">
          <button className={`debug-btn ${autoScroll ? 'debug-btn--active' : ''}`} onClick={() => setAutoScroll(!autoScroll)} title="自动滚动">↓</button>
          <button className="debug-btn" onClick={clearLogs} title="清空">清</button>
          <button className="debug-btn" onClick={() => setMinimized(true)} title="最小化">_</button>
        </div>
      </div>
      <div className="debug-body">
        {logs.map((entry, i) => (
          <div key={i} className={`debug-log debug-log--${entry.type}`}>
            <span className="debug-log__time">{formatTime(entry.timestamp)}</span>
            {entry.level && (
              <span className="debug-log__level" style={{ color: getLevelColor(entry.level) }}>{entry.level}</span>
            )}
            {entry.name && <span className="debug-log__name">{entry.name}</span>}
            <span className="debug-log__msg">{entry.message || JSON.stringify(entry)}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
