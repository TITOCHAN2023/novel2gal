import { useGameStore } from '../../store/gameStore';
import './SettingsScreen.css';

export default function SettingsScreen() {
  const settings = useGameStore((s) => s.settings);
  const updateSettings = useGameStore((s) => s.updateSettings);
  const setScreen = useGameStore((s) => s.setScreen);

  return (
    <div className="settings-screen">
      <div className="settings-panel">
        <h2 className="settings-panel__title">设置</h2>

        <div className="settings-group">
          <label className="settings-label">
            文字速度
            <div className="settings-slider-row">
              <span className="settings-hint">快</span>
              <input
                type="range"
                min={0}
                max={80}
                step={5}
                value={settings.textSpeed}
                onChange={(e) =>
                  updateSettings({ textSpeed: Number(e.target.value) })
                }
              />
              <span className="settings-hint">慢</span>
              <span className="settings-value">{settings.textSpeed}ms</span>
            </div>
          </label>

          <label className="settings-label">
            自动播放间隔
            <div className="settings-slider-row">
              <span className="settings-hint">短</span>
              <input
                type="range"
                min={500}
                max={5000}
                step={250}
                value={settings.autoPlayDelay}
                onChange={(e) =>
                  updateSettings({ autoPlayDelay: Number(e.target.value) })
                }
              />
              <span className="settings-hint">长</span>
              <span className="settings-value">{(settings.autoPlayDelay / 1000).toFixed(1)}s</span>
            </div>
          </label>
        </div>

        <div className="settings-group">
          <label className="settings-label">
            背景音乐音量
            <div className="settings-slider-row">
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={settings.bgmVolume}
                onChange={(e) =>
                  updateSettings({ bgmVolume: Number(e.target.value) })
                }
              />
              <span className="settings-value">{Math.round(settings.bgmVolume * 100)}%</span>
            </div>
          </label>

          <label className="settings-label">
            音效音量
            <div className="settings-slider-row">
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={settings.sfxVolume}
                onChange={(e) =>
                  updateSettings({ sfxVolume: Number(e.target.value) })
                }
              />
              <span className="settings-value">{Math.round(settings.sfxVolume * 100)}%</span>
            </div>
          </label>

          <label className="settings-label">
            语音音量
            <div className="settings-slider-row">
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={settings.voiceVolume}
                onChange={(e) =>
                  updateSettings({ voiceVolume: Number(e.target.value) })
                }
              />
              <span className="settings-value">{Math.round(settings.voiceVolume * 100)}%</span>
            </div>
          </label>
        </div>

        <div className="settings-actions">
          <button className="settings-back-btn" onClick={() => setScreen('game')}>
            返回游戏
          </button>
        </div>
      </div>
    </div>
  );
}
