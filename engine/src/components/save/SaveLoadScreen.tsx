import { useState, useEffect, useCallback } from 'react';
import { useGameStore } from '../../store/gameStore';
import { saveGame, loadGame, listSaves, deleteSave } from '../../engine/SaveManager';
import type { SaveSlot } from '../../engine/types';
import './SaveLoadScreen.css';

const SLOT_COUNT = 12;

export default function SaveLoadScreen() {
  const screen = useGameStore((s) => s.screen);
  const setScreen = useGameStore((s) => s.setScreen);
  const getSnapshot = useGameStore((s) => s.getSnapshot);
  const restoreFromSave = useGameStore((s) => s.restoreFromSave);

  const isSaveMode = screen === 'save';
  const [slots, setSlots] = useState<(SaveSlot | null)[]>(
    Array(SLOT_COUNT).fill(null)
  );

  const refreshSlots = useCallback(async () => {
    const saved = await listSaves();
    const map = new Map(saved.map((s) => [s.id, s]));
    setSlots(Array.from({ length: SLOT_COUNT }, (_, i) => map.get(i + 1) ?? null));
  }, []);

  useEffect(() => {
    refreshSlots();
  }, [refreshSlots]);

  const handleSlotClick = async (slotId: number) => {
    if (isSaveMode) {
      const snap = getSnapshot();
      const slot: SaveSlot = {
        id: slotId,
        timestamp: Date.now(),
        sceneId: snap.sceneId,
        lineIndex: snap.lineIndex,
        playPath: snap.playPath,
        preview: snap.preview,
        playTimeMs: snap.playTime,
      };
      await saveGame(slot);
      await refreshSlots();
    } else {
      const slot = await loadGame(slotId);
      if (slot) {
        restoreFromSave(slot.sceneId, slot.lineIndex, slot.playPath);
      }
    }
  };

  const handleDelete = async (e: React.MouseEvent, slotId: number) => {
    e.stopPropagation();
    await deleteSave(slotId);
    await refreshSlots();
  };

  const formatTime = (ms: number) => {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    return `${h}:${String(m % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  };

  const formatDate = (ts: number) =>
    new Date(ts).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });

  return (
    <div className="saveload-screen">
      <div className="saveload-panel">
        <div className="saveload-header">
          <h2>{isSaveMode ? '存档' : '读档'}</h2>
          <button className="saveload-close" onClick={() => setScreen('game')}>
            返回
          </button>
        </div>

        <div className="saveload-grid">
          {slots.map((slot, i) => {
            const slotId = i + 1;
            return (
              <div
                key={slotId}
                className={`save-slot ${slot ? 'save-slot--filled' : 'save-slot--empty'}`}
                onClick={() => handleSlotClick(slotId)}
              >
                <div className="save-slot__id">Slot {slotId}</div>
                {slot ? (
                  <>
                    <div className="save-slot__preview">{slot.preview}</div>
                    <div className="save-slot__meta">
                      <span>{formatDate(slot.timestamp)}</span>
                      <span>{formatTime(slot.playTimeMs)}</span>
                    </div>
                    <button
                      className="save-slot__delete"
                      onClick={(e) => handleDelete(e, slotId)}
                    >
                      ✕
                    </button>
                  </>
                ) : (
                  <div className="save-slot__empty-text">
                    {isSaveMode ? '点击保存' : '空'}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
