import type { GameScript, GenerationContext, TreeQuery } from './types';

/**
 * 剧情树管理器
 *
 * 将扁平的 scenes map 视为一棵树进行查询。
 * 树的拓扑关系由 Scene.parentId / Scene.choices / Scene.nextScene 隐式定义。
 */
export function createTreeQuery(script: GameScript): TreeQuery {
  const { scenes } = script;

  /** 获取一个场景的所有直接子场景 ID */
  function getChildren(sceneId: string): string[] {
    const scene = scenes[sceneId];
    if (!scene) return [];
    const children: string[] = [];
    if (scene.choices) {
      for (const c of scene.choices) {
        if (scenes[c.targetScene]) children.push(c.targetScene);
      }
    } else if (scene.nextScene && scenes[scene.nextScene]) {
      children.push(scene.nextScene);
    }
    return children;
  }

  /** 获取从根到指定节点的路径（通过 parentId 回溯，含循环检测） */
  function getPathToRoot(sceneId: string): string[] {
    const path: string[] = [];
    const visited = new Set<string>();
    let current: string | undefined | null = sceneId;
    while (current && scenes[current] && !visited.has(current)) {
      visited.add(current);
      path.unshift(current);
      current = scenes[current].parentId;
    }
    return path;
  }

  /** 获取场景的深度 */
  function getDepth(sceneId: string): number {
    const d = scenes[sceneId]?.depth;
    if (d !== undefined && d !== null) return d;
    const path = getPathToRoot(sceneId);
    return path.length > 0 ? path.length - 1 : 0;
  }

  /** 获取以某节点为根的子树最大深度（相对于该节点，含循环检测） */
  function getSubtreeDepth(sceneId: string, visited?: Set<string>): number {
    const seen = visited ?? new Set<string>();
    if (seen.has(sceneId)) return 0; // 循环检测
    seen.add(sceneId);
    const children = getChildren(sceneId);
    if (children.length === 0) return 0;
    let max = 0;
    for (const child of children) {
      max = Math.max(max, 1 + getSubtreeDepth(child, seen));
    }
    return max;
  }

  /**
   * 获取生成前沿——玩家当前位置的子树中，需要继续生成子节点的叶子
   *
   * 算法：
   * 1. 从玩家当前节点开始，向下遍历子树
   * 2. 找到所有叶子节点（没有子节点的场景）
   * 3. 如果叶子的深度 < 玩家深度 + gap，说明 Gap 不足，需要为该叶子生成子节点
   */
  function getGenerationFrontier(
    playerSceneId: string,
    gap: number
  ): GenerationContext[] {
    const playerDepth = getDepth(playerSceneId);
    const targetDepth = playerDepth + gap;
    const frontier: GenerationContext[] = [];

    function walk(sceneId: string) {
      const children = getChildren(sceneId);
      const depth = getDepth(sceneId);

      if (children.length === 0 && depth < targetDepth) {
        // 这是一个需要继续生成的叶子
        frontier.push({
          leafSceneId: sceneId,
          pathFromRoot: getPathToRoot(sceneId),
          depth,
        });
      } else {
        for (const child of children) {
          walk(child);
        }
      }
    }

    walk(playerSceneId);
    return frontier;
  }

  return {
    getGenerationFrontier: (gap: number) => {
      // 需要外部传入 playerSceneId，这里做一个 curried 版本
      // 实际调用时通过 store 包装
      return getGenerationFrontier(script.firstScene, gap);
    },
    getPathToRoot,
    getChildren,
    getSubtreeDepth,
  };
}

/**
 * 自动填充树元数据（depth, parentId）
 *
 * 对 script.scenes 进行一次 BFS 遍历，
 * 从 firstScene 出发，填充每个 scene 的 depth 和 parentId。
 * 用于从扁平脚本构建树结构。
 */
export function populateTreeMetadata(script: GameScript): void {
  const { scenes, firstScene } = script;
  const root = scenes[firstScene];
  if (!root) return;

  root.depth = 0;
  root.parentId = null;

  const queue: string[] = [firstScene];
  const visited = new Set<string>([firstScene]);

  while (queue.length > 0) {
    const id = queue.shift()!;
    const scene = scenes[id];
    const parentDepth = scene.depth ?? 0;

    // 收集子节点
    const childIds: string[] = [];
    if (scene.choices) {
      for (const c of scene.choices) {
        childIds.push(c.targetScene);
      }
    } else if (scene.nextScene) {
      childIds.push(scene.nextScene);
    }

    for (const childId of childIds) {
      if (visited.has(childId) || !scenes[childId]) continue;
      visited.add(childId);
      scenes[childId].depth = parentDepth + 1;
      scenes[childId].parentId = id;
      queue.push(childId);
    }
  }
}
