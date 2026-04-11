import { useState, useCallback, useEffect, useRef } from 'react';
import { useGameStore } from '../../store/gameStore';
import { useLauncherStore } from '../../store/launcherStore';
import { useBackend, sendToBackend } from '../../hooks/useBackend';
import './SetupScreen.css';

const PHASES = [
  { label: '正在阅读你的书...', icon: '1' },
  { label: '正在理解故事...', icon: '2' },
  { label: '正在创建世界...', icon: '3' },
  { label: '正在编写第一章...', icon: '4' },
];

export default function SetupScreen() {
  const setScreen = useGameStore((s) => s.setScreen);
  const currentStoryId = useLauncherStore((s) => s.currentStoryId);
  const stories = useLauncherStore((s) => s.stories);
  const uploadBook = useLauncherStore((s) => s.uploadBook);
  const selectStory = useLauncherStore((s) => s.selectStory);
  const fetchStories = useLauncherStore((s) => s.fetchStories);
  const updateStoryFromWS = useLauncherStore((s) => s.updateStoryFromWS);

  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const currentStory = stories.find((s) => s.id === currentStoryId) || null;
  const isUploadMode = !currentStoryId || !currentStory;
  const isReady = currentStory?.status === 'ready';
  const isError = currentStory?.status === 'error';

  // 监听 WebSocket 进度更新
  useBackend(useCallback((data: Record<string, unknown>) => {
    if (data.type === 'pipeline_progress' && data.story_id) {
      updateStoryFromWS(data.story_id as string, {
        progress: {
          phase: data.phase as number,
          phase_name: data.phase_name as string,
          detail: (data.detail as string) || '',
          percent: (data.percent as number) || 0,
        },
      });
    }
    if (data.type === 'pipeline_done' && data.story_id) {
      fetchStories(); // 刷新状态
    }
  }, [updateStoryFromWS, fetchStories]));

  // 绑定故事到 WebSocket
  useEffect(() => {
    if (currentStoryId) {
      sendToBackend({ cmd: 'bind_story', story_id: currentStoryId });
    }
  }, [currentStoryId]);

  // 定时刷新状态
  useEffect(() => {
    if (currentStoryId && !isReady) {
      const timer = setInterval(fetchStories, 3000);
      return () => clearInterval(timer);
    }
  }, [currentStoryId, isReady, fetchStories]);

  const handleFile = async (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (ext !== 'epub' && ext !== 'txt') {
      alert('请上传 .epub 或 .txt 文件');
      return;
    }
    setUploading(true);
    const storyId = await uploadBook(file);
    setUploading(false);
    if (storyId) {
      selectStory(storyId);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  // ---- 上传模式 ----
  if (isUploadMode) {
    return (
      <div className="setup-screen">
        <button className="setup-back" onClick={() => setScreen('launcher')}>
          &larr; 返回书架
        </button>

        <div className="setup-content">
          <h2 className="setup-title">新建故事</h2>
          <p className="setup-desc">上传一本小说，我们会将它变成可交互的视觉小说</p>

          <div
            className={`setup-dropzone ${dragOver ? 'setup-dropzone--active' : ''} ${uploading ? 'setup-dropzone--uploading' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => !uploading && fileInputRef.current?.click()}
          >
            {uploading ? (
              <span className="setup-dropzone__text">上传中...</span>
            ) : (
              <>
                <span className="setup-dropzone__icon">+</span>
                <span className="setup-dropzone__text">
                  拖拽文件到这里，或点击选择
                </span>
                <span className="setup-dropzone__hint">支持 .epub 和 .txt</span>
              </>
            )}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".epub,.txt"
            style={{ display: 'none' }}
            onChange={handleFileInput}
          />
        </div>
      </div>
    );
  }

  // ---- 进度模式 ----
  const phase = currentStory?.progress?.phase || 0;
  const percent = currentStory?.progress?.percent || 0;
  const detail = currentStory?.progress?.detail || '';

  return (
    <div className="setup-screen">
      <button className="setup-back" onClick={() => setScreen('launcher')}>
        &larr; 返回书架
      </button>

      <div className="setup-content">
        <h2 className="setup-title">{currentStory?.title}</h2>

        {isError ? (
          <div className="setup-error">
            <p className="setup-error__text">{currentStory?.error || '初始化失败'}</p>
            <button className="setup-retry-btn" onClick={() => {
              // TODO: 重试
              fetchStories();
            }}>
              重试
            </button>
          </div>
        ) : isReady ? (
          <div className="setup-done">
            <div className="setup-done__icon">&#10003;</div>
            <p className="setup-done__text">故事已就绪！</p>
            <div className="setup-done__stats">
              <span>{currentStory.stats?.characters || 0} 个角色</span>
              <span>{currentStory.stats?.scenes || 0} 个场景</span>
            </div>
            <button className="setup-play-btn" onClick={() => setScreen('title')}>
              开始游玩
            </button>
          </div>
        ) : (
          <>
            {/* 4 阶段步进条 */}
            <div className="setup-stepper">
              {PHASES.map((p, i) => {
                const stepNum = i + 1;
                const isCurrent = phase === stepNum;
                const isDone = phase > stepNum;
                return (
                  <div
                    key={i}
                    className={`setup-step ${isDone ? 'setup-step--done' : ''} ${isCurrent ? 'setup-step--current' : ''}`}
                  >
                    <div className="setup-step__circle">
                      {isDone ? '✓' : p.icon}
                    </div>
                    <div className="setup-step__label">{p.label}</div>
                  </div>
                );
              })}
            </div>

            {/* 当前阶段进度 */}
            <div className="setup-phase-progress">
              <div className="setup-phase-bar">
                <div className="setup-phase-fill" style={{ width: `${percent}%` }} />
              </div>
              <p className="setup-phase-detail">{detail}</p>
            </div>

            <p className="setup-hint">
              完整小说可能需要 30-60 分钟处理。你可以关闭这个页面，稍后回来查看。
            </p>
          </>
        )}
      </div>
    </div>
  );
}
