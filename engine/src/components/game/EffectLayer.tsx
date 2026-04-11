import { useEffect } from 'react';
import { useGameStore } from '../../store/gameStore';
import './EffectLayer.css';

export default function EffectLayer() {
  const transition = useGameStore((s) => s.transition);
  const isTransitioning = useGameStore((s) => s.isTransitioning);
  const setTransitioning = useGameStore((s) => s.setTransitioning);

  useEffect(() => {
    if (!isTransitioning) return;

    const duration = transition === 'blackout' ? 800 : 600;
    const timer = setTimeout(() => {
      setTransitioning(false);
    }, duration);

    return () => clearTimeout(timer);
  }, [isTransitioning, transition, setTransitioning]);

  if (!isTransitioning) return null;

  let className = 'effect-layer';
  if (transition === 'fade') className += ' effect-layer--fade';
  if (transition === 'blackout') className += ' effect-layer--blackout';
  if (transition === 'dissolve') className += ' effect-layer--dissolve';

  return <div className={className} />;
}
