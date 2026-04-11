import { useGameStore } from '../../store/gameStore';
import './BackgroundLayer.css';

export default function BackgroundLayer() {
  const background = useGameStore((s) => s.background);

  if (!background) {
    return <div className="background-layer background-layer--empty" />;
  }

  return (
    <div className="background-layer">
      <img src={background} alt="" className="background-layer__img" />
    </div>
  );
}
