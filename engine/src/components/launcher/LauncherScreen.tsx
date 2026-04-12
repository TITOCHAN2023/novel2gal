import { useEffect, useState } from 'react';
import { useGameStore } from '../../store/gameStore';
import { useLauncherStore, type StoryEntry } from '../../store/launcherStore';
import GraphView from './GraphView';
import './LauncherScreen.css';

export default function LauncherScreen() {
  const stories = useLauncherStore((s) => s.stories);
  const loading = useLauncherStore((s) => s.loading);
  const fetchStories = useLauncherStore((s) => s.fetchStories);
  const selectStory = useLauncherStore((s) => s.selectStory);
  const deleteStory = useLauncherStore((s) => s.deleteStory);
  const refreshAssets = useLauncherStore((s) => s.refreshAssets);
  const setScreen = useGameStore((s) => s.setScreen);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [graphStoryId, setGraphStoryId] = useState<string | null>(null);

  useEffect(() => {
    fetchStories();
    // 定时刷新（检测后台流水线进度）
    const timer = setInterval(fetchStories, 5000);
    return () => clearInterval(timer);
  }, [fetchStories]);

  const handleStoryClick = (story: StoryEntry) => {
    selectStory(story.id);
    if (story.status === 'ready' || story.status === 'playable') {
      setScreen('title');
    } else {
      setScreen('setup');
    }
  };

  const handleNewStory = () => {
    setScreen('setup');
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (deleting) return;
    setDeleting(id);
    await deleteStory(id);
    setDeleting(null);
  };

  const getStatusBadge = (status: StoryEntry['status']) => {
    switch (status) {
      case 'ready': return <span className="badge badge--ready">就绪</span>;
      case 'playable': return <span className="badge badge--playable">可玩</span>;
      case 'parsing': return <span className="badge badge--processing">解析中</span>;
      case 'generating': return <span className="badge badge--processing">生成中</span>;
      case 'uploading': return <span className="badge badge--processing">待配置</span>;
      case 'queued': return <span className="badge badge--processing">排队中</span>;
      case 'error': return <span className="badge badge--error">错误</span>;
      default: return null;
    }
  };

  const formatDate = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
  };

  // 空状态
  if (!loading && stories.length === 0) {
    return (
      <div className="launcher-screen">
        <div className="launcher-empty">
          <h1 className="launcher-logo">Novel2Gal</h1>
          <p className="launcher-tagline">将任何小说变成可交互的视觉小说</p>
          <button className="launcher-new-btn launcher-new-btn--large" onClick={handleNewStory}>
            上传你的第一本书
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="launcher-screen">
      <header className="launcher-header">
        <h1 className="launcher-title">我的书架</h1>
        <button className="launcher-new-btn" onClick={handleNewStory}>
          + 新建故事
        </button>
      </header>

      <div className="launcher-grid">
        {stories.map((story) => (
          <div
            key={story.id}
            className={`story-card ${story.status === 'error' ? 'story-card--error' : ''}`}
            onClick={() => handleStoryClick(story)}
          >
            <div className="story-card__header">
              <h3 className="story-card__title">{story.title}</h3>
              {getStatusBadge(story.status)}
            </div>

            {story.status !== 'ready' && story.status !== 'playable' && story.status !== 'error' && story.status !== 'uploading' && (
              <div className="story-card__progress">
                <div className="story-card__progress-bar">
                  <div
                    className="story-card__progress-fill"
                    style={{ width: `${story.progress?.percent || 0}%` }}
                  />
                </div>
                <span className="story-card__progress-text">
                  {story.progress?.phase_name || '处理中...'}
                </span>
              </div>
            )}

            {(story.status === 'ready' || story.status === 'playable') && (
              <div className="story-card__stats">
                <span>{story.stats?.characters || 0} 角色</span>
                <span>{story.stats?.scenes || 0} 场景</span>
                {story.status === 'playable' && <span style={{color: '#e8c170'}}>生成中...</span>}
              </div>
            )}

            {story.status === 'error' && (
              <div className="story-card__error">{story.error || '未知错误'}</div>
            )}

            <div className="story-card__footer">
              <span className="story-card__date">{formatDate(story.updated_at)}</span>
              {(story.status === 'ready' || story.status === 'playable') && (
                <>
                  <button
                    className="story-card__graph"
                    onClick={(e) => { e.stopPropagation(); setGraphStoryId(story.id); }}
                    title="查看关系图"
                  >
                    关系图
                  </button>
                  <button
                    className="story-card__graph"
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (refreshing) return;
                      setRefreshing(story.id);
                      await refreshAssets(story.id);
                      setRefreshing(null);
                    }}
                    disabled={refreshing === story.id}
                    title="刷新图片资产"
                  >
                    {refreshing === story.id ? '...' : '刷新资产'}
                  </button>
                </>
              )}
              <button
                className="story-card__delete"
                onClick={(e) => handleDelete(e, story.id)}
                disabled={deleting === story.id}
              >
                {deleting === story.id ? '...' : '删除'}
              </button>
            </div>
          </div>
        ))}
      </div>

      {graphStoryId && (
        <GraphView storyId={graphStoryId} onClose={() => setGraphStoryId(null)} />
      )}
    </div>
  );
}
