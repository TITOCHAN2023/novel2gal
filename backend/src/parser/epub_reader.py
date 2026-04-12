"""
EPUB 读取器 — 从 epub 文件中提取章节文本
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")


@dataclass
class Chapter:
    index: int
    title: str
    text: str
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.text)


def extract_images(path: str | Path, output_dir: str | Path) -> list[dict]:
    """从 epub 提取所有插图，返回 [{name, path, size_kb}]"""
    book = epub.read_epub(str(path))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for img in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        name = Path(img.get_name()).name
        out_path = output_dir / name
        content = img.get_content()
        out_path.write_bytes(content)
        results.append({
            "name": name,
            "path": str(out_path),
            "size_kb": len(content) // 1024,
        })
    return results


def read_epub(path: str | Path) -> list[Chapter]:
    """从 epub 提取所有正文章节（跳过封面、目录、后记等）"""
    book = epub.read_epub(str(path))
    chapters: list[Chapter] = []
    idx = 0

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text(separator="\n", strip=False)
        # 清理连续空行
        lines = text.split("\n")
        cleaned = []
        prev_empty = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if not prev_empty:
                    cleaned.append("")
                prev_empty = True
            else:
                cleaned.append(stripped)
                prev_empty = False
        text = "\n".join(cleaned).strip()

        # 跳过太短的内容（封面、目录、后记等）
        if len(text) < 500:
            continue

        # 尝试提取标题
        title_tag = soup.find(["h1", "h2", "h3", "title"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            title = f"章节 {idx + 1}"
        # 如果标题太长或者就是正文开头，用文件名
        if len(title) > 50:
            name = item.get_name()
            title = name.rsplit("/", 1)[-1].replace(".xhtml", "").replace(".html", "")

        chapters.append(Chapter(index=idx, title=title, text=text))
        idx += 1

    return chapters
