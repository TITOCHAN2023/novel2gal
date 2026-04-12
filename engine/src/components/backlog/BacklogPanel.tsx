import { useRef, useEffect } from 'react';
import { useGameStore } from '../../store/gameStore';
import './BacklogPanel.css';

export default function BacklogPanel() {
  const backlog = useGameStore((s) => s.backlog);
  const showBacklog = useGameStore((s) => s.showBacklog);
  const toggleBacklog = useGameStore((s) => s.toggleBacklog);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (showBacklog) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [showBacklog, backlog.length]);

  if (!showBacklog) return null;

  return (
    <div className="backlog-overlay" onClick={toggleBacklog}>
      <div className="backlog-panel" onClick={(e) => e.stopPropagation()}>
        <div className="backlog-panel__header">
          <h2>对话回溯</h2>
          <button className="backlog-panel__close" onClick={toggleBacklog}>
            ✕
          </button>
        </div>
        <div className="backlog-panel__content">
          {backlog.length === 0 && (
            <div className="backlog-panel__empty">暂无对话记录</div>
          )}
          {backlog.map((entry, i) => (
            <div key={`${entry.sceneId}-${i}`} className={`backlog-entry backlog-entry--${entry.type}`}>
              {entry.character && (
                <span className="backlog-entry__name">{entry.character}</span>
              )}
              <span className="backlog-entry__text">{entry.text}</span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
