import { useCallback } from 'react';
import { useGameStore } from './store/gameStore';
import { useLauncherStore } from './store/launcherStore';
import LauncherScreen from './components/launcher/LauncherScreen';
import SetupScreen from './components/setup/SetupScreen';
import TitleScreen from './components/menu/TitleScreen';
import GameScreen from './components/game/GameScreen';
import SaveLoadScreen from './components/save/SaveLoadScreen';
import SettingsScreen from './components/settings/SettingsScreen';
import BacklogPanel from './components/backlog/BacklogPanel';
import DebugPanel from './components/debug/DebugPanel';
import { useBackend, sendToBackend } from './hooks/useBackend';

export default function App() {
  const screen = useGameStore((s) => s.screen);
  const loadScript = useGameStore((s) => s.loadScript);
  const injectScenes = useGameStore((s) => s.injectScenes);
  const script = useGameStore((s) => s.script);
  const currentStoryId = useLauncherStore((s) => s.currentStoryId);

  const handleBackendMessage = useCallback((data: Record<string, unknown>) => {
    // 场景推送
    if (data.type === 'scenes_ready') {
      const scenes = data.scenes as Record<string, unknown>;
      const firstScene = (data.firstScene as string) || 'scene_root';
      if (!script) {
        loadScript({
          title: (data.title as string) || 'Novel2Gal',
          author: (data.author as string) || '',
          firstScene,
          scenes: scenes as never,
        });
      } else {
        injectScenes(scenes as never);
      }
    }

    // 绑定故事后，如果已就绪自动请求场景
    if (data.type === 'story_bound' && data.status === 'ready') {
      sendToBackend({ cmd: 'get_scenes' });
    }
  }, [loadScript, injectScenes, script]);

  useBackend(handleBackendMessage);

  // bind_story 由 TitleScreen / SetupScreen 各自的 useEffect 负责，
  // 不在此处发送——render body 中的副作用会每次渲染都触发，导致竞态。

  return (
    <div className="app-root">
      <DebugPanel />
      {screen === 'launcher' && <LauncherScreen />}
      {screen === 'setup' && <SetupScreen />}
      {screen === 'title' && <TitleScreen />}
      {screen === 'game' && (
        <>
          <GameScreen />
          <BacklogPanel />
        </>
      )}
      {(screen === 'save' || screen === 'load') && <SaveLoadScreen />}
      {screen === 'settings' && <SettingsScreen />}
    </div>
  );
}
