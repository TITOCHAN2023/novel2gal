import { useGameStore } from '../../store/gameStore';
import { useLauncherStore } from '../../store/launcherStore';
import { sendToBackend } from '../../hooks/useBackend';
import { useEffect } from 'react';
import './TitleScreen.css';

export default function TitleScreen() {
  const script = useGameStore((s) => s.script);
  const startGame = useGameStore((s) => s.startGame);
  const setScreen = useGameStore((s) => s.setScreen);
  const currentStoryId = useLauncherStore((s) => s.currentStoryId);
  const stories = useLauncherStore((s) => s.stories);
  const fetchStories = useLauncherStore((s) => s.fetchStories);

  // 定期刷新故事状态（显示生成进度）
  useEffect(() => {
    if (!script) {
      fetchStories();
      const t = setInterval(fetchStories, 3000);
      return () => clearInterval(t);
    }
  }, [script, fetchStories]);

  // 进入标题页时，确保绑定故事并请求场景
  useEffect(() => {
    if (currentStoryId) {
      sendToBackend({ cmd: 'bind_story', story_id: currentStoryId });
    }
  }, [currentStoryId]);

  // 没有 script 时显示友好的等待状态
  if (!script) {
    // 从 launcher store 获取故事状态
    const story = stories.find((s) => s.id === currentStoryId);
    const phase = story?.progress?.phase_name || '';
    const detail = story?.progress?.detail || '';

    return (
      <div className="title-screen">
        <div className="title-screen__content">
          <h1 className="title-screen__title">{story?.title || 'Novel2Gal'}</h1>
          <p className="title-screen__author">
            {phase ? phase : '正在准备故事...'}
          </p>
          {detail && <p className="title-screen__author" style={{fontSize: '12px', opacity: 0.5}}>{detail}</p>}
          <div style={{margin: '24px auto', width: 200, height: 3, background: 'rgba(255,255,255,0.1)', borderRadius: 2, overflow: 'hidden'}}>
            <div style={{
              width: `${story?.progress?.percent || 30}%`,
              height: '100%',
              background: '#e8c170',
              borderRadius: 2,
              transition: 'width 0.5s',
              animation: phase ? 'none' : 'loading-pulse 2s ease infinite',
            }} />
          </div>
          <nav className="title-screen__menu">
            <button className="title-btn title-btn--back" onClick={() => setScreen('launcher')}>
              返回书架
            </button>
          </nav>
        </div>
        <div className="title-screen__footer">Powered by Novel2Gal Engine</div>
      </div>
    );
  }

  return (
    <div className="title-screen">
      <div className="title-screen__content">
        <h1 className="title-screen__title">{script.title}</h1>
        {script.author && (
          <p className="title-screen__author">{script.author}</p>
        )}

        <nav className="title-screen__menu">
          <button className="title-btn" onClick={startGame}>
            开始游戏
          </button>
          <button className="title-btn" onClick={() => setScreen('load')}>
            读取存档
          </button>
          <button className="title-btn" onClick={() => setScreen('settings')}>
            设置
          </button>
          <button className="title-btn title-btn--back" onClick={() => setScreen('launcher')}>
            返回书架
          </button>
        </nav>
      </div>

      <div className="title-screen__footer">
        Powered by Novel2Gal Engine
      </div>
    </div>
  );
}
