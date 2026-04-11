"""
SurrealDB 持久化层 — 嵌入式 + 文件落盘

数据模型（对应 architecture.md）：
  节点：character, location, event, world_rule
  边：关系类型动态创建（knows, enemy_of, occurs_at, participates_in, ...）
  版本：character_card_version（角色卡版本历史，供三时区切割）

  每个节点关联一个资产文件夹路径。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from surrealdb import AsyncSurreal, RecordID

logger = logging.getLogger(__name__)

# SurrealDB 嵌入式 (surrealkv) 单连接模式下可能出现的锁冲突
_RETRYABLE_KEYWORDS = ("locked", "busy", "timeout", "connection")
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5  # 秒，指数退避


async def _safe_query(db: AsyncSurreal, query: str, params: dict | None = None,
                      *, retries: int = _MAX_RETRIES, label: str = "") -> list:
    """带重试和错误处理的 SurrealDB 查询封装。

    - 可重试错误（锁冲突/超时）：指数退避重试
    - 不可重试错误：记日志 + 抛出
    """
    for attempt in range(retries + 1):
        try:
            return await db.query(query, params) if params else await db.query(query)
        except Exception as e:
            err_str = str(e).lower()
            is_retryable = any(kw in err_str for kw in _RETRYABLE_KEYWORDS)

            if is_retryable and attempt < retries:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"DB 查询可重试错误 [{label}] (第{attempt+1}次): {e}，{delay:.1f}s 后重试")
                await asyncio.sleep(delay)
                continue

            logger.error(f"DB 查询失败 [{label}]: {e}\n  Query: {query[:200]}\n  Params: {str(params)[:200] if params else 'None'}")
            raise
    return []  # unreachable


class NovelStore:
    """图数据库存储管理（嵌入式 SurrealKV，数据落盘）"""

    def __init__(self, db: AsyncSurreal, asset_root: Path):
        self.db = db
        self.asset_root = asset_root

    @classmethod
    async def create(
        cls,
        db_path: str | Path = "./data/novel.db",
        namespace: str = "novel2gal",
        database: str = "world",
        asset_root: str | Path = "./data/assets",
    ) -> "NovelStore":
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        asset_root = Path(asset_root)
        asset_root.mkdir(parents=True, exist_ok=True)

        db = AsyncSurreal(f"surrealkv://{db_path.resolve()}")
        await db.use(namespace, database)
        logger.info(f"SurrealDB 已连接: surrealkv://{db_path.resolve()}")
        logger.info(f"资产根目录: {asset_root.resolve()}")
        return cls(db=db, asset_root=asset_root)

    # ---- 角色 ----

    async def upsert_character(self, char_id: str, name: str, card: str, config: dict,
                                dialogues: list[str], memories: list[str], version: int) -> None:
        asset_dir = self.asset_root / f"character_{char_id}"
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "character_card.md").write_text(card, encoding="utf-8")
        (asset_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        await _safe_query(
            self.db,
            "UPSERT type::thing('character', $id) SET name=$name, card=$card, config=$config, "
            "example_dialogues=$dlg, initial_memories=$mem, card_version=$ver, asset_folder=$dir",
            {"id": char_id, "name": name, "card": card, "config": config,
             "dlg": dialogues, "mem": memories, "ver": version, "dir": str(asset_dir)},
            label=f"upsert_character:{name}",
        )
        logger.info(f"  角色写入: {name} (v{version})")

    async def save_card_version(self, char_id: str, version: int, data: dict) -> None:
        await _safe_query(
            self.db,
            "CREATE character_card_version SET char_id=$cid, version=$ver, data=$data",
            {"cid": char_id, "ver": version, "data": data},
            label=f"save_card_version:{char_id}:v{version}",
        )

    # ---- 地点 ----

    async def upsert_location(self, loc_id: str, name: str, description: str) -> None:
        asset_dir = self.asset_root / f"location_{loc_id}"
        asset_dir.mkdir(parents=True, exist_ok=True)

        await _safe_query(
            self.db,
            "UPSERT type::thing('location', $id) SET name=$name, description=$desc, asset_folder=$dir",
            {"id": loc_id, "name": name, "desc": description, "dir": str(asset_dir)},
            label=f"upsert_location:{name}",
        )
        logger.info(f"  地点写入: {name}")

    # ---- 事件 ----

    async def create_event(self, event_id: str, chunk_index: int, summary: str,
                           participants: list[str], location: str, significance: str) -> None:
        await _safe_query(
            self.db,
            "CREATE type::thing('event', $id) SET chunk_index=$ci, summary=$s, participants=$p, "
            "location=$loc, significance=$sig",
            {"id": event_id, "ci": chunk_index, "s": summary,
             "p": participants, "loc": location, "sig": significance},
            label=f"create_event:{event_id}",
        )
        for cid in participants:
            await _safe_query(
                self.db,
                "RELATE $f->participates_in->$t",
                {"f": RecordID("character", cid), "t": RecordID("event", event_id)},
                label=f"relate:participates_in:{cid}->{event_id}",
            )
        if location:
            await _safe_query(
                self.db,
                "RELATE $f->occurs_at->$t",
                {"f": RecordID("event", event_id), "t": RecordID("location", location)},
                label=f"relate:occurs_at:{event_id}->{location}",
            )

    # ---- 世界观规则 ----

    async def create_world_rule(self, rule_id: str, category: str, description: str) -> None:
        await _safe_query(
            self.db,
            "CREATE type::thing('world_rule', $id) SET category=$cat, description=$desc",
            {"id": rule_id, "cat": category, "desc": description},
            label=f"create_world_rule:{rule_id}",
        )
        logger.info(f"  规则写入: [{category}] {description[:40]}")

    # ---- 关系 ----

    async def create_relationship(self, from_id: str, to_id: str, rel_type: str, desc: str) -> None:
        import re
        # SurrealQL 关系名只允许 ASCII，中文/特殊字符统一用 "relates_to" + description 保存语义
        safe = rel_type.replace(" ", "_").replace("/", "_").lower()
        safe = re.sub(r'[^a-z0-9_]', '', safe)
        if not safe:
            safe = "relates_to"
        await _safe_query(
            self.db,
            f"RELATE $f->{safe}->$t SET description=$d, rel_label=$label",
            {"f": RecordID("character", from_id), "t": RecordID("character", to_id),
             "d": desc, "label": rel_type},
            label=f"relate:{from_id}-[{rel_type}]->{to_id}",
        )
        logger.info(f"  关系写入: {from_id} --[{rel_type}]--> {to_id}")

    # ---- 批量持久化 ----

    async def persist_parse_results(self, card_versions: dict, chunk_results: list, synthesis: dict) -> None:
        logger.info("开始持久化解析结果...")

        # 角色
        for cid, versions in card_versions.items():
            latest = versions[-1]
            cfg = latest.get("config", {})
            await self.upsert_character(
                cid, cfg.get("name", cid), latest.get("natural_language", ""),
                cfg, latest.get("example_dialogues", []), [], len(versions) - 1,
            )
            for i, v in enumerate(versions):
                await self.save_card_version(cid, i, v)

        # 地点（去重）
        seen_locs: set[str] = set()
        for cr in chunk_results:
            for loc in cr.locations:
                if loc["id"] not in seen_locs:
                    seen_locs.add(loc["id"])
                    await self.upsert_location(loc["id"], loc["name"], loc.get("description", ""))

        # 事件
        evt_n = 0
        for cr in chunk_results:
            for ev in cr.events:
                await self.create_event(
                    f"evt_{cr.chunk_index}_{evt_n}", cr.chunk_index,
                    ev.get("summary", ""), ev.get("participants", []),
                    ev.get("location", ""), ev.get("significance", "medium"),
                )
                evt_n += 1

        # 世界观规则
        for i, wr in enumerate(synthesis.get("world_rules", [])):
            await self.create_world_rule(wr.get("id", f"rule_{i}"), wr.get("category", ""), wr.get("description", ""))

        # 关系
        for rel in synthesis.get("relationships", []):
            await self.create_relationship(rel["from"], rel["to"], rel.get("type", "knows"), rel.get("description", ""))

        stats = await self.get_stats()
        logger.info(f"持久化完成: {stats}")

    # ---- 查询 ----

    async def get_stats(self) -> dict:
        def cnt(r): return r[0]["count"] if r and isinstance(r[0], dict) and "count" in r[0] else 0
        try:
            return {
                "characters": cnt(await _safe_query(self.db, "SELECT count() FROM character GROUP ALL", label="stats:character")),
                "locations": cnt(await _safe_query(self.db, "SELECT count() FROM location GROUP ALL", label="stats:location")),
                "events": cnt(await _safe_query(self.db, "SELECT count() FROM event GROUP ALL", label="stats:event")),
                "world_rules": cnt(await _safe_query(self.db, "SELECT count() FROM world_rule GROUP ALL", label="stats:world_rule")),
            }
        except Exception as e:
            logger.warning(f"get_stats 失败: {e}")
            return {"characters": 0, "locations": 0, "events": 0, "world_rules": 0}

    async def get_all_characters(self) -> list:
        chars = await _safe_query(self.db, "SELECT * FROM character", label="get_all_characters")
        for c in chars:
            if isinstance(c.get("config"), str):
                try:
                    c["config"] = json.loads(c["config"])
                except (ValueError, TypeError):
                    c["config"] = {}
        return chars

    async def get_all_locations(self) -> list:
        return await _safe_query(self.db, "SELECT * FROM location", label="get_all_locations")

    async def get_all_world_rules(self) -> list:
        return await _safe_query(self.db, "SELECT * FROM world_rule", label="get_all_world_rules")

    async def get_card_version(self, char_id: str, version: int) -> dict | None:
        r = await _safe_query(
            self.db,
            "SELECT data FROM character_card_version WHERE char_id=$cid AND version=$ver",
            {"cid": char_id, "ver": version},
            label=f"get_card_version:{char_id}:v{version}",
        )
        return r[0]["data"] if r else None
