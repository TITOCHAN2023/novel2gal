import { useState, useCallback } from 'react';
import { useGameStore } from '../../store/gameStore';
import { sendToBackend } from '../../hooks/useBackend';
import type { Choice } from '../../engine/types';
import './ChoicePanel.css';

export default function ChoicePanel() {
  const script = useGameStore((s) => s.script);
  const sceneId = useGameStore((s) => s.currentSceneId);
  const showingChoices = useGameStore((s) => s.showingChoices);
  const selectChoice = useGameStore((s) => s.selectChoice);

  const [annotatingChoice, setAnnotatingChoice] = useState<Choice | null>(null);
  const [annotationText, setAnnotationText] = useState('');

  const notifyBackend = useCallback((choice: Choice, annotation?: string) => {
    sendToBackend({
      cmd: 'player_choice',
      scene_id: sceneId,
      choice_text: choice.text,
      target_scene: choice.targetScene,
      annotation: annotation || '',
    });
  }, [sceneId]);

  const handleLeftClick = useCallback(
    (choice: Choice) => {
      selectChoice(choice);
      notifyBackend(choice);
    },
    [selectChoice, notifyBackend]
  );

  const handleRightClick = useCallback(
    (e: React.MouseEvent, choice: Choice) => {
      e.preventDefault();
      setAnnotatingChoice(choice);
      setAnnotationText('');
    },
    []
  );

  const handleAnnotationSubmit = useCallback(() => {
    if (annotatingChoice) {
      selectChoice(annotatingChoice, annotationText || undefined);
      notifyBackend(annotatingChoice, annotationText || undefined);
      setAnnotatingChoice(null);
      setAnnotationText('');
    }
  }, [annotatingChoice, annotationText, selectChoice, notifyBackend]);

  const handleAnnotationCancel = useCallback(() => {
    setAnnotatingChoice(null);
    setAnnotationText('');
  }, []);

  if (!showingChoices || !script) return null;

  const scene = script.scenes[sceneId];
  const choices = scene?.choices;
  if (!choices || choices.length === 0) return null;

  // 备注输入面板
  if (annotatingChoice) {
    return (
      <div className="choice-panel">
        <div className="choice-annotation">
          <div className="choice-annotation__selected">
            ▸ {annotatingChoice.text}
          </div>
          <div className="choice-annotation__prompt">
            为什么选这个？（可选，影响后续剧情方向）
          </div>
          <textarea
            className="choice-annotation__input"
            value={annotationText}
            onChange={(e) => setAnnotationText(e.target.value)}
            placeholder="写下你的想法..."
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleAnnotationSubmit();
              }
              if (e.key === 'Escape') handleAnnotationCancel();
            }}
          />
          <div className="choice-annotation__actions">
            <button
              className="choice-annotation__btn choice-annotation__btn--submit"
              onClick={handleAnnotationSubmit}
            >
              确认
            </button>
            <button
              className="choice-annotation__btn choice-annotation__btn--cancel"
              onClick={handleAnnotationCancel}
            >
              取消
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="choice-panel">
      <div className="choice-panel__list">
        {choices.map((choice: Choice, i: number) => (
          <button
            key={choice.targetScene || `choice_${i}`}
            className="choice-panel__btn"
            onClick={() => handleLeftClick(choice)}
            onContextMenu={(e) => handleRightClick(e, choice)}
          >
            <span className="choice-panel__btn-text">{choice.text}</span>
            <span className="choice-panel__btn-hint">右键添加备注</span>
          </button>
        ))}
      </div>
    </div>
  );
}
