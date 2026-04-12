import { useBackendStore } from '../hooks/useBackend';

/**
 * 生产环境断线重连指示器
 * WS 断开时在右下角显示"重新连接中..."提示
 */
export default function ConnectionIndicator() {
  const connected = useBackendStore((s) => s.connected);

  if (connected) return null;

  return (
    <div style={{
      position: 'fixed',
      bottom: 16,
      right: 16,
      zIndex: 9000,
      padding: '8px 16px',
      background: 'rgba(255, 107, 107, 0.9)',
      borderRadius: 6,
      color: '#fff',
      fontSize: 13,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      backdropFilter: 'blur(4px)',
      animation: 'pulse-reconnect 2s ease infinite',
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: '#fff',
        animation: 'blink 1s ease infinite',
      }} />
      <span>reconnecting...</span>
      <style>{`
        @keyframes pulse-reconnect {
          0%, 100% { opacity: 0.9; }
          50% { opacity: 0.6; }
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
