/**
 * 共享的后端 WebSocket 连接 hook
 *
 * 全局单例——所有组件共用一个 WS 连接
 */
import { useEffect, useRef } from 'react';
import { create } from 'zustand';

// WS 地址——统一走当前 host（dev 模式由 Vite proxy 转发到后端，prod 同源）
const BACKEND_WS = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/debug`;

interface BackendLog {
  type: string;
  level?: string;
  name?: string;
  message?: string;
  timestamp?: number;
  [key: string]: unknown;
}

interface BackendState {
  connected: boolean;
  logs: BackendLog[];
  setConnected: (v: boolean) => void;
  addLog: (log: BackendLog) => void;
  clearLogs: () => void;
}

export const useBackendStore = create<BackendState>((set) => ({
  connected: false,
  logs: [],
  setConnected: (v) => set({ connected: v }),
  addLog: (log) =>
    set((s) => ({
      logs: s.logs.length > 500 ? [...s.logs.slice(-400), log] : [...s.logs, log],
    })),
  clearLogs: () => set({ logs: [] }),
}));

// 全局单例 WS
let ws: WebSocket | null = null;
// reconnect 由 onclose 内部 setTimeout 管理

type MessageHandler = (data: Record<string, unknown>) => void;
const handlers = new Set<MessageHandler>();

function connectWS() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;

  ws = new WebSocket(BACKEND_WS);
  const store = useBackendStore.getState();

  ws.onopen = () => {
    store.setConnected(true);
    store.addLog({ type: 'system', message: '已连接后端', timestamp: Date.now() / 1000 });
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      // 日志类消息 → 推到 store + console
      if (data.type === 'log') {
        store.addLog(data);
        const level = data.level?.toLowerCase() || 'info';
        const msg = `[${data.name || 'backend'}] ${data.message || ''}`;
        if (level === 'error') console.error(msg);
        else if (level === 'warning') console.warn(msg);
        else console.log(`%c${msg}`, 'color: #888');
      }
      // 所有消息 → 通知 handlers
      handlers.forEach((h) => h(data));
    } catch { /* ignore */ }
  };

  ws.onclose = () => {
    store.setConnected(false);
    store.addLog({ type: 'system', message: '连接断开，3秒后重连...', timestamp: Date.now() / 1000 });
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws?.close();
}

export function sendToBackend(data: Record<string, unknown>) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

/**
 * 使用后端连接
 *
 * onMessage: 接收非日志消息（scenes_ready, pipeline_done 等）
 */
export function useBackend(onMessage?: MessageHandler) {
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  useEffect(() => {
    // 确保 WS 已连接
    connectWS();

    if (handlerRef.current) {
      const handler: MessageHandler = (data) => handlerRef.current?.(data);
      handlers.add(handler);
      return () => { handlers.delete(handler); };
    }
  }, []);

  return { sendToBackend };
}
