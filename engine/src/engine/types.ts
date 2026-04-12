// ============================================================
// Novel2Gal VN Engine — Core Type Definitions
// ============================================================

/** 角色在屏幕上的站位 */
export type CharacterPosition = 'left' | 'center' | 'right';

/** 角色当前显示状态 */
export interface CharacterOnScreen {
  id: string;
  name: string;
  sprite: string;        // 立绘图片路径
  position: CharacterPosition;
  isActive: boolean;     // 当前是否在说话（高亮）
  flipped: boolean;      // 是否水平翻转
}

/** 对话行的类型 */
export type LineType = 'dialogue' | 'narration' | 'thought';

/** 单条对话/旁白/内心独白 */
export interface ScriptLine {
  type: LineType;
  character?: string;     // dialogue 时必填，narration 时为空
  text: string;
  /** 角色当前情绪（驱动立绘切换） */
  emotion?: string;       // happy/sad/angry/surprised/worried/excited/shy/neutral
  /** 情绪强度 1-10（对应资产池索引） */
  emotion_intensity?: number;
  /** 角色当前着装（对应资产池索引） */
  outfit?: string;
  /** 语音文件路径（TTS 生成） */
  voice?: string;
  /** 该行显示时对角色和场景的即时变更 */
  effects?: LineEffect[];
}

/** 一条对话行附带的即时效果 */
export interface LineEffect {
  type: 'show_character' | 'hide_character' | 'move_character'
      | 'change_background' | 'play_bgm' | 'stop_bgm'
      | 'play_sfx' | 'screen_shake' | 'change_sprite';
  payload: Record<string, unknown>;
}

/** 选项 */
export interface Choice {
  text: string;
  /** 选择后跳转到的 sceneId */
  targetScene: string;
  /** 选择后的即时效果（状态变更等） */
  effects?: LineEffect[];
}

/** 玩家做出的选择记录（含可选备注） */
export interface ChoiceRecord {
  /** 选择的文本 */
  choiceText: string;
  /** 所在场景 */
  sceneId: string;
  /** 玩家的备注（右键选择时填写的"为什么选这个"） */
  annotation?: string;
  /** 时间戳 */
  timestamp: number;
}

/** 场景转场类型 */
export type TransitionType = 'fade' | 'dissolve' | 'blackout' | 'none';

/** 一个场景（章节中的一段连续叙事，也是剧情树上的一个节点） */
export interface Scene {
  id: string;
  background?: string;          // 背景图路径
  bgm?: string;                 // 背景音乐
  transition?: TransitionType;  // 进入本场景时的转场效果
  /** 场景开始时在屏的角色 */
  characters?: CharacterOnScreen[];
  /** 对话序列 */
  lines: ScriptLine[];
  /** 对话结束后的选项（没有则自动跳转 nextScene） */
  choices?: Choice[];
  /** 无选项时自动跳转的下一个场景 */
  nextScene?: string;

  // ---- 树结构元数据 ----
  /** 在剧情树中的深度（根节点 = 0） */
  depth?: number;
  /** 父场景 ID（根节点为 null） */
  parentId?: string | null;
}

/** 完整的游戏脚本（一局游戏的所有场景） */
export interface GameScript {
  title: string;
  author?: string;
  firstScene: string;
  scenes: Record<string, Scene>;
}

// ============================================================
// 存档相关
// ============================================================

export interface SaveSlot {
  id: number;
  timestamp: number;
  sceneId: string;
  lineIndex: number;
  /** 从根到当前场景的完整路径 */
  playPath: string[];
  preview: string;          // 最后一句对话文本作为预览
  screenshotDataUrl?: string;
  playTimeMs: number;
}

// ============================================================
// 设置
// ============================================================

export interface GameSettings {
  textSpeed: number;        // 逐字显示速度 (ms per char)，0 = 即时
  autoPlayDelay: number;    // 自动播放间隔 (ms)
  bgmVolume: number;        // 0-1
  sfxVolume: number;        // 0-1
  voiceVolume: number;      // 0-1
  fullscreen: boolean;
  gap: number;              // Gap 预生成缓冲层数
}

export const DEFAULT_SETTINGS: GameSettings = {
  textSpeed: 30,
  autoPlayDelay: 2000,
  bgmVolume: 0.7,
  sfxVolume: 0.8,
  voiceVolume: 0.8,
  fullscreen: false,
  gap: 3,
};

// ============================================================
// 对话回溯 (Backlog)
// ============================================================

export interface BacklogEntry {
  type: LineType;
  character?: string;
  text: string;
  sceneId: string;
}

// ============================================================
// 游戏全局状态（Store 用）
// ============================================================

export type ScreenType = 'launcher' | 'setup' | 'title' | 'game' | 'save' | 'load' | 'settings';

export interface GameState {
  /** 当前所在屏 */
  screen: ScreenType;
  /** 已加载的游戏脚本 */
  script: GameScript | null;
  /** 当前场景 ID */
  currentSceneId: string;
  /** 当前对话行索引 */
  currentLineIndex: number;
  /** 从根到当前场景的完整路径（剧情树上的位置） */
  playPath: string[];
  /** 当前玩家在树中的深度 */
  currentDepth: number;
  /** 是否正在显示选项 */
  showingChoices: boolean;
  /** 当前屏幕上的角色 */
  characters: CharacterOnScreen[];
  /** 当前背景图 */
  background: string;
  /** 当前 BGM */
  bgm: string;
  /** 对话回溯记录 */
  backlog: BacklogEntry[];
  /** 是否自动播放中 */
  autoPlay: boolean;
  /** 是否显示 backlog 面板 */
  showBacklog: boolean;
  /** 当前转场状态 */
  transition: TransitionType;
  isTransitioning: boolean;
  /** 设置 */
  settings: GameSettings;
  /** 游玩时间 (ms) */
  playTime: number;
  /** 当前显示中的文本（打字机效果用） */
  displayedText: string;
  /** 当前行的完整文本是否已显示完毕 */
  textComplete: boolean;
  /** 是否正在等待后端生成后续内容 */
  waitingForContent: boolean;
}

// ============================================================
// 剧情树查询
// ============================================================

/** 后端请求生成时需要的上下文 */
export interface GenerationContext {
  /** 需要生成子节点的叶子场景 ID */
  leafSceneId: string;
  /** 从根到该叶子的完整路径 */
  pathFromRoot: string[];
  /** 叶子的深度 */
  depth: number;
}

/** 引擎暴露给后端调度器的树查询接口 */
export interface TreeQuery {
  /** 获取玩家当前子树的叶子节点（需要继续生成的前沿） */
  getGenerationFrontier: (gap: number) => GenerationContext[];
  /** 获取某个场景到根的完整路径 */
  getPathToRoot: (sceneId: string) => string[];
  /** 获取某个场景的所有子场景 ID */
  getChildren: (sceneId: string) => string[];
  /** 获取以某节点为根的子树最大深度 */
  getSubtreeDepth: (sceneId: string) => number;
}
