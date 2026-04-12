"""
图片生成模块 — 用 AnyGen API 生成角色立绘 + 场景背景图

流程：
  角色立绘：AnyGen ai_designer → 白底角色图 → 抠白底 → 透明 PNG
  场景背景：AnyGen ai_designer → 16:9 背景图 → 直接保存
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import subprocess
import os
from pathlib import Path

from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

def _get_api_key() -> str:
    """运行时动态获取 API key（支持 .env 延迟加载）"""
    return os.environ.get("ANYGEN_API_KEY", "")


def _anygen_cmd(args: list[str]) -> dict:
    """执行 anygen CLI 命令（健壮 JSON 提取）"""
    env = {**os.environ, "ANYGEN_API_KEY": _get_api_key()}
    result = subprocess.run(
        ["anygen"] + args,
        capture_output=True, text=True, env=env, timeout=300,
    )
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()

    if result.returncode != 0:
        # 检查是否是 rate limit
        combined = out + err
        if "rate limit" in combined.lower():
            raise RuntimeError(f"rate limit exceeded")
        raise RuntimeError(f"anygen error (code {result.returncode}): {err or out}")

    # 健壮提取 JSON：跳过 spinner/进度行，找最后一个完整 JSON 对象
    last_json = None
    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                last_json = json.loads(line)
            except json.JSONDecodeError:
                continue
    if last_json:
        return last_json

    # 尝试从整体输出找 JSON
    start = out.rfind("{")
    if start >= 0:
        try:
            return json.loads(out[start:])
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"anygen: 无法提取 JSON: {out[:200]}")


async def _anygen_create_and_download(prompt: str, output_path: Path, file_tokens: list[str] | None = None) -> Path | None:
    """创建 AnyGen 任务 → 等待完成 → 下载第一张图（含速率控制）

    所有阻塞操作通过 asyncio.to_thread 在线程池运行，不阻塞事件循环。
    """
    logger.info(f"  AnyGen 创建任务...")
    task_data: dict = {"operation": "ai_designer", "prompt": prompt}
    if file_tokens:
        task_data["file_tokens"] = file_tokens

    # 速率控制：创建任务前等 2 秒（避免 rate limit）
    await asyncio.sleep(2)

    try:
        create_result = await asyncio.to_thread(
            _anygen_cmd, ["task", "create", "--data", json.dumps(task_data)]
        )
    except RuntimeError as e:
        if "rate limit" in str(e).lower():
            logger.warning("  AnyGen rate limit，等 30 秒后重试...")
            await asyncio.sleep(30)
            create_result = await asyncio.to_thread(
                _anygen_cmd, ["task", "create", "--data", json.dumps(task_data)]
            )
        else:
            raise
    task_id = create_result.get("task_id")
    if not task_id:
        logger.error(f"  创建任务失败: {create_result}")
        return None

    logger.info(f"  任务ID: {task_id}，等待完成...")

    # 等待完成（在线程池运行，避免阻塞事件循环）
    env = {**os.environ, "ANYGEN_API_KEY": _get_api_key()}
    get_result = await asyncio.to_thread(
        subprocess.run,
        ["anygen", "task", "get", "--params", json.dumps({"task_id": task_id}), "--wait", "--timeout", "120000"],
        capture_output=True, text=True, env=env, timeout=180,
    )
    # 解析结果——task get --wait 输出有 spinner 行 + 多行 JSON
    out = get_result.stdout or ""
    result_data = None

    # 找到输出中最大的 JSON 对象（从第一个 { 到匹配的最后一个 }）
    brace_start = out.find("{")
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(out)):
            if out[i] == "{":
                depth += 1
            elif out[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result_data = json.loads(out[brace_start:i + 1])
                    except json.JSONDecodeError:
                        pass
                    break

    if not result_data or result_data.get("status") != "completed":
        logger.error(f"  任务未完成或解析失败: {out[-300:]}")
        return None

    # 下载第一张图
    files = result_data.get("output", {}).get("files", [])
    if not files:
        logger.error("  没有生成文件")
        return None

    url = files[0]["url"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dl = await asyncio.to_thread(
        subprocess.run,
        ["curl", "-sL", "-o", str(output_path), url],
        capture_output=True, timeout=60,
    )
    if dl.returncode != 0 or not output_path.exists():
        logger.error(f"  下载失败: {url}")
        return None

    logger.info(f"  已保存: {output_path} ({output_path.stat().st_size // 1024}KB)")
    return output_path


def remove_white_bg(img: Image.Image, max_diff: int = 15) -> Image.Image:
    """抠白/黑底——自动判断底色"""
    arr = np.array(img.convert("RGBA"))
    h, w = arr.shape[:2]
    corners = [arr[0, 0, :3], arr[0, w-1, :3], arr[h-1, 0, :3], arr[h-1, w-1, :3]]
    brightness = np.mean(np.mean(corners, axis=0))

    bg_color = np.array([255, 255, 255]) if brightness > 200 else np.array([0, 0, 0]) if brightness < 55 else np.array([255, 255, 255])
    logger.debug(f"  底色亮度={brightness:.0f}, 抠{'白' if brightness > 200 else '黑' if brightness < 55 else '白(默认)'}")

    rgb = arr[:, :, :3].astype(np.int16)
    mask = np.all(np.abs(rgb - bg_color) <= max_diff, axis=2)
    arr[mask, 3] = 0
    return Image.fromarray(arr)


async def _upload_reference_image(file_path: Path) -> str | None:
    """上传参考图到 AnyGen，返回 file_token"""
    try:
        env = {**os.environ, "ANYGEN_API_KEY": _get_api_key()}
        result = await asyncio.to_thread(
            subprocess.run,
            ["curl", "-s", "-X", "POST", "https://api.anygen.io/v1/openapi/files/upload",
             "-H", f"Authorization: Bearer {_get_api_key()}",
             "-F", f"file=@{file_path}",
             "-F", f"filename={file_path.name}"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("success"):
            token = data.get("file_token", "")
            logger.info(f"  参考图上传成功: {file_path.name} → {token[:20]}...")
            return token
        else:
            logger.warning(f"  参考图上传失败: {data.get('error', '')}")
            return None
    except Exception as e:
        logger.warning(f"  参考图上传异常: {e}")
        return None


async def generate_character_sprite(
    name: str, appearance: str, output_path: Path,
    novel_title: str = "Overlord",
    reference_image: Path | None = None,
    art_prompt: str = "",
) -> Path | None:
    """生成角色立绘（透明 PNG）— 优先使用 SuperAgent 生成的 art_prompt"""
    logger.info(f"生成角色立绘: {name}")

    if art_prompt:
        # 使用 SuperAgent 美术导演生成的高质量 prompt
        prompt = art_prompt
    else:
        # fallback：基础 prompt
        prompt = (
            f"Search online for the character '{name}' from the light novel '{novel_title}'. "
            f"Anime style character illustration, full body standing pose, white background, high quality. "
            f"Character details: {appearance}"
        )

    # 如果有参考图，上传获取 token
    file_tokens = []
    if reference_image and reference_image.exists():
        token = await _upload_reference_image(reference_image)
        if token:
            file_tokens.append(token)

    raw_path = output_path.with_suffix(".raw.jpeg")
    result = await _anygen_create_and_download(prompt, raw_path, file_tokens or None)
    if not result:
        return None

    # 抠底
    img = Image.open(raw_path).convert("RGBA")
    img = remove_white_bg(img)
    img.save(output_path, "PNG")
    raw_path.unlink(missing_ok=True)
    logger.info(f"  抠图完成: {output_path}")
    return output_path


async def generate_scene_background(
    name: str, description: str, output_path: Path,
    novel_title: str = "Overlord",
    reference_image: Path | None = None,
    art_prompt: str = "",
) -> Path | None:
    """生成场景背景图 — 优先使用 SuperAgent 生成的 art_prompt"""
    logger.info(f"生成场景背景: {name}")

    if art_prompt:
        prompt = art_prompt
    else:
        prompt = (
            f"Search online for locations from '{novel_title}' light novel. "
            f"Anime background art: {name}. {description}. "
            f"Wide scenic shot, no characters, atmospheric lighting, 16:9 aspect ratio."
        )

    file_tokens = []
    if reference_image and reference_image.exists():
        token = await _upload_reference_image(reference_image)
        if token:
            file_tokens.append(token)

    result = await _anygen_create_and_download(prompt, output_path, file_tokens or None)
    return result


async def generate_all_assets(
    asset_root: Path,
    characters: list[dict],
    locations: list[dict],
    novel_title: str = "Overlord",
    epub_images_dir: Path | None = None,
    max_concurrent: int = 8,
) -> dict:
    """
    批量并发生成所有角色立绘和场景背景

    Args:
        epub_images_dir: epub 提取的原书插图目录
        max_concurrent: 最大并行数（默认 4）
    """
    import asyncio
    results: dict[str, str] = {}
    logger.info(f"=== 图片资产批量生成 ({len(characters)} 角色, {len(locations)} 地点, 并行={max_concurrent}) ===")

    style_ref = None
    if epub_images_dir and epub_images_dir.exists():
        candidates = list(epub_images_dir.glob("*.jpg")) + list(epub_images_dir.glob("*.png"))
        if candidates:
            style_ref = next((c for c in candidates if "cover" in c.name.lower()), candidates[0])
            logger.info(f"  风格参考图: {style_ref.name}")

    semaphore = asyncio.Semaphore(max_concurrent)

    async def gen_char(char: dict):
        async with semaphore:
            config = char.get("config", {})
            raw_id = config.get("id", "")
            # SurrealDB 返回的 id 可能带表前缀，去掉
            char_id = str(raw_id).split(":")[-1] if ":" in str(raw_id) else str(raw_id)
            name = char.get("name", char_id)
            appearance = config.get("appearance_summary", f"character named {name}")
            out = asset_root / f"character_{char_id}" / "base" / "sprite.png"
            if out.exists():
                results[f"character_{char_id}"] = str(out)
                return
            path = await generate_character_sprite(name, appearance, out, novel_title, style_ref)
            if path:
                results[f"character_{char_id}"] = str(path)

    async def gen_loc(loc: dict):
        async with semaphore:
            raw_id = loc.get("id", "")
            # SurrealDB 返回的 id 可能带表前缀（如 "location:meeting_room"），需要去掉
            loc_id = str(raw_id).split(":")[-1] if ":" in str(raw_id) else str(raw_id)
            name = loc.get("name", loc_id)
            desc = loc.get("description", "")
            out = asset_root / f"location_{loc_id}" / "base" / "background.png"
            if out.exists():
                results[f"location_{loc_id}"] = str(out)
                return
            path = await generate_scene_background(name, desc, out, novel_title, style_ref)
            if path:
                results[f"location_{loc_id}"] = str(path)

    # 并发执行所有生成任务
    tasks = [gen_char(c) for c in characters] + [gen_loc(l) for l in locations]
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"图片生成完成: {len(results)}/{len(characters) + len(locations)}")
    return results
