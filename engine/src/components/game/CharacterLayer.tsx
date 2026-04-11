import { useGameStore } from '../../store/gameStore';
import type { CharacterOnScreen } from '../../engine/types';
import './CharacterLayer.css';

const POSITION_MAP: Record<string, string> = {
  left: '20%',
  center: '50%',
  right: '80%',
};

function CharacterSprite({ char }: { char: CharacterOnScreen }) {
  const style: React.CSSProperties = {
    left: POSITION_MAP[char.position] ?? '50%',
    transform: `translateX(-50%)${char.flipped ? ' scaleX(-1)' : ''}`,
    opacity: char.isActive ? 1 : 0.7,
    filter: char.isActive ? 'none' : 'brightness(0.8)',
  };

  // 没有立绘时显示名字占位符（而不是碎图标）
  if (!char.sprite) {
    return (
      <div className="character-sprite character-sprite--placeholder" style={style}>
        <div className="character-placeholder">
          <span className="character-placeholder__initial">{char.name.charAt(0)}</span>
          <span className="character-placeholder__name">{char.name}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="character-sprite" style={style}>
      <img
        src={char.sprite}
        alt={char.name}
        draggable={false}
        onError={(e) => {
          // emotion sprite 不存在时 fallback 到基础立绘
          const target = e.currentTarget;
          const basePath = char.sprite.replace(/outfit_[^/]+\/emotion\/.*/, 'base/sprite.png');
          if (target.src !== basePath && basePath !== char.sprite) {
            target.src = basePath;
          }
        }}
      />
    </div>
  );
}

export default function CharacterLayer() {
  const characters = useGameStore((s) => s.characters);

  return (
    <div className="character-layer">
      {characters.map((char) => (
        <CharacterSprite key={char.id} char={char} />
      ))}
    </div>
  );
}
