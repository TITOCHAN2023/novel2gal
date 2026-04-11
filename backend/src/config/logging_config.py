"""日志配置——全局日志 + 按故事分割"""
import logging
import sys
from pathlib import Path


def setup_logging(log_dir: str | Path = "./data/logs", level: int = logging.INFO) -> None:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 控制台（立即 flush）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(level)

    # 全局日志文件
    file_handler = logging.FileHandler(log_dir / "pipeline.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    file_handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # 避免重复添加
    if not root.handlers:
        root.addHandler(console_handler)
        root.addHandler(file_handler)

    # 降低第三方库日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("surrealdb").setLevel(logging.WARNING)


def add_story_logger(story_id: str, log_dir: Path) -> logging.Logger:
    """为特定故事创建独立的日志文件"""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"story.{story_id}")

    # 避免重复添加
    if not logger.handlers:
        handler = logging.FileHandler(log_dir / f"{story_id}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

    return logger
