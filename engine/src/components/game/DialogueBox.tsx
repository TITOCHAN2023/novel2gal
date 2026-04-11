import { useEffect, useRef, useCallback } from 'react';
import { useGameStore } from '../../store/gameStore';
import './DialogueBox.css';

export default function DialogueBox() {
  const script = useGameStore((s) => s.script);
  const sceneId = useGameStore((s) => s.currentSceneId);
  const lineIndex = useGameStore((s) => s.currentLineIndex);
  const displayedText = useGameStore((s) => s.displayedText);
  const textComplete = useGameStore((s) => s.textComplete);
  const textSpeed = useGameStore((s) => s.settings.textSpeed);
  const showingChoices = useGameStore((s) => s.showingChoices);
  const setDisplayedText = useGameStore((s) => s.setDisplayedText);
  const setTextComplete = useGameStore((s) => s.setTextComplete);

  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const scene = script?.scenes[sceneId];
  const line = scene?.lines[lineIndex];

  // 打字机效果
  useEffect(() => {
    if (!line || showingChoices) return;

    const fullText = line.text;

    // 速度为 0 → 即时显示
    if (textSpeed === 0) {
      setDisplayedText(fullText);
      setTextComplete(true);
      return;
    }

    setDisplayedText('');
    setTextComplete(false);
    let idx = 0;

    timerRef.current = setInterval(() => {
      idx++;
      if (idx >= fullText.length) {
        setDisplayedText(fullText);
        setTextComplete(true);
        clearInterval(timerRef.current);
      } else {
        setDisplayedText(fullText.slice(0, idx));
      }
    }, textSpeed);

    return () => clearInterval(timerRef.current);
  }, [line, sceneId, lineIndex, textSpeed, showingChoices, setDisplayedText, setTextComplete]);

  const handleClick = useCallback(() => {
    if (!textComplete && line) {
      // 点击 → 跳过打字机效果
      clearInterval(timerRef.current);
      setDisplayedText(line.text);
      setTextComplete(true);
    }
  }, [textComplete, line, setDisplayedText, setTextComplete]);

  if (!line || showingChoices) return null;

  const isNarration = line.type === 'narration';
  const isThought = line.type === 'thought';

  return (
    <div
      className={`dialogue-box ${isNarration ? 'dialogue-box--narration' : ''} ${isThought ? 'dialogue-box--thought' : ''}`}
      onClick={handleClick}
    >
      {line.character && !isNarration && (
        <div className="dialogue-box__name">
          {line.character}
          {line.emotion && line.emotion !== 'neutral' && (
            <span className="dialogue-box__emotion">{line.emotion}</span>
          )}
        </div>
      )}
      <div className="dialogue-box__text">
        {isThought && <span className="dialogue-box__thought-mark">（</span>}
        {displayedText}
        {isThought && textComplete && <span className="dialogue-box__thought-mark">）</span>}
        {!textComplete && <span className="dialogue-box__cursor">▌</span>}
      </div>
      {textComplete && (
        <div className="dialogue-box__indicator">▼</div>
      )}
    </div>
  );
}
