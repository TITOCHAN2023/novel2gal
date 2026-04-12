"""
Novel2Gal 后端服务器

REST API:
  POST /api/stories/upload  — 上传 epub/txt，创建故事，启动流水线
  GET  /api/stories         — 列出所有故事
  GET  /api/stories/{id}    — 单个故事状态
  DELETE /api/stories/{id}  — 删除故事

WebSocket:
  /ws/debug  — 调试工作台 + 实时进度 + 场景推送
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Set

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parent))

import config
from config.logging_config import setup_logging
from stories.manager import StoryManager, StoryStats, StoryProgress, StorySettings

# 全局
DATA_DIR = Path(__file__).parent.parent / "data"
active_connections: Set[WebSocket] = set()
story_manager: StoryManager = None  # type: ignore


# ---- WebSocket 日志 Handler ----

class WebSocketLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        if not active_connections:
            return
        msg = {
            "type": "log",
            "level": record.levelname,
            "name": record.name,
            "message": self.format(record),
            "timestamp": record.created,
        }
        for ws in list(active_connections):
            try:
                asyncio.ensure_future(ws.send_json(msg))
            except Exception:
                pass


ws_handler = WebSocketLogHandler()
ws_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
ws_handler.setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global story_manager
    setup_logging(DATA_DIR / "logs")
    root = logging.getLogger()
    root.addHandler(ws_handler)

    story_manager = StoryManager(DATA_DIR)
    logger.info("Novel2Gal 后端启动")

    # 恢复中断的流水线
    interrupted = story_manager.get_interrupted_stories()
    if interrupted:
        logger.info(f"发现 {len(interrupted)} 个中断的故事，尝试恢复...")
        for sid in interrupted:
            upload_path = story_manager.get_upload_path(sid)
            if upload_path:
                story_manager.start_pipeline(sid, run_story_pipeline(sid))
                logger.info(f"  恢复流水线: {sid}")

    yield
    await story_manager.close_all_stores()
    logger.info("Novel2Gal 后端关闭")


app = FastAPI(title="Novel2Gal Backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

logger = logging.getLogger("server")


def _safe_task(coro, name: str = ""):
    """创建 asyncio task 并记录未捕获的异常（避免静默丢失）"""
    task = asyncio.create_task(coro)
    def _on_done(t: asyncio.Task):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error(f"后台任务异常 [{name}]: {exc}", exc_info=exc)
    task.add_done_callback(_on_done)
    return task


# ============================================================
# REST API — 故事管理
# ============================================================

@app.post("/api/stories/upload")
async def upload_story(file: UploadFile = File(...)):
    """上传 epub/txt 文件，创建故事（不自动启动流水线，等待配置）"""
    if not file.filename:
        raise HTTPException(400, "缺少文件名")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".epub", ".txt"):
        raise HTTPException(400, f"不支持的文件格式: {ext}，请上传 .epub 或 .txt")

    # 保存临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    # 创建故事（状态为 uploading，等待用户配置后启动）
    entry = story_manager.create_story(file.filename, tmp_path)
    tmp_path.unlink(missing_ok=True)

    return JSONResponse({
        "success": True,
        "story_id": entry.id,
        "title": entry.title,
        "status": entry.status,
    })


@app.post("/api/stories/{story_id}/configure")
async def configure_and_start(story_id: str, request: Request):
    """配置故事设置并启动流水线"""
    entry = story_manager.get_story(story_id)
    if not entry:
        raise HTTPException(404, "故事不存在")
    if entry.status == "ready":
        raise HTTPException(409, "故事已就绪，无需重新配置")
    if entry.status not in ("uploading", "error"):
        if story_manager.is_pipeline_running(story_id):
            raise HTTPException(409, "流水线已在运行")

    # 解析设置
    try:
        body = await request.json()
    except Exception:
        body = {}

    def safe_int(val, default: int) -> int:
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    settings = StorySettings(
        player_role=str(body.get("player_role", "")),
        initial_depth=max(1, min(10, safe_int(body.get("initial_depth"), 2))),
        gap=max(1, min(10, safe_int(body.get("gap"), 3))),
        max_branches=max(1, min(4, safe_int(body.get("max_branches"), 2))),
    )
    story_manager.update_story(story_id, settings=settings)

    # 启动流水线
    story_manager.start_pipeline(story_id, run_story_pipeline(story_id))

    return JSONResponse({
        "success": True,
        "story_id": story_id,
        "settings": settings.to_dict(),
    })


@app.get("/api/stories")
async def list_stories():
    """列出所有故事"""
    return JSONResponse({"stories": story_manager.list_stories()})


@app.get("/api/stories/{story_id}")
async def get_story(story_id: str):
    """获取单个故事状态"""
    entry = story_manager.get_story(story_id)
    if not entry:
        raise HTTPException(404, "故事不存在")
    return JSONResponse(entry.to_dict())


@app.post("/api/stories/{story_id}/refresh-assets")
async def refresh_story_assets(story_id: str):
    """刷新故事的资产 URL（为存量数据注入角色立绘和背景图路径）"""
    entry = story_manager.get_story(story_id)
    if not entry:
        raise HTTPException(404, "故事不存在")

    scenes_path = story_manager.story_scenes(story_id)
    if not scenes_path.exists():
        raise HTTPException(404, "场景文件不存在")

    from db.store import NovelStore
    from orchestrator.tree_generator import inject_asset_urls_standalone

    store = None
    try:
        store = await NovelStore.create(
            db_path=story_manager.story_db(story_id),
            namespace="novel2gal", database=story_id,
            asset_root=story_manager.story_assets(story_id),
        )

        # 加载场景
        scenes = json.loads(scenes_path.read_text(encoding="utf-8"))

        # 注入资产 URL（独立函数，不需要构造 TreeGenerator）
        await inject_asset_urls_standalone(store, scenes, story_id, scenes_path)

        # 统计注入结果
        bg_count = sum(1 for s in scenes.values() if s.get("background"))
        sprite_count = sum(
            1 for s in scenes.values()
            for c in (s.get("characters") or [])
            if c.get("sprite")
        )

        logger.info(f"[{story_id}] 资产 URL 刷新: {bg_count} 个背景, {sprite_count} 个立绘")
        return JSONResponse({
            "success": True,
            "backgrounds_injected": bg_count,
            "sprites_injected": sprite_count,
            "total_scenes": len(scenes),
        })
    except Exception as e:
        logger.error(f"[{story_id}] 资产刷新失败: {e}", exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        if store:
            await store.close()


@app.delete("/api/stories/{story_id}")
async def delete_story(story_id: str):
    """删除故事"""
    if story_manager.is_pipeline_running(story_id):
        raise HTTPException(409, "流水线运行中，无法删除")
    if not story_manager.delete_story(story_id):
        raise HTTPException(404, "故事不存在")
    return JSONResponse({"success": True})


@app.get("/api/tts/voices")
async def list_tts_voices():
    """列出当前 TTS Provider 可用的语音"""
    from assets.tts_provider import create_tts_provider
    provider = create_tts_provider()
    if not provider:
        return JSONResponse({"provider": None, "voices": []})
    return JSONResponse({
        "provider": provider.name,
        "voices": provider.list_voices(),
    })


# ============================================================
# 静态文件（按故事隔离的资产）
# ============================================================

# 通用资产路由：/assets/{story_id}/xxx
@app.get("/api/stories/{story_id}/graph")
async def get_story_graph(story_id: str):
    """获取故事的图结构数据（从 parse_cache.json 读取，不锁 DB）"""
    entry = story_manager.get_story(story_id)
    if not entry:
        raise HTTPException(404, "故事不存在")

    from pathlib import Path

    cache_path = story_manager.story_parse_cache(story_id)
    if not cache_path.exists():
        return JSONResponse({"nodes": [], "edges": []})

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    card_versions = cache.get("character_card_versions", {})
    chunk_results = cache.get("chunk_results", [])
    synthesis = cache.get("synthesis", {})
    assets_dir = story_manager.story_assets(story_id)

    nodes = []
    edges = []

    # 角色节点
    for cid, versions in card_versions.items():
        latest = versions[-1] if versions else {}
        cfg = latest.get("config", {})
        sprite_path = ""
        sprite_file = assets_dir / f"character_{cid}" / "base" / "sprite.png"
        if sprite_file.exists():
            sprite_path = f"/assets/{story_id}/character_{cid}/base/sprite.png"

        nodes.append({
            "id": f"char_{cid}",
            "label": cfg.get("name", cid),
            "type": "character",
            "traits": cfg.get("traits", []),
            "speech_style": cfg.get("speech_style", ""),
            "appearance": cfg.get("appearance_summary", ""),
            "identity": cfg.get("identity", ""),
            "card_version": len(versions),
            "sprite": sprite_path,
            "card_preview": (latest.get("natural_language", "") or "")[:300],
        })

    # 地点节点（从 chunk_results 去重）
    seen_locs = set()
    for cr in chunk_results:
        for loc in cr.get("locations", []):
            lid = loc.get("id", "")
            if lid and lid not in seen_locs:
                seen_locs.add(lid)
                bg_file = assets_dir / f"location_{lid}" / "base" / "background.png"
                bg_path = f"/assets/{story_id}/location_{lid}/base/background.png" if bg_file.exists() else ""
                nodes.append({
                    "id": f"loc_{lid}",
                    "label": loc.get("name", lid),
                    "type": "location",
                    "description": loc.get("description", ""),
                    "background": bg_path,
                })

    # 规则节点
    for r in synthesis.get("world_rules", []):
        nodes.append({
            "id": f"rule_{r.get('category', '').replace(' ', '_')}",
            "label": f"[{r.get('category', '')}]",
            "type": "rule",
            "description": r.get("description", ""),
        })

    # 关系边——从 synthesis 读取（不走 DB）
    for rel in synthesis.get("relationships", []):
        src = f"char_{rel.get('from', '')}"
        tgt = f"char_{rel.get('to', '')}"
        edges.append({
            "source": src,
            "target": tgt,
            "type": rel.get("type", "knows"),
            "label": rel.get("type", "knows").replace("_", " "),
            "description": rel.get("description", ""),
        })

    # 角色-事件关系（从 chunk_results）
    for cr in chunk_results:
        for ev in cr.get("events", []):
            for pid in ev.get("participants", []):
                if f"char_{pid}" in {n["id"] for n in nodes}:
                    edges.append({
                        "source": f"char_{pid}",
                        "target": f"loc_{ev.get('location', '')}",
                        "type": "appears_at",
                        "label": ev.get("summary", "")[:30],
                    })

    return JSONResponse({"nodes": nodes, "edges": edges})


@app.get("/api/stories/{story_id}/logs")
async def get_story_logs(story_id: str, lines: int = 50):
    """获取故事的最近 N 行日志（供前端调试面板备用）"""
    # 先查故事专属日志
    story_log = story_manager.story_dir(story_id) / "logs" / f"{story_id}.log"
    # 再查全局日志
    global_log = DATA_DIR / "logs" / "pipeline.log"

    log_file = story_log if story_log.exists() else global_log
    if not log_file.exists():
        return JSONResponse({"lines": []})

    all_lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    return JSONResponse({"lines": all_lines[-lines:]})


@app.get("/assets/bgm/{filename:path}")
async def serve_bgm(filename: str):
    """提供默认 BGM 文件"""
    bgm_dir = (DATA_DIR / "bgm").resolve()
    bgm_path = (bgm_dir / filename).resolve()
    if not str(bgm_path).startswith(str(bgm_dir)):
        raise HTTPException(403, "路径非法")
    if not bgm_path.exists():
        raise HTTPException(404)
    from fastapi.responses import FileResponse
    return FileResponse(bgm_path)


@app.get("/assets/{story_id}/{path:path}")
async def serve_asset(story_id: str, path: str):
    base_dir = story_manager.story_assets(story_id).resolve()
    asset_path = (base_dir / path).resolve()
    # 防止路径穿越攻击
    if not str(asset_path).startswith(str(base_dir)):
        raise HTTPException(403, "路径非法")
    if not asset_path.exists():
        raise HTTPException(404)
    from fastapi.responses import FileResponse
    return FileResponse(asset_path)


# ============================================================
# WebSocket — 调试工作台 + 实时通信
# ============================================================

@app.websocket("/ws/debug")
async def debug_websocket(ws: WebSocket):
    await ws.accept()
    active_connections.add(ws)
    bound_story: str | None = None
    logger.info(f"客户端已连接 (共 {len(active_connections)} 个)")

    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd")

            if cmd == "ping":
                await ws.send_json({"type": "pong"})

            elif cmd == "bind_story":
                story_id = data.get("story_id", "")
                entry = story_manager.get_story(story_id)
                if entry:
                    # 取消旧订阅
                    if bound_story:
                        story_manager.unsubscribe(bound_story, ws)
                    bound_story = story_id
                    story_manager.subscribe(story_id, ws)
                    await ws.send_json({
                        "type": "story_bound",
                        "story_id": story_id,
                        "status": entry.status,
                    })
                    # 如果已就绪或可玩，推送场景
                    if entry.status in ("ready", "playable"):
                        scenes_path = story_manager.story_scenes(story_id)
                        if scenes_path.exists() and scenes_path.stat().st_size > 10:
                            scenes = json.loads(scenes_path.read_text(encoding="utf-8"))
                            if scenes:
                                await ws.send_json({
                                    "type": "scenes_ready",
                                    "scenes": scenes,
                                    "firstScene": "scene_root",
                                })
                            else:
                                # 场景文件空——需要重新生成
                                logger.info(f"故事 {story_id} 场景为空，触发生成")
                                story_manager.start_pipeline(story_id, run_story_pipeline(story_id))
                                await ws.send_json({"type": "pipeline_progress", "story_id": story_id, "phase": 4, "phase_name": "正在编写第一章...", "detail": "自动触发", "percent": 0})
                        else:
                            # 没有场景文件——触发生成
                            logger.info(f"故事 {story_id} 无场景文件，触发生成")
                            story_manager.start_pipeline(story_id, run_story_pipeline(story_id))
                            await ws.send_json({"type": "pipeline_progress", "story_id": story_id, "phase": 4, "phase_name": "正在编写第一章...", "detail": "自动触发", "percent": 0})
                else:
                    await ws.send_json({"type": "error", "message": f"故事不存在: {story_id}"})

            elif cmd == "get_scenes":
                if bound_story:
                    scenes_path = story_manager.story_scenes(bound_story)
                    if scenes_path.exists():
                        scenes = json.loads(scenes_path.read_text(encoding="utf-8"))
                        await ws.send_json({"type": "scenes_ready", "scenes": scenes, "firstScene": "scene_root"})
                    else:
                        await ws.send_json({"type": "no_scenes"})
                else:
                    await ws.send_json({"type": "error", "message": "未绑定故事"})

            elif cmd == "player_choice":
                if bound_story:
                    _safe_task(handle_player_choice(ws, bound_story, data), "player_choice")

            elif cmd == "gap_pregenerate":
                if bound_story:
                    from_scene = data.get("from_scene", "")
                    gap_depth = data.get("gap_depth", 2)
                    if from_scene:
                        _safe_task(_handle_gap_pregenerate(ws, bound_story, from_scene, gap_depth), "gap_pregenerate")

            elif cmd == "get_status":
                await ws.send_json({
                    "type": "status",
                    "connections": len(active_connections),
                    "stories": len(story_manager.list_stories()),
                })

    except WebSocketDisconnect:
        if bound_story:
            story_manager.unsubscribe(bound_story, ws)
        active_connections.discard(ws)
        logger.info(f"客户端断开 (剩余 {len(active_connections)} 个)")


# ============================================================
# 流水线（解耦 WebSocket，按故事隔离）
# ============================================================

async def run_story_pipeline(story_id: str):
    """故事流水线——不绑定任何 WebSocket"""
    from config.llm_client import LLMClient
    from parser.epub_reader import read_epub
    from parser.chunker import chunk_novel
    from parser.novel_parser import NovelParser, ParseState, ChunkResult
    from db.store import NovelStore
    from assets.generator import generate_base_assets
    from orchestrator.player_setup import setup_player_character
    from orchestrator.tree_generator import TreeGenerator
    from orchestrator.three_zone import build_three_zone_context

    pl = logging.getLogger("pipeline")
    llm_url = config.LLM_BASE_URL
    llm_model = config.LLM_MODEL

    try:
        # ---- Phase 1: 阅读 ----
        story_manager.update_progress(story_id, 1, "正在阅读你的书...", "导入中", 0)

        upload_path = story_manager.get_upload_path(story_id)
        if not upload_path:
            story_manager.mark_error(story_id, "找不到上传文件")
            return

        chapters = read_epub(str(upload_path))
        all_chunks = []
        for ch in chapters:
            ch_chunks = chunk_novel(ch.text, max_chars=config.CHUNK_MAX_CHARS, overlap_chars=config.CHUNK_OVERLAP_CHARS)
            for c in ch_chunks:
                c.chapter = ch.index + 1
                c.chapter_title = f"{ch.title} (块{c.index})" if len(ch_chunks) > 1 else ch.title
            all_chunks.extend(ch_chunks)
        for i, c in enumerate(all_chunks):
            c.index = i

        story_manager.update_progress(story_id, 1, "正在阅读你的书...", f"{len(all_chunks)} 段", 100)
        pl.info(f"[{story_id}] 分块完成: {len(all_chunks)} 块")

        # ---- Phase 2: 理解 ----
        story_manager.update_progress(story_id, 2, "正在理解故事...", "开始解析", 0)

        cache_path = story_manager.story_parse_cache(story_id)
        state = ParseState()
        synthesis = None
        cached_chunk_count = 0

        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_chunk_count = cache.get("chunk_count", 0)

            # 恢复已有状态（无论是否有 synthesis）
            if cache.get("character_card_versions"):
                state.character_card_versions = cache["character_card_versions"]
            if cache.get("known_character_ids"):
                state.known_character_ids = cache["known_character_ids"]
            for cr_data in cache.get("chunk_results", []):
                state.chunk_results.append(ChunkResult(
                    chunk_index=cr_data["chunk_index"],
                    characters=cr_data.get("characters", []),
                    locations=cr_data.get("locations", []),
                    events=cr_data.get("events", []),
                    chapter_summary=cr_data.get("chapter_summary", ""),
                    dialogues=cr_data.get("dialogues", {}),
                ))

            if cache.get("synthesis"):
                synthesis = cache["synthesis"]
                pl.info(f"[{story_id}] 完整缓存命中 ({cached_chunk_count}/{len(all_chunks)} 块 + synthesis)")
            elif cached_chunk_count > 0:
                pl.info(f"[{story_id}] 断点恢复: 已有 {cached_chunk_count}/{len(all_chunks)} 块，从第 {cached_chunk_count+1} 块继续")

        if synthesis is None:
            async with LLMClient(base_url=llm_url, model=llm_model, timeout=300) as llm:
                parser = NovelParser(llm=llm)
                # 从断点继续（跳过已缓存的 chunks）
                for i, chunk in enumerate(all_chunks):
                    if i < cached_chunk_count:
                        continue  # 跳过已解析的
                    pct = int((i / len(all_chunks)) * 100)
                    story_manager.update_progress(story_id, 2, "正在理解故事...", f"第 {i+1}/{len(all_chunks)} 段", pct)
                    await parser.process_chunk(chunk, state)
                    # 断点缓存（含 known_character_ids）
                    _save_parse_cache(cache_path, state, i + 1, None)

                story_manager.update_progress(story_id, 2, "正在理解故事...", "综合分析中", 95)
                synthesis = await parser.synthesize(state)
                _save_parse_cache(cache_path, state, len(all_chunks), synthesis)

        story_manager.update_progress(story_id, 2, "正在理解故事...", "完成", 100)

        # ---- Phase 3: 创建世界（DB持久化 + 并行生图） ----
        story_manager.update_progress(story_id, 3, "正在创建世界...", "写入数据库", 0)

        store = await NovelStore.create(
            db_path=story_manager.story_db(story_id),
            namespace="novel2gal",
            database=story_id,
            asset_root=story_manager.story_assets(story_id),
        )
        await store.persist_parse_results(state.character_card_versions, state.chunk_results, synthesis)

        # epub 插图提取
        epub_images_dir = story_manager.story_dir(story_id) / "epub_images"
        try:
            from parser.epub_reader import extract_images
            extract_images(str(upload_path), epub_images_dir)
        except Exception as e:
            pl.warning(f"[{story_id}] epub 插图提取失败: {e}")
            epub_images_dir = None

        entry = story_manager.get_story(story_id)
        novel_title = entry.title if entry else "Unknown"

        # 目录结构创建（快速，不阻塞）
        await generate_base_assets(store, novel_title=novel_title, epub_images_dir=epub_images_dir)

        # 并行启动生图（不阻塞 Phase 4）
        image_task = None
        if config.ANYGEN_API_KEY:
            story_manager.update_progress(story_id, 3, "正在创建世界...", "生成角色立绘和场景背景（并行）", 60)
            from assets.image_generator import generate_all_assets as gen_images
            chars = await store.get_all_characters()
            locs = await store.get_all_locations()
            image_task = _safe_task(gen_images(
                asset_root=story_manager.story_assets(story_id),
                characters=chars, locations=locs,
                novel_title=novel_title, epub_images_dir=epub_images_dir,
                max_concurrent=config.IMAGE_MAX_CONCURRENT,
            ), "image_generation")
            pl.info(f"[{story_id}] 生图任务已启动（并行，不阻塞场景生成）")
        else:
            pl.info(f"[{story_id}] 无 ANYGEN_API_KEY，跳过生图")

        story_manager.update_progress(story_id, 3, "正在创建世界...", "完成", 100)

        # ---- Phase 4: 编写第一章（与生图并行） ----
        story_manager.update_progress(story_id, 4, "正在编写第一章...", "创建角色", 0)

        three_zone = build_three_zone_context(cache_path) if cache_path.exists() else None

        # 检查是否已有场景缓存（中断恢复）
        scenes_path = story_manager.story_scenes(story_id)
        engine_scenes = {}
        if scenes_path.exists() and scenes_path.stat().st_size > 10:
            try:
                engine_scenes = json.loads(scenes_path.read_text(encoding="utf-8"))
                if engine_scenes:
                    pl.info(f"[{story_id}] 已有 {len(engine_scenes)} 个缓存场景，跳过场景生成")
            except Exception:
                engine_scenes = {}

        if not engine_scenes:
            # ws_broadcast: 生成新场景时实时推送给订阅该故事的前端
            _playable_notified = False

            async def ws_broadcast(new_scenes: dict):
                nonlocal _playable_notified

                # 流式对话推送（__stream__ 标记）
                if new_scenes.get("__stream__"):
                    stream_msg = {
                        "type": "scene_lines_append",
                        "scene_id": new_scenes["scene_id"],
                        "lines": new_scenes["lines"],
                    }
                    for ws in list(story_manager._subscribers.get(story_id, [])):
                        try:
                            await ws.send_json(stream_msg)
                        except Exception:
                            pass
                    return

                msg = {"type": "scenes_ready", "scenes": new_scenes, "firstScene": None}
                for ws in list(story_manager._subscribers.get(story_id, [])):
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        pass

                # 分阶段解锁：scene_root 生成后立即标记为 playable
                if "scene_root" in new_scenes and not _playable_notified:
                    _playable_notified = True
                    story_manager.update_story(story_id, status="playable")
                    pl.info(f"[{story_id}] 第一个场景已生成，标记为 playable（后台继续生成）")
                    # 通知前端可以开始玩了
                    playable_msg = {
                        "type": "story_playable",
                        "story_id": story_id,
                        "scenes": new_scenes,
                        "firstScene": "scene_root",
                    }
                    for ws in list(story_manager._subscribers.get(story_id, [])):
                        try:
                            await ws.send_json(playable_msg)
                        except Exception:
                            pass

            # 读取故事设置
            entry_for_settings = story_manager.get_story(story_id)
            settings = entry_for_settings.settings if entry_for_settings else StorySettings()

            async with LLMClient(base_url=llm_url, model=llm_model, timeout=600) as llm:
                await setup_player_character(store, llm, settings.player_role)
                story_manager.update_progress(story_id, 4, "正在编写第一章...", "生成剧情树", 20)

                generator = TreeGenerator(
                    llm=llm, store=store, three_zone=three_zone,
                    initial_depth=settings.initial_depth,
                    max_branches_per_node=settings.max_branches,
                    scenes_path=scenes_path,
                    ws_broadcast=ws_broadcast,
                    story_id=story_id,
                )
                engine_scenes = await generator.generate_tree()

        # TTS 语音生成（并行，不阻塞）
        tts_task = None
        if config.TTS_ENABLED and engine_scenes:
            try:
                from assets.tts_generator import generate_all_scene_voices
                chars = await store.get_all_characters()
                tts_task = _safe_task(generate_all_scene_voices(
                    scenes=engine_scenes,
                    characters=chars,
                    asset_root=story_manager.story_assets(story_id),
                    max_concurrent=config.TTS_MAX_CONCURRENT,
                ), "tts_generation")
                pl.info(f"[{story_id}] TTS 任务已启动（并行）")
            except Exception as e:
                pl.warning(f"[{story_id}] TTS 启动失败: {e}")

        # 等待生图完成（如果还在跑）
        if image_task and not image_task.done():
            story_manager.update_progress(story_id, 4, "正在编写第一章...", "等待图片生成完成", 90)
            try:
                await asyncio.wait_for(image_task, timeout=600)
            except asyncio.TimeoutError:
                pl.warning(f"[{story_id}] 生图超时，跳过（后续增量补充）")
            except Exception as e:
                pl.warning(f"[{story_id}] 生图异常: {e}")

        # 等待 TTS 完成 + 注入语音 URL
        if tts_task:
            try:
                voice_results = await asyncio.wait_for(tts_task, timeout=300)
                if voice_results:
                    from assets.tts_generator import inject_voice_urls
                    inject_voice_urls(engine_scenes, voice_results)
                    # 保存更新后的场景（含语音 URL）
                    scenes_path.write_text(json.dumps(engine_scenes, ensure_ascii=False, indent=2))
            except asyncio.TimeoutError:
                pl.warning(f"[{story_id}] TTS 超时，后续增量补充")
            except Exception as e:
                pl.warning(f"[{story_id}] TTS 异常: {e}")

        # 更新统计+标记就绪
        stats = StoryStats(
            chapters=len(chapters),
            chunks=len(all_chunks),
            characters=len(state.character_card_versions),
            scenes=len(engine_scenes),
        )
        story_manager.mark_ready(story_id, stats)

        # 广播完成
        for ws in list(story_manager._subscribers.get(story_id, [])):
            try:
                await ws.send_json({"type": "pipeline_done", "story_id": story_id})
                await ws.send_json({"type": "scenes_ready", "scenes": engine_scenes, "firstScene": "scene_root"})
            except Exception:
                pass

        pl.info(f"[{story_id}] 流水线完成！{len(engine_scenes)} 个场景")

    except Exception as e:
        pl.error(f"[{story_id}] 流水线错误: {e}", exc_info=True)
        story_manager.mark_error(story_id, str(e))
    finally:
        # 确保关闭 DB 连接
        if 'store' in dir() and store:
            await store.close()


async def handle_player_choice(ws: WebSocket, story_id: str, data: dict):
    """处理玩家选择"""
    choice_text = data.get("choice_text", "")
    annotation = data.get("annotation", "")
    target_scene = data.get("target_scene", "")

    cl = logging.getLogger("player_choice")
    cl.info(f"[{story_id}] 选择: {choice_text}")
    if annotation:
        cl.info(f"  备注: {annotation}")

    # 更新玩家角色卡记忆
    try:
        store = await story_manager.get_store(story_id)
        memory_entry = f"做出了选择: {choice_text}"
        if annotation:
            memory_entry += f" (原因: {annotation})"
        chars = await store.get_all_characters()
        player = next((c for c in chars if c.get("is_player")), None)
        if player:
            pid = player.get("config", {}).get("id", "")
            await store.db.query(
                "UPDATE type::thing('character', $id) SET initial_memories += $mem",
                {"id": pid, "mem": memory_entry},
            )
    except Exception as e:
        cl.warning(f"  角色卡更新失败: {e}")

    # 检查目标场景是否存在
    scenes_path = story_manager.story_scenes(story_id)
    scenes = json.loads(scenes_path.read_text(encoding="utf-8")) if scenes_path.exists() else {}
    if target_scene not in scenes:
        cl.info(f"  目标场景不存在: {target_scene}，触发 Gap 生成")
        await ws.send_json({"type": "generating", "scene_id": target_scene})
        # 后台生成缺失的场景
        _safe_task(_gap_generate_scene(ws, story_id, scenes, target_scene), "gap_generate")


async def _gap_generate_scene(ws: WebSocket, story_id: str, existing_scenes: dict, target_scene: str):
    """Gap 生成——为缺失的目标场景生成内容"""
    gl = logging.getLogger("gap")
    gl.info(f"[{story_id}] Gap 生成: {target_scene}")
    try:
        from config.llm_client import LLMClient
        from db.store import NovelStore
        from orchestrator.super_agent import SuperAgent
        from orchestrator.three_zone import build_three_zone_context
        from agent.character_agent import CharacterAgent

        llm_url = config.LLM_BASE_URL
        llm_model = config.LLM_MODEL
        cache_path = story_manager.story_parse_cache(story_id)
        three_zone = build_three_zone_context(cache_path) if cache_path.exists() else None

        store = await story_manager.get_store(story_id)
        async with LLMClient(base_url=config.LLM_BASE_URL, model=config.LLM_MODEL, timeout=600) as llm:
            sa = SuperAgent(llm)

            # 加载角色 Agent
            chars = await store.get_all_characters()
            agents = {}
            for c in chars:
                cfg = c.get("config", {})
                cid = cfg.get("id", "")
                if cid:
                    agents[cid] = CharacterAgent(
                        char_id=cid, name=c["name"],
                        card=c.get("card", ""),
                        memories=c.get("initial_memories", []),
                    )

            # 规划+生成场景
            rules = await store.get_all_world_rules()
            locs = await store.get_all_locations()
            player = next((c for c in chars if c.get("is_player")), chars[0] if chars else {})

            plan = await sa.plan_scene(rules, chars, locs, player, "继续之前的剧情")
            result = await sa.generate_scene(target_scene, plan, agents)

        # 保存
        new_scene = result.to_engine_json()
        new_scene["depth"] = existing_scenes.get(target_scene.rsplit("_", 1)[0], {}).get("depth", 0) + 1
        existing_scenes[target_scene] = new_scene
        scenes_path = story_manager.story_scenes(story_id)
        scenes_path.write_text(json.dumps(existing_scenes, ensure_ascii=False, indent=2))

        # 推送到前端
        await ws.send_json({"type": "scenes_ready", "scenes": {target_scene: new_scene}})
        gl.info(f"[{story_id}] Gap 生成完成: {target_scene} ({len(result.lines)} 行)")

    except Exception as e:
        gl.error(f"[{story_id}] Gap 生成失败: {e}", exc_info=True)
        try:
            await ws.send_json({"type": "pipeline_error", "error": str(e)})
        except Exception:
            pass


async def _handle_gap_pregenerate(ws: WebSocket, story_id: str, from_scene: str, gap_depth: int):
    """主动 Gap 预生成——在玩家接近生成前沿时提前生成"""
    gl = logging.getLogger("gap")
    gl.info(f"[{story_id}] Gap 预生成: from={from_scene}, depth={gap_depth}")

    try:
        from config.llm_client import LLMClient
        from db.store import NovelStore
        from orchestrator.tree_generator import TreeGenerator
        from orchestrator.three_zone import build_three_zone_context

        llm_url = config.LLM_BASE_URL
        llm_model = config.LLM_MODEL
        cache_path = story_manager.story_parse_cache(story_id)
        three_zone = build_three_zone_context(cache_path) if cache_path.exists() else None
        scenes_path = story_manager.story_scenes(story_id)

        store = await story_manager.get_store(story_id)

        # ws_broadcast: 推新场景给前端
        async def ws_broadcast(new_scenes: dict):
            # 流式推送处理
            if new_scenes.get("__stream__"):
                stream_msg = {
                    "type": "scene_lines_append",
                    "scene_id": new_scenes["scene_id"],
                    "lines": new_scenes["lines"],
                }
                for sub_ws in list(story_manager._subscribers.get(story_id, [])):
                    try:
                        await sub_ws.send_json(stream_msg)
                    except Exception:
                        pass
                return
            msg = {"type": "scenes_ready", "scenes": new_scenes, "firstScene": None}
            for sub_ws in list(story_manager._subscribers.get(story_id, [])):
                try:
                    await sub_ws.send_json(msg)
                except Exception:
                    pass

        entry = story_manager.get_story(story_id)
        settings = entry.settings if entry else StorySettings()

        async with LLMClient(base_url=config.LLM_BASE_URL, model=config.LLM_MODEL, timeout=600) as llm:
            generator = TreeGenerator(
                llm=llm, store=store, three_zone=three_zone,
                initial_depth=gap_depth,
                max_branches_per_node=settings.max_branches,
                scenes_path=scenes_path,
                ws_broadcast=ws_broadcast,
                story_id=story_id,
            )
            new_scenes = await generator.generate_from_node(from_scene, depth=gap_depth)

        gl.info(f"[{story_id}] Gap 预生成完成: {len(new_scenes)} 个新场景")

    except Exception as e:
        gl.error(f"[{story_id}] Gap 预生成失败: {e}", exc_info=True)
        try:
            await ws.send_json({"type": "pipeline_error", "error": str(e)})
        except Exception:
            pass


def _save_parse_cache(cache_path: Path, state, chunk_count: int, synthesis):
    from parser.novel_parser import ParseState
    cache = {
        "chunk_count": chunk_count,
        "character_card_versions": state.character_card_versions,
        "known_character_ids": state.known_character_ids if hasattr(state, 'known_character_ids') else {},
        "chunk_results": [
            {"chunk_index": cr.chunk_index, "chapter_summary": cr.chapter_summary,
             "characters": cr.characters, "locations": cr.locations,
             "events": cr.events, "dialogues": cr.dialogues}
            for cr in state.chunk_results
        ],
        "synthesis": synthesis,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
