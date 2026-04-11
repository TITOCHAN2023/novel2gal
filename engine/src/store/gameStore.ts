import { create } from 'zustand';
import type {
  GameState,
  GameScript,
  Scene,
  ScriptLine,
  CharacterOnScreen,
  Choice,
  TransitionType,
  BacklogEntry,
  GameSettings,
  ScreenType,
  LineEffect,
  GenerationContext,
  ChoiceRecord,
} from '../engine/types';
import { DEFAULT_SETTINGS } from '../engine/types';
import { populateTreeMetadata, createTreeQuery } from '../engine/TreeManager';

interface GameActions {
  // 生命周期
  loadScript: (script: GameScript) => void;
  startGame: () => void;

  // === 热更新：运行时动态注入内容 ===
  injectScenes: (scenes: Record<string, Scene>) => void;
  appendLines: (sceneId: string, lines: ScriptLine[]) => void;
  patchScene: (sceneId: string, patch: Partial<Pick<Scene, 'choices' | 'nextScene' | 'bgm' | 'background' | 'characters'>>) => void;

  // === 树查询（暴露给后端调度器） ===
  getGenerationFrontier: (gap: number) => GenerationContext[];
  getPathToRoot: (sceneId: string) => string[];
  getChildren: (sceneId: string) => string[];
  getSubtreeDepth: (sceneId: string) => number;

  // 场景导航
  goToScene: (sceneId: string, transition?: TransitionType) => void;
  setTransitioning: (v: boolean) => void;

  // 对话推进
  advanceLine: () => void;
  completeText: () => void;
  setDisplayedText: (text: string) => void;
  setTextComplete: (v: boolean) => void;

  // 选项
  /** 选择选项（annotation 为右键备注，可选） */
  selectChoice: (choice: Choice, annotation?: string) => void;
  /** 玩家的选择历史记录 */
  choiceHistory: ChoiceRecord[];

  // 角色管理
  setCharacters: (chars: CharacterOnScreen[]) => void;

  // 背景 / 音频
  setBackground: (bg: string) => void;
  setBgm: (bgm: string) => void;

  // UI 屏幕切换
  setScreen: (screen: ScreenType) => void;
  toggleBacklog: () => void;
  toggleAutoPlay: () => void;

  // 设置
  updateSettings: (patch: Partial<GameSettings>) => void;

  // 存档辅助
  getSnapshot: () => {
    sceneId: string;
    lineIndex: number;
    playPath: string[];
    preview: string;
    playTime: number;
  };
  restoreFromSave: (sceneId: string, lineIndex: number, playPath: string[]) => void;

  // 计时
  addPlayTime: (ms: number) => void;

  // 处理行效果
  applyEffects: (effects: LineEffect[]) => void;
}

type GameStore = GameState & GameActions;

function getCurrentScene(state: GameState): Scene | null {
  return state.script?.scenes[state.currentSceneId] ?? null;
}

function getCurrentLine(state: GameState): ScriptLine | null {
  const scene = getCurrentScene(state);
  if (!scene) return null;
  return scene.lines[state.currentLineIndex] ?? null;
}

export const useGameStore = create<GameStore>((set, get) => ({
  // ---- initial state ----
  screen: 'launcher',
  script: null,
  currentSceneId: '',
  currentLineIndex: 0,
  playPath: [],
  currentDepth: 0,
  showingChoices: false,
  characters: [],
  background: '',
  bgm: '',
  backlog: [],
  autoPlay: false,
  showBacklog: false,
  transition: 'none',
  isTransitioning: false,
  settings: { ...DEFAULT_SETTINGS },
  playTime: 0,
  displayedText: '',
  textComplete: false,
  waitingForContent: false,
  choiceHistory: [],

  // ---- actions ----

  loadScript: (script) => {
    populateTreeMetadata(script);
    set({ script });
  },

  startGame: () => {
    const { script } = get();
    if (!script) return;
    set({ screen: 'game', playTime: 0, backlog: [], playPath: [], currentDepth: 0 });
    get().goToScene(script.firstScene);
  },

  // === 热更新 ===

  injectScenes: (scenes) => {
    const { script } = get();
    if (!script) return;

    // 为新场景填充树元数据
    for (const [id, scene] of Object.entries(scenes)) {
      if (scene.parentId && script.scenes[scene.parentId]) {
        scene.depth = (script.scenes[scene.parentId].depth ?? 0) + 1;
      }
      scenes[id] = scene;
    }

    const merged = { ...script.scenes, ...scenes };
    set({ script: { ...script, scenes: merged } });

    // 如果正在等待，检查等待的场景是否已注入
    const state = get();
    if (state.waitingForContent) {
      const currentScene = merged[state.currentSceneId];
      if (!currentScene) return;

      // 检查 nextScene
      if (currentScene.nextScene && merged[currentScene.nextScene]) {
        set({ waitingForContent: false });
        get().goToScene(currentScene.nextScene);
        return;
      }
      // 检查 choices 的 targetScene
      if (currentScene.choices) {
        const allExist = currentScene.choices.every(
          (c) => merged[c.targetScene]
        );
        if (allExist) {
          set({ waitingForContent: false, showingChoices: true });
        }
      }
    }
  },

  appendLines: (sceneId, lines) => {
    const { script } = get();
    if (!script) return;
    const scene = script.scenes[sceneId];
    if (!scene) return;
    const updated: Scene = { ...scene, lines: [...scene.lines, ...lines] };
    set({
      script: { ...script, scenes: { ...script.scenes, [sceneId]: updated } },
    });
  },

  patchScene: (sceneId, patch) => {
    const { script } = get();
    if (!script) return;
    const scene = script.scenes[sceneId];
    if (!scene) return;
    const updated: Scene = { ...scene, ...patch };
    set({
      script: { ...script, scenes: { ...script.scenes, [sceneId]: updated } },
    });
  },

  // === 树查询 ===

  getGenerationFrontier: (gap) => {
    const { script, currentSceneId } = get();
    if (!script) return [];
    const tree = createTreeQuery(script);
    const playerDepth = script.scenes[currentSceneId]?.depth ?? 0;
    const targetDepth = playerDepth + gap;
    const frontier: GenerationContext[] = [];

    function walk(sceneId: string) {
      const scene = script!.scenes[sceneId];
      if (!scene) return;
      const children = tree.getChildren(sceneId);
      const depth = scene.depth ?? 0;

      if (children.length === 0 && depth < targetDepth) {
        frontier.push({
          leafSceneId: sceneId,
          pathFromRoot: tree.getPathToRoot(sceneId),
          depth,
        });
      } else {
        for (const child of children) {
          walk(child);
        }
      }
    }

    // 只遍历玩家当前节点的子树
    walk(currentSceneId);
    return frontier;
  },

  getPathToRoot: (sceneId) => {
    const { script } = get();
    if (!script) return [];
    return createTreeQuery(script).getPathToRoot(sceneId);
  },

  getChildren: (sceneId) => {
    const { script } = get();
    if (!script) return [];
    return createTreeQuery(script).getChildren(sceneId);
  },

  getSubtreeDepth: (sceneId) => {
    const { script } = get();
    if (!script) return 0;
    return createTreeQuery(script).getSubtreeDepth(sceneId);
  },

  // === 场景导航（树感知） ===

  goToScene: (sceneId, transition = 'fade') => {
    const { script } = get();
    if (!script) return;
    const scene = script.scenes[sceneId];
    if (!scene) return;

    const effectiveTransition = scene.transition ?? transition;
    const firstLine = scene.lines[0];
    const depth = scene.depth ?? 0;

    // 更新 playPath：追加新节点
    set((s) => ({
      currentSceneId: sceneId,
      currentLineIndex: 0,
      playPath: [...s.playPath, sceneId],
      currentDepth: depth,
      showingChoices: false,
      background: scene.background ?? s.background,
      bgm: scene.bgm ?? s.bgm,
      characters: scene.characters ?? s.characters,
      transition: effectiveTransition,
      isTransitioning: effectiveTransition !== 'none',
      displayedText: '',
      textComplete: false,
      waitingForContent: false,
    }));

    // 应用第一行的效果并记入 backlog
    if (firstLine) {
      if (firstLine.effects) {
        get().applyEffects(firstLine.effects);
      }
      if (firstLine.type === 'dialogue' && firstLine.character) {
        set((s) => ({
          characters: s.characters.map((c) => ({
            ...c,
            isActive: c.name === firstLine.character,
          })),
        }));
      }
      const entry: BacklogEntry = {
        type: firstLine.type,
        character: firstLine.character,
        text: firstLine.text,
        sceneId,
      };
      set((s) => ({ backlog: [...s.backlog, entry] }));
    }
  },

  setTransitioning: (v) => set({ isTransitioning: v }),

  advanceLine: () => {
    const state = get();
    if (state.isTransitioning) return;

    if (!state.textComplete) {
      get().completeText();
      return;
    }

    const scene = getCurrentScene(state);
    if (!scene) return;

    const nextIndex = state.currentLineIndex + 1;

    // 场景内还有对话
    if (nextIndex < scene.lines.length) {
      const nextLine = scene.lines[nextIndex];

      if (nextLine.effects) {
        get().applyEffects(nextLine.effects);
      }

      // 更新活跃角色 + 根据 emotion/outfit 切换立绘
      const emotion = (nextLine as { emotion?: string }).emotion || '';
      const intensity = (nextLine as { emotion_intensity?: number }).emotion_intensity || 5;
      const outfit = (nextLine as { outfit?: string }).outfit || '';

      const updatedChars = get().characters.map((c) => {
        const isSpeaking = nextLine.type === 'dialogue' && c.name === nextLine.character;
        // 如果是说话角色且有 emotion 信息，构造对应的 sprite 路径
        let sprite = c.sprite;
        if (isSpeaking && emotion && c.id) {
          // 资产池路径：character_{id}/outfit_{outfit}/emotion/{emotion}_{intensity}.png
          // 如果精确路径不存在，fallback 到基础立绘
          const outfitDir = outfit && outfit !== 'default' ? `outfit_${outfit}` : 'outfit_default';
          sprite = `/assets/${c.id}/${outfitDir}/emotion/${emotion}_${intensity}.png`;
          // 注意：这个路径可能不存在（资产池按需生成），前端 img onerror 会 fallback
        }
        return { ...c, isActive: isSpeaking, sprite: sprite || c.sprite };
      });

      const entry: BacklogEntry = {
        type: nextLine.type,
        character: nextLine.character,
        text: nextLine.text,
        sceneId: state.currentSceneId,
      };

      set({
        currentLineIndex: nextIndex,
        characters: updatedChars,
        backlog: [...state.backlog, entry],
        displayedText: '',
        textComplete: false,
      });
      return;
    }

    // 场景对话已读完
    if (scene.choices && scene.choices.length > 0) {
      // 检查选项目标场景是否都已生成
      const { script } = get();
      const allExist = scene.choices.every(
        (c) => script?.scenes[c.targetScene]
      );
      if (allExist) {
        set({ showingChoices: true });
      } else {
        set({ waitingForContent: true });
      }
      return;
    }

    // 无选项，自动跳转下一场景
    if (scene.nextScene) {
      const { script } = get();
      if (script?.scenes[scene.nextScene]) {
        get().goToScene(scene.nextScene);
      } else {
        set({ waitingForContent: true });
      }
    }
  },

  completeText: () => {
    const state = get();
    const line = getCurrentLine(state);
    if (!line) return;
    set({ displayedText: line.text, textComplete: true });
  },

  setDisplayedText: (text) => set({ displayedText: text }),
  setTextComplete: (v) => set({ textComplete: v }),

  selectChoice: (choice, annotation?) => {
    if (choice.effects) {
      get().applyEffects(choice.effects);
    }

    // 记录选择历史（含备注）
    const record: ChoiceRecord = {
      choiceText: choice.text,
      sceneId: get().currentSceneId,
      annotation,
      timestamp: Date.now(),
    };

    const backlogText = annotation
      ? `▸ ${choice.text}（${annotation}）`
      : `▸ ${choice.text}`;

    const entry: BacklogEntry = {
      type: 'narration',
      text: backlogText,
      sceneId: get().currentSceneId,
    };
    set((s) => ({
      backlog: [...s.backlog, entry],
      choiceHistory: [...s.choiceHistory, record],
      showingChoices: false,
    }));

    // 如果目标场景存在，跳转；否则等待
    const { script } = get();
    if (script?.scenes[choice.targetScene]) {
      get().goToScene(choice.targetScene);
    } else {
      set({ waitingForContent: true });
    }
  },

  setCharacters: (chars) => set({ characters: chars }),
  setBackground: (bg) => set({ background: bg }),
  setBgm: (bgm) => set({ bgm }),

  setScreen: (screen) => set({ screen }),
  toggleBacklog: () => set((s) => ({ showBacklog: !s.showBacklog })),
  toggleAutoPlay: () => set((s) => ({ autoPlay: !s.autoPlay })),

  updateSettings: (patch) =>
    set((s) => ({ settings: { ...s.settings, ...patch } })),

  // === 存档（树感知） ===

  getSnapshot: () => {
    const s = get();
    const line = getCurrentLine(s);
    return {
      sceneId: s.currentSceneId,
      lineIndex: s.currentLineIndex,
      playPath: [...s.playPath],
      preview: line?.text ?? '',
      playTime: s.playTime,
    };
  },

  restoreFromSave: (sceneId, lineIndex, playPath) => {
    const { script } = get();
    if (!script) return;
    const scene = script.scenes[sceneId];
    if (!scene) return;

    // 读档：恢复到树上的那个位置
    // 树上之前生成过的所有分支都还在，不需要清理
    set({
      screen: 'game',
      currentSceneId: sceneId,
      currentLineIndex: lineIndex,
      playPath,
      currentDepth: scene.depth ?? 0,
      showingChoices: false,
      background: scene.background ?? '',
      bgm: scene.bgm ?? '',
      characters: scene.characters ?? [],
      displayedText: '',
      textComplete: false,
      isTransitioning: false,
      waitingForContent: false,
      // backlog 从 playPath 重建（简化：读档后清空，从当前位置开始记录）
      backlog: [],
    });
  },

  addPlayTime: (ms) => set((s) => ({ playTime: s.playTime + ms })),

  applyEffects: (effects) => {
    for (const effect of effects) {
      switch (effect.type) {
        case 'change_background':
          set({ background: effect.payload.src as string });
          break;
        case 'play_bgm':
          set({ bgm: effect.payload.src as string });
          break;
        case 'stop_bgm':
          set({ bgm: '' });
          break;
        case 'show_character': {
          const char = effect.payload as unknown as CharacterOnScreen;
          set((s) => ({
            characters: [...s.characters.filter((c) => c.id !== char.id), char],
          }));
          break;
        }
        case 'hide_character': {
          const id = effect.payload.id as string;
          set((s) => ({
            characters: s.characters.filter((c) => c.id !== id),
          }));
          break;
        }
        case 'change_sprite': {
          const { id, sprite } = effect.payload as { id: string; sprite: string };
          set((s) => ({
            characters: s.characters.map((c) =>
              c.id === id ? { ...c, sprite } : c
            ),
          }));
          break;
        }
        case 'move_character': {
          const { id, position } = effect.payload as {
            id: string;
            position: CharacterOnScreen['position'];
          };
          set((s) => ({
            characters: s.characters.map((c) =>
              c.id === id ? { ...c, position } : c
            ),
          }));
          break;
        }
        default:
          break;
      }
    }
  },
}));
