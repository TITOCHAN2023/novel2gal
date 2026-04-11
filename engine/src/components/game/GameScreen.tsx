import { useEffect, useCallback, useRef } from 'react';
import { useGameStore } from '../../store/gameStore';
import { audioManager } from '../../engine/AudioManager';
import BackgroundLayer from './BackgroundLayer';
import CharacterLayer from './CharacterLayer';
import DialogueBox from './DialogueBox';
import ChoicePanel from './ChoicePanel';
import EffectLayer from './EffectLayer';
import GameHUD from './GameHUD';
import ProgressIndicator from './ProgressIndicator';
import './GameScreen.css';

export default function GameScreen() {
  const advanceLine = useGameStore((s) => s.advanceLine);
  const showingChoices = useGameStore((s) => s.showingChoices);
  const textComplete = useGameStore((s) => s.textComplete);
  const autoPlay = useGameStore((s) => s.autoPlay);
  const autoPlayDelay = useGameStore((s) => s.settings.autoPlayDelay);
  const bgm = useGameStore((s) => s.bgm);
  const bgmVolume = useGameStore((s) => s.settings.bgmVolume);
  const addPlayTime = useGameStore((s) => s.addPlayTime);
  const showBacklog = useGameStore((s) => s.showBacklog);
  // waitingForContent 由 ProgressIndicator 处理

  // BGM 管理
  useEffect(() => {
    audioManager.setBgmVolume(bgmVolume);
    audioManager.playBgm(bgm);
  }, [bgm, bgmVolume]);

  // 自动播放
  useEffect(() => {
    if (!autoPlay || !textComplete || showingChoices) return;
    const timer = setTimeout(() => advanceLine(), autoPlayDelay);
    return () => clearTimeout(timer);
  }, [autoPlay, textComplete, showingChoices, autoPlayDelay, advanceLine]);

  // 游玩计时
  useEffect(() => {
    const timer = setInterval(() => addPlayTime(1000), 1000);
    return () => clearInterval(timer);
  }, [addPlayTime]);

  // 键盘事件
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (showBacklog) return;
      switch (e.key) {
        case ' ':
        case 'Enter':
          if (!showingChoices) advanceLine();
          break;
      }
    },
    [advanceLine, showingChoices, showBacklog]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // 点击游戏区域推进对话
  const containerRef = useRef<HTMLDivElement>(null);
  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      // 仅当点击的是游戏区域本身（非按钮/选项）时推进
      const target = e.target as HTMLElement;
      if (target.closest('button') || target.closest('.choice-panel')) return;
      if (showingChoices || showBacklog) return;
      advanceLine();
    },
    [advanceLine, showingChoices, showBacklog]
  );

  return (
    <div className="game-screen" ref={containerRef} onClick={handleClick}>
      <BackgroundLayer />
      <CharacterLayer />
      <DialogueBox />
      <ChoicePanel />
      <EffectLayer />
      <ProgressIndicator />
      <GameHUD />
    </div>
  );
}
