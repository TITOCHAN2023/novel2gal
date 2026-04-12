"""
StoryManager — 多故事生命周期管理

职责：
  - 故事注册表 CRUD（stories.json）
  - 按 story_id 隔离数据目录
  - 流水线启动/进度/恢复（解耦 WebSocket）
  - 上传文件管理
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Literal

logger = logging.getLogger(__name__)

StoryStatus = Literal["uploading", "parsing", "generating", "playable", "ready", "error", "queued"]


@dataclass
class StoryProgress:
    phase: int = 0
    phase_name: str = ""
    detail: str = ""
    percent: int = 0


@dataclass
class StoryStats:
    chapters: int = 0
    chunks: int = 0
    characters: int = 0
    scenes: int = 0


@dataclass
class StorySettings:
    """玩家在创建故事时的配置"""
    player_role: str = ""          # 玩家角色名/ID（空=默认旅人）
    initial_depth: int = 2         # 初始树深度
    gap: int = 3                   # Gap 预生成距离
    max_branches: int = 2          # 每个节点最大分支数

    def to_dict(self) -> dict:
        return {
            "player_role": self.player_role,
            "initial_depth": self.initial_depth,
            "gap": self.gap,
            "max_branches": self.max_branches,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StorySettings":
        return cls(
            player_role=d.get("player_role", ""),
            initial_depth=d.get("initial_depth", 2),
            gap=d.get("gap", 3),
            max_branches=d.get("max_branches", 2),
        )


@dataclass
class StoryEntry:
    id: str = ""
    title: str = ""
    author: str = ""
    filename: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: StoryStatus = "uploading"
    progress: StoryProgress = field(default_factory=StoryProgress)
    error: str | None = None
    stats: StoryStats = field(default_factory=StoryStats)
    settings: StorySettings = field(default_factory=StorySettings)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StoryEntry":
        prog = d.get("progress", {})
        stats = d.get("stats", {})
        settings = d.get("settings", {})
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            author=d.get("author", ""),
            filename=d.get("filename", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            status=d.get("status", "uploading"),
            progress=StoryProgress(**prog) if isinstance(prog, dict) else StoryProgress(),
            error=d.get("error"),
            stats=StoryStats(**stats) if isinstance(stats, dict) else StoryStats(),
            settings=StorySettings.from_dict(settings) if isinstance(settings, dict) else StorySettings(),
        )


class StoryManager:
    """多故事管理器"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.registry_path = data_dir / "stories.json"
        self.uploads_dir = data_dir / "uploads"
        self.stories_dir = data_dir / "stories"
        # DB 连接缓存（避免反复创建/关闭）
        self._store_cache: dict[str, "NovelStore"] = {}  # {story_id: NovelStore}
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.stories_dir.mkdir(parents=True, exist_ok=True)

        # 运行中的流水线任务
        self._running_tasks: dict[str, asyncio.Task] = {}
        # 进度订阅者（WebSocket 连接）
        self._subscribers: dict[str, set] = {}  # {story_id: set of ws}

    # ---- 注册表 ----

    def _load_registry(self) -> dict[str, StoryEntry]:
        if self.registry_path.exists():
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return {k: StoryEntry.from_dict(v) for k, v in data.items()}
        return {}

    def _save_registry(self, registry: dict[str, StoryEntry]):
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps({k: v.to_dict() for k, v in registry.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_stories(self) -> list[dict]:
        return [v.to_dict() for v in self._load_registry().values()]

    def get_story(self, story_id: str) -> StoryEntry | None:
        return self._load_registry().get(story_id)

    def update_story(self, story_id: str, **kwargs) -> StoryEntry | None:
        reg = self._load_registry()
        entry = reg.get(story_id)
        if not entry:
            return None
        for k, v in kwargs.items():
            if hasattr(entry, k):
                setattr(entry, k, v)
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        reg[story_id] = entry
        self._save_registry(reg)
        return entry

    def delete_story(self, story_id: str) -> bool:
        reg = self._load_registry()
        if story_id not in reg:
            return False
        # 停止运行中的流水线
        if story_id in self._running_tasks:
            self._running_tasks[story_id].cancel()
            del self._running_tasks[story_id]
        # 删除数据
        story_dir = self.stories_dir / story_id
        if story_dir.exists():
            shutil.rmtree(story_dir)
        upload_files = list(self.uploads_dir.glob(f"{story_id}.*"))
        for f in upload_files:
            f.unlink()
        del reg[story_id]
        self._save_registry(reg)
        logger.info(f"已删除故事: {story_id}")
        return True

    # ---- DB 连接管理 ----

    async def get_store(self, story_id: str) -> "NovelStore":
        """获取故事的 DB 连接（缓存复用，避免反复创建）"""
        if story_id in self._store_cache:
            return self._store_cache[story_id]

        from db.store import NovelStore
        store = await NovelStore.create(
            db_path=self.story_db(story_id),
            namespace="novel2gal",
            database=story_id,
            asset_root=self.story_assets(story_id),
        )
        self._store_cache[story_id] = store
        return store

    async def close_store(self, story_id: str) -> None:
        """关闭并移除缓存的 DB 连接"""
        store = self._store_cache.pop(story_id, None)
        if store:
            await store.close()

    async def close_all_stores(self) -> None:
        """关闭所有缓存的 DB 连接"""
        for store in self._store_cache.values():
            await store.close()
        self._store_cache.clear()

    # ---- 路径解析 ----

    def story_dir(self, story_id: str) -> Path:
        d = self.stories_dir / story_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def story_parse_cache(self, story_id: str) -> Path:
        return self.story_dir(story_id) / "parse_cache.json"

    def story_scenes(self, story_id: str) -> Path:
        return self.story_dir(story_id) / "engine_scenes.json"

    def story_db(self, story_id: str) -> Path:
        return self.story_dir(story_id) / "novel.db"

    def story_assets(self, story_id: str) -> Path:
        d = self.story_dir(story_id) / "assets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def story_logs(self, story_id: str) -> Path:
        d = self.story_dir(story_id) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- 创建故事 ----

    def create_story(self, filename: str, file_path: Path) -> StoryEntry:
        story_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        # 从文件名提取标题
        title = Path(filename).stem.replace("+", " ").replace("_", " ")

        entry = StoryEntry(
            id=story_id,
            title=title,
            author="",
            filename=filename,
            created_at=now,
            updated_at=now,
            status="uploading",
        )

        # 保存上传文件
        ext = Path(filename).suffix
        upload_path = self.uploads_dir / f"{story_id}{ext}"
        shutil.copy2(file_path, upload_path)

        # 注册
        reg = self._load_registry()
        reg[story_id] = entry
        self._save_registry(reg)

        logger.info(f"新故事: {story_id} — {title} ({filename})")
        return entry

    def get_upload_path(self, story_id: str) -> Path | None:
        for f in self.uploads_dir.iterdir():
            if f.stem == story_id:
                return f
        return None

    # ---- 进度管理 ----

    def update_progress(self, story_id: str, phase: int, phase_name: str, detail: str = "", percent: int = 0):
        progress = StoryProgress(phase=phase, phase_name=phase_name, detail=detail, percent=percent)

        # 映射 phase 到 status（但不覆盖 playable）
        current = self.get_story(story_id)
        if current and current.status == "playable":
            # 已标记可玩，只更新进度不改状态
            self.update_story(story_id, progress=progress, error=None)
        else:
            status_map = {1: "parsing", 2: "parsing", 3: "generating", 4: "generating"}
            status = status_map.get(phase, "generating")
            self.update_story(story_id, status=status, progress=progress, error=None)

        # 广播给订阅者
        asyncio.ensure_future(self._broadcast_progress(story_id, progress))

    def mark_ready(self, story_id: str, stats: StoryStats | None = None):
        kwargs: dict = {"status": "ready", "error": None}
        kwargs["progress"] = StoryProgress(phase=4, phase_name="完成", detail="", percent=100)
        if stats:
            kwargs["stats"] = stats
        self.update_story(story_id, **kwargs)
        logger.info(f"故事就绪: {story_id}")

    def mark_error(self, story_id: str, error: str):
        self.update_story(story_id, status="error", error=error)
        logger.error(f"故事错误 [{story_id}]: {error}")

    # ---- 订阅/广播 ----

    def subscribe(self, story_id: str, ws):
        self._subscribers.setdefault(story_id, set()).add(ws)

    def unsubscribe(self, story_id: str, ws):
        if story_id in self._subscribers:
            self._subscribers[story_id].discard(ws)

    async def _broadcast_progress(self, story_id: str, progress: StoryProgress):
        msg = {
            "type": "pipeline_progress",
            "story_id": story_id,
            "phase": progress.phase,
            "phase_name": progress.phase_name,
            "detail": progress.detail,
            "percent": progress.percent,
        }
        for ws in list(self._subscribers.get(story_id, [])):
            try:
                await ws.send_json(msg)
            except Exception:
                self._subscribers[story_id].discard(ws)

    # ---- 流水线 ----

    def is_pipeline_running(self, story_id: str) -> bool:
        task = self._running_tasks.get(story_id)
        return task is not None and not task.done()

    def has_active_pipeline(self) -> bool:
        return any(not t.done() for t in self._running_tasks.values())

    def start_pipeline(self, story_id: str, coro):
        """启动流水线（不绑定 WebSocket）"""
        if self.is_pipeline_running(story_id):
            logger.warning(f"流水线已在运行: {story_id}")
            return
        task = asyncio.create_task(coro)
        self._running_tasks[story_id] = task
        task.add_done_callback(lambda _: self._running_tasks.pop(story_id, None))

    # ---- 启动恢复 ----

    def get_interrupted_stories(self) -> list[str]:
        """找到状态为 parsing/generating 的故事（服务器重启后需要恢复）
        注意：uploading 表示等待用户配置，不应自动恢复"""
        reg = self._load_registry()
        return [
            sid for sid, entry in reg.items()
            if entry.status in ("parsing", "generating")
        ]
