"""
剧情树生成器 — 步骤7（可中断续接版）

核心设计：
  - 每生成一个场景节点，立即写入 engine_scenes.json
  - 任何时候中断（Ctrl+C / 崩溃 / 断电），重启后自动续接
  - 续接时跳过已生成的节点，从缺失的子节点继续
  - _story_summary 字段保存在场景 JSON 中，续接时恢复上下文

  generate_tree()       → 初始化：从 scene_root 开始，生成到 initial_depth
  generate_from_node()  → Gap 运行时：从指定节点开始，向下生成 depth 层
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

try:
    from ..config.llm_client import LLMClient
    from ..db.store import NovelStore
    from ..agent.character_agent import CharacterAgent
    from .super_agent import SuperAgent, SceneResult
    from .three_zone import ThreeZoneContext, get_character_context, build_super_agent_context
except ImportError:
    from config.llm_client import LLMClient
    from db.store import NovelStore
    from agent.character_agent import CharacterAgent
    from orchestrator.super_agent import SuperAgent, SceneResult
    from orchestrator.three_zone import ThreeZoneContext, get_character_context, build_super_agent_context

logger = logging.getLogger(__name__)


@dataclass
class TreeNode:
    """剧情树的一个节点"""
    scene_id: str
    depth: int
    parent_id: str | None = None
    scene_result: SceneResult | None = None
    children: list["TreeNode"] = field(default_factory=list)
    choice_text: str = ""


class TreeGenerator:
    """剧情树生成器 — 支持增量持久化+中断续接"""

    def __init__(
        self,
        llm: LLMClient,
        store: NovelStore,
        three_zone: ThreeZoneContext | None = None,
        initial_depth: int = 5,
        max_branches_per_node: int = 2,
        scenes_path: Path | None = None,
        ws_broadcast=None,
        story_id: str = "",
    ):
        self.llm = llm
        self.store = store
        self.three_zone = three_zone
        self.super_agent = SuperAgent(llm)
        self.initial_depth = initial_depth
        self.max_branches = max_branches_per_node
        self.scenes_path = scenes_path
        self.ws_broadcast = ws_broadcast  # async callable: push new scenes to frontend
        self.story_id = story_id
        self.character_agents: dict[str, CharacterAgent] = {}
        self.engine_scenes: dict[str, dict] = {}
        self._new_scenes: dict[str, dict] = {}  # 本次运行新生成的

    # ---- 持久化 ----

    def _load_existing(self) -> None:
        """从磁盘加载已有场景（中断续接）"""
        if self.scenes_path and self.scenes_path.exists():
            try:
                self.engine_scenes = json.loads(self.scenes_path.read_text(encoding="utf-8"))
                logger.info(f"加载已有场景缓存: {len(self.engine_scenes)} 个节点")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"场景缓存读取失败: {e}，将重新生成")
                self.engine_scenes = {}
        else:
            self.engine_scenes = {}

    def _persist(self) -> None:
        """把当前所有场景写入磁盘（每生成一个节点调用一次）"""
        if self.scenes_path:
            self.scenes_path.parent.mkdir(parents=True, exist_ok=True)
            self.scenes_path.write_text(
                json.dumps(self.engine_scenes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _save_node(self, node: TreeNode, story_summary: str) -> dict:
        """将一个生成完成的节点转为引擎 JSON，保存并返回"""
        scene_json = node.scene_result.to_engine_json()
        scene_json["depth"] = node.depth
        scene_json["parentId"] = node.parent_id
        scene_json["_story_summary"] = story_summary  # 续接用

        # 修正 choices 的 targetScene
        if node.scene_result.choices:
            for i, choice in enumerate(node.scene_result.choices[:self.max_branches]):
                child_id = f"{node.scene_id}_c{i}"
                if i < len(scene_json.get("choices", [])):
                    scene_json["choices"][i]["targetScene"] = child_id

        self.engine_scenes[node.scene_id] = scene_json
        self._new_scenes[node.scene_id] = scene_json
        self._persist()
        return scene_json

    # ---- 角色加载 ----

    async def _load_character_agents(self) -> None:
        """从图数据库+三时区上下文加载角色 Agent"""
        characters = await self.store.get_all_characters()
        for char in characters:
            config = char.get("config", {})
            if isinstance(config, str):
                import json as _json
                try:
                    config = _json.loads(config)
                except (ValueError, TypeError):
                    config = {}
            cid = config.get("id", "") if isinstance(config, dict) else ""
            if not cid:
                continue

            if self.three_zone:
                char_ctx = get_character_context(self.three_zone, cid)
                card = char_ctx["card"] or char.get("card", "")
                memories = char_ctx["memories"]
                dialogues = char_ctx["example_dialogues"] or char.get("example_dialogues", [])
                is_future = char_ctx["is_future"]
                if is_future:
                    logger.info(f"  角色 {char['name']}: 潜在未来区（无记忆）")
                else:
                    logger.info(f"  角色 {char['name']}: 已发生区（{len(memories)} 条记忆）")
            else:
                card = char.get("card", "")
                memories = char.get("initial_memories", [])
                dialogues = char.get("example_dialogues", [])

            self.character_agents[cid] = CharacterAgent(
                char_id=cid,
                name=char["name"],
                card=card,
                memories=memories,
                state={},
                relationships=char.get("config", {}).get("social", {}),
                example_dialogues=dialogues,
            )
        logger.info(f"加载了 {len(self.character_agents)} 个角色 Agent")

    # ---- 单节点生成 ----

    async def _generate_node(
        self,
        scene_id: str,
        depth: int,
        parent_id: str | None,
        choice_text: str,
        story_so_far: str,
    ) -> TreeNode:
        """生成一个场景节点"""
        node = TreeNode(
            scene_id=scene_id,
            depth=depth,
            parent_id=parent_id,
            choice_text=choice_text,
        )

        world_rules = await self.store.get_all_world_rules()
        characters = await self.store.get_all_characters()
        locations = await self.store.get_all_locations()

        player_chars = [c for c in characters if c.get("is_player")]
        player_info = player_chars[0] if player_chars else characters[0] if characters else {}

        world_context = ""
        if self.three_zone:
            world_context = build_super_agent_context(self.three_zone)

        enriched_story = story_so_far
        if choice_text:
            enriched_story += f"\n玩家选择了: {choice_text}"
        if world_context:
            enriched_story = f"{world_context}\n\n## 之前的剧情\n{enriched_story}"

        plan = await self.super_agent.plan_scene(
            world_rules=world_rules,
            available_characters=characters,
            available_locations=locations,
            player_info=player_info,
            story_so_far=enriched_story,
        )

        scene_result = await self.super_agent.generate_scene(
            scene_id=scene_id,
            scene_plan=plan,
            character_agents=self.character_agents,
        )

        node.scene_result = scene_result
        return node

    # ---- 递归生成核心 ----

    async def _generate_recursive(
        self,
        scene_id: str,
        depth: int,
        max_depth: int,
        parent_id: str | None,
        choice_text: str,
        story_so_far: str,
    ) -> None:
        """递归生成场景树——已有节点跳过，缺失节点生成"""
        if depth > max_depth:
            return

        # ---- 续接：节点已存在 → 跳过，但递归检查子节点 ----
        if scene_id in self.engine_scenes:
            existing = self.engine_scenes[scene_id]
            logger.info(f"跳过已有场景: {scene_id} (深度 {depth})")
            current_story = existing.get("_story_summary", story_so_far)

            choices = existing.get("choices") or []
            for i, choice in enumerate(choices[:self.max_branches]):
                child_id = choice.get("targetScene", f"{scene_id}_c{i}")
                await self._generate_recursive(
                    child_id, depth + 1, max_depth, scene_id,
                    choice.get("text", ""),
                    current_story,
                )
            return

        # ---- 新生成 ----
        logger.info(f"生成节点: {scene_id} (深度 {depth}/{max_depth})")
        node = await self._generate_node(
            scene_id, depth, parent_id, choice_text, story_so_far,
        )

        # 构建剧情摘要
        scene_summary = ""
        if node.scene_result:
            lines = [
                f"{l.character}: {l.text}" if l.character else l.text
                for l in node.scene_result.lines[:5]
            ]
            scene_summary = f"场景{scene_id}: " + " ".join(lines)[:200]
        current_story = story_so_far + "\n" + scene_summary

        # 保存（立即持久化）
        self._save_node(node, current_story)
        logger.info(f"  已保存: {scene_id} (累计 {len(self.engine_scenes)} 个)")

        # 推送给前端（如果有 ws_broadcast）
        if self.ws_broadcast:
            try:
                await self.ws_broadcast({scene_id: self.engine_scenes[scene_id]})
            except Exception:
                pass

        # 递归子节点
        if node.scene_result and node.scene_result.choices:
            for i, choice in enumerate(node.scene_result.choices[:self.max_branches]):
                child_id = f"{scene_id}_c{i}"
                await self._generate_recursive(
                    child_id, depth + 1, max_depth, scene_id,
                    choice.get("text", ""),
                    current_story,
                )

    # ---- 公开接口 ----

    async def generate_tree(self) -> dict[str, dict]:
        """
        初始化生成：从 scene_root 到 initial_depth。
        自动续接——已有节点跳过，缺失节点补全。

        Returns: 所有场景（含已有的 + 本次新增的）
        """
        logger.info(f"=== 树预生成 (depth={self.initial_depth}, branches={self.max_branches}) ===")

        self._load_existing()
        self._new_scenes = {}

        await self._load_character_agents()
        if not self.character_agents:
            logger.error("没有可用的角色 Agent，无法生成")
            return self.engine_scenes

        await self._generate_recursive(
            "scene_root", 0, self.initial_depth, None, "", "",
        )

        # 后处理：注入资产 URL（角色名 → 立绘路径）
        await self._inject_asset_urls(self._new_scenes)

        logger.info(f"树生成完成: 总计 {len(self.engine_scenes)} 个, 本次新增 {len(self._new_scenes)} 个")
        return self.engine_scenes

    async def _inject_asset_urls(self, scenes: dict[str, dict]) -> None:
        """将角色名映射到资产 URL，注入到场景 JSON 中"""
        # 构建 name → id 映射
        chars = await self.store.get_all_characters()
        name_to_id: dict[str, str] = {}
        for c in chars:
            cfg = c.get("config", {})
            cid = cfg.get("id", "")
            name = c.get("name", "")
            if cid and name:
                name_to_id[name] = cid

        story_prefix = f"/assets/{self.story_id}" if self.story_id else "/assets"

        for scene in scenes.values():
            # 更新 characters 的 sprite 路径
            for char in (scene.get("characters") or []):
                cname = char.get("name", "")
                if cname in name_to_id:
                    cid = name_to_id[cname]
                    char["id"] = cid
                    # 检查基础立绘是否存在
                    sprite_path = self.store.asset_root / f"character_{cid}" / "base" / "sprite.png"
                    if sprite_path.exists():
                        char["sprite"] = f"{story_prefix}/character_{cid}/base/sprite.png"

    async def generate_from_node(
        self,
        from_scene_id: str,
        depth: int = 2,
    ) -> dict[str, dict]:
        """
        Gap 运行时生成：从指定节点向下生成 depth 层。
        用于玩家推进时补充前方场景。

        Returns: 本次新生成的场景
        """
        logger.info(f"=== Gap 生成: from={from_scene_id}, depth={depth} ===")

        self._load_existing()
        self._new_scenes = {}

        # 确认起始节点存在
        if from_scene_id not in self.engine_scenes:
            logger.error(f"起始节点不存在: {from_scene_id}")
            return {}

        await self._load_character_agents()
        if not self.character_agents:
            logger.error("没有可用的角色 Agent，无法生成")
            return {}

        existing = self.engine_scenes[from_scene_id]
        from_depth = existing.get("depth", 0)
        story_so_far = existing.get("_story_summary", "")

        # 如果没有 _story_summary，从对话重建
        if not story_so_far:
            lines = existing.get("lines", [])
            parts = [
                f"{l.get('character', '')}: {l.get('text', '')}" if l.get("character") else l.get("text", "")
                for l in lines[:5]
            ]
            story_so_far = " ".join(parts)[:300]

        # 从起始节点的每个 choice 向下生成
        choices = existing.get("choices") or []
        max_target_depth = from_depth + depth

        for i, choice in enumerate(choices[:self.max_branches]):
            child_id = choice.get("targetScene", f"{from_scene_id}_c{i}")
            await self._generate_recursive(
                child_id, from_depth + 1, max_target_depth, from_scene_id,
                choice.get("text", ""),
                story_so_far,
            )

        logger.info(f"Gap 生成完成: 新增 {len(self._new_scenes)} 个场景")
        return self._new_scenes
