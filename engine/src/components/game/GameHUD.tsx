import { useGameStore } from '../../store/gameStore';
import './GameHUD.css';

export default function GameHUD() {
  const setScreen = useGameStore((s) => s.setScreen);
  const toggleAutoPlay = useGameStore((s) => s.toggleAutoPlay);
  const toggleBacklog = useGameStore((s) => s.toggleBacklog);
  const autoPlay = useGameStore((s) => s.autoPlay);

  return (
    <div className="game-hud">
      <button className="game-hud__btn" onClick={() => setScreen('save')} title="存档">
        存档
      </button>
      <button className="game-hud__btn" onClick={() => setScreen('load')} title="读档">
        读档
      </button>
      <button
        className={`game-hud__btn ${autoPlay ? 'game-hud__btn--active' : ''}`}
        onClick={toggleAutoPlay}
        title="自动播放"
      >
        自动
      </button>
      <button className="game-hud__btn" onClick={toggleBacklog} title="对话历史">
        回溯
      </button>
      <button className="game-hud__btn" onClick={() => setScreen('settings')} title="设置">
        设置
      </button>
      <button className="game-hud__btn" onClick={() => setScreen('title')} title="返回标题">
        菜单
      </button>
    </div>
  );
}
