"""
小说分块器 — 将长篇小说拆分为 LLM 可处理的块

策略：
1. 按章节拆分（优先，自然边界）
2. 超长章节再按段落切分，保证每块 < max_tokens
3. 块之间保留重叠（overlap）以维持上下文连贯
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """一个文本块"""
    index: int
    chapter: int | None          # 所属章节号（如果能识别）
    chapter_title: str           # 章节标题
    text: str
    char_count: int = 0
    overlap_from_prev: str = ""  # 从上一块保留的重叠文本

    def __post_init__(self):
        self.char_count = len(self.text)


# 常见的中文章节标题模式
CHAPTER_PATTERNS = [
    re.compile(r'^第[一二三四五六七八九十百千万零\d]+[章回节卷].*', re.MULTILINE),
    re.compile(r'^Chapter\s+\d+.*', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\d+[\.、]\s*\S+', re.MULTILINE),
]


def detect_chapters(text: str) -> list[tuple[int, str, str]]:
    """
    检测章节边界，返回 [(start_pos, title, body), ...]
    """
    # 尝试每种模式，用匹配数最多的
    best_matches: list[re.Match] = []
    for pattern in CHAPTER_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) > len(best_matches):
            best_matches = matches

    if not best_matches:
        # 无法识别章节，整体作为一个块
        return [(0, "全文", text)]

    chapters = []
    for i, match in enumerate(best_matches):
        start = match.start()
        end = best_matches[i + 1].start() if i + 1 < len(best_matches) else len(text)
        title = match.group().strip()
        body = text[start:end].strip()
        chapters.append((start, title, body))

    return chapters


def chunk_novel(
    text: str,
    max_chars: int = 8000,
    overlap_chars: int = 200,
) -> list[Chunk]:
    """
    将小说文本拆分为块。

    Args:
        text: 完整小说文本
        max_chars: 每块最大字符数
        overlap_chars: 块间重叠字符数
    """
    chapters = detect_chapters(text)
    chunks: list[Chunk] = []
    chunk_idx = 0

    for ch_idx, (_, title, body) in enumerate(chapters):
        chapter_num = ch_idx + 1

        if len(body) <= max_chars:
            # 整章作为一个块
            chunks.append(Chunk(
                index=chunk_idx,
                chapter=chapter_num,
                chapter_title=title,
                text=body,
            ))
            chunk_idx += 1
        else:
            # 超长章节按段落切分
            paragraphs = re.split(r'\n\s*\n', body)
            current_text = ""
            for para in paragraphs:
                if len(current_text) + len(para) + 2 > max_chars and current_text:  # +2 for \n\n separator
                    chunks.append(Chunk(
                        index=chunk_idx,
                        chapter=chapter_num,
                        chapter_title=f"{title}（续）" if chunks and chunks[-1].chapter == chapter_num else title,
                        text=current_text,
                        overlap_from_prev=current_text[-overlap_chars:] if overlap_chars else "",
                    ))
                    chunk_idx += 1
                    current_text = current_text[-overlap_chars:] + "\n\n" + para if overlap_chars else para
                else:
                    current_text = current_text + "\n\n" + para if current_text else para

            if current_text.strip():
                chunks.append(Chunk(
                    index=chunk_idx,
                    chapter=chapter_num,
                    chapter_title=title,
                    text=current_text,
                ))
                chunk_idx += 1

    return chunks
