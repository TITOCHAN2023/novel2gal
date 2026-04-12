import { useState, useEffect, useCallback, useRef } from 'react';
import { useGameStore } from '../../store/gameStore';
import { useBackendStore, useBackend, sendToBackend } from '../../hooks/useBackend';
import './ProgressIndicator.css';

interface GenerationStatus {
  phase: number;
  phaseName: string;
  detail: string;
  percent: number;
  gapRemaining: number; // 玩家当前位置到生成前沿的距离
}

export default function ProgressIndicator() {
  const [status, setStatus] = useState<GenerationStatus | null>(null);
  const [minimized, setMinimized] = useState(false);
  useBackendStore((s) => s.connected); // 触发重渲染
  const waitingForContent = useGameStore((s) => s.waitingForContent);
  const currentSceneId = useGameStore((s) => s.currentSceneId);
  const script = useGameStore((s) => s.script);

  // 监听后端进度消息
  useBackend(useCallback((data: Record<string, unknown>) => {
    if (data.type === 'pipeline_progress') {
      setStatus({
        phase: (data.phase as number) || 0,
        phaseName: (data.phase_name as string) || '',
        detail: (data.detail as string) || '',
        percent: (data.percent as number) || 0,
        gapRemaining: 0,
      });
    }
    if (data.type === 'pipeline_done' || data.type === 'scenes_ready') {
      setStatus(null); // 生成完成，隐藏
    }
  }, []));

  const gapSetting = useGameStore((s) => s.settings.gap);
  const pregeneratingRef = useRef(false);

  // 计算 Gap 距离：当前场景子树内的最大深度
  useEffect(() => {
    if (!script || !currentSceneId) return;
    const scenes = script.scenes;
    const current = scenes[currentSceneId];
    if (!current) return;

    const currentDepth = current.depth ?? 0;

    // 只在玩家可达子树内找最深叶子（BFS/DFS from currentSceneId）
    let maxDepth = currentDepth;
    let deepestLeaf = currentSceneId;
    const visited = new Set<string>();
    const queue = [currentSceneId];
    while (queue.length > 0) {
      const sid = queue.shift()!;
      if (visited.has(sid)) continue;
      visited.add(sid);
      const scene = scenes[sid];
      if (!scene) continue;
      const d = (scene as { depth?: number }).depth ?? 0;
      if (d > maxDepth) {
        maxDepth = d;
        deepestLeaf = sid;
      }
      // 找子场景：通过 choices 或 nextScene
      if (scene.choices) {
        for (const c of scene.choices) {
          if (c.targetScene && scenes[c.targetScene]) queue.push(c.targetScene);
        }
      }
      if (scene.nextScene && scenes[scene.nextScene]) queue.push(scene.nextScene);
    }

    const remainingGap = maxDepth - currentDepth;

    // 只在 gap 小于设定值时显示警告
    if (remainingGap <= Math.min(gapSetting, 3) && remainingGap >= 0) {
      setStatus((prev) => prev ? { ...prev, gapRemaining: remainingGap } : {
        phase: 0, phaseName: '', detail: '', percent: 0, gapRemaining: remainingGap,
      });
    }

    // 主动触发 Gap 预生成（当剩余 gap 不足设定值的一半时）
    if (remainingGap < Math.ceil(gapSetting / 2) && !pregeneratingRef.current) {

      pregeneratingRef.current = true;
      sendToBackend({
        cmd: 'gap_pregenerate',
        from_scene: deepestLeaf,
        gap_depth: gapSetting,
      });

      // 30秒后重置标记，允许再次触发
      setTimeout(() => { pregeneratingRef.current = false; }, 30000);
    }
  }, [script, currentSceneId, gapSetting]);

  // 不显示的情况：没有状态且不在等待
  if (!status && !waitingForContent) return null;

  // 最小化状态
  if (minimized) {
    return (
      <div className="progress-indicator progress-indicator--minimized" onClick={() => setMinimized(false)}>
        {waitingForContent ? (
          <span className="progress-indicator__dot progress-indicator__dot--generating" />
        ) : status && status.gapRemaining <= 2 ? (
          <span className="progress-indicator__dot progress-indicator__dot--warning" />
        ) : (
          <span className="progress-indicator__dot progress-indicator__dot--ok" />
        )}
      </div>
    );
  }

  return (
    <div className="progress-indicator">
      <button className="progress-indicator__minimize" onClick={() => setMinimized(true)}>_</button>

      {/* 正在等待内容 */}
      {waitingForContent && (
        <div className="progress-indicator__waiting">
          <div className="progress-indicator__spinner" />
          <span>正在创作新章节...</span>
        </div>
      )}

      {/* 流水线进度 */}
      {status && status.phaseName && (
        <div className="progress-indicator__pipeline">
          <span className="progress-indicator__phase">{status.phaseName}</span>
          {status.detail && <span className="progress-indicator__detail">{status.detail}</span>}
          {status.percent > 0 && (
            <div className="progress-indicator__bar">
              <div className="progress-indicator__fill" style={{ width: `${status.percent}%` }} />
            </div>
          )}
        </div>
      )}

      {/* Gap 距离指示 */}
      {status && status.gapRemaining >= 0 && status.gapRemaining <= 2 && !waitingForContent && (
        <div className={`progress-indicator__gap ${status.gapRemaining === 0 ? 'progress-indicator__gap--danger' : 'progress-indicator__gap--warning'}`}>
          {status.gapRemaining === 0 ? (
            <span>已到达最新章节，后续内容生成中</span>
          ) : (
            <span>还有 {status.gapRemaining} 个章节缓冲</span>
          )}
        </div>
      )}
    </div>
  );
}
