"""哈希、时间、JSONL 追加写、断点续跑等基础工具。"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .config import BEIJING_OFFSET_HOURS

BEIJING_TZ = _dt.timezone(_dt.timedelta(hours=BEIJING_OFFSET_HOURS), name="UTC+08:00")


# --- 哈希 -------------------------------------------------------------------

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_seed(*parts: Any) -> int:
    """由任意标识派生稳定整数种子。

    同一个 (run_id, cell_id, task_index) 永远得到同一个种子，
    因此设计矩阵可重放——这是"任务已冻结"的技术保证。
    """
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


# --- 时间 -------------------------------------------------------------------

def now_utc() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def to_beijing(moment: _dt.datetime) -> _dt.datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return moment.astimezone(BEIJING_TZ)


def iso_beijing(moment: _dt.datetime) -> str:
    return to_beijing(moment).isoformat(timespec="milliseconds")


def iso_utc(moment: _dt.datetime) -> str:
    return moment.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds")


def timestamp_slug(moment: _dt.datetime | None = None) -> str:
    """用于文件名的时间戳：北京时间 yyyyMMdd-HHMMSS。"""
    moment = moment or now_utc()
    return to_beijing(moment).strftime("%Y%m%d-%H%M%S")


def beijing_hour(moment: _dt.datetime | None = None) -> int:
    return to_beijing(moment or now_utc()).hour


# --- JSONL ------------------------------------------------------------------

def append_jsonl(path: str | os.PathLike[str], record: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def iter_jsonl(path: str | os.PathLike[str]) -> Iterator[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:  # 明确报出坏行位置，便于人工修复
                raise ValueError(f"{path}:{line_number} 不是合法 JSON 行：{exc}") from exc


def load_jsonl(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def existing_keys(
    path: str | os.PathLike[str], key_fields: Sequence[str]
) -> set[tuple[Any, ...]]:
    """读取已有 JSONL 的键集合，用于断点续跑去重。"""
    keys: set[tuple[Any, ...]] = set()
    for record in iter_jsonl(path):
        keys.add(tuple(record.get(field) for field in key_fields))
    return keys


def write_json(path: str | os.PathLike[str], payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


# --- 文本 -------------------------------------------------------------------

def normalize_ws(text: str) -> str:
    """把 YAML 块标量里的折行压成单个空格，用于提示词等自然语言文本。

    注意：法规正文【不能】使用该函数，必须保留段落结构。
    """
    return " ".join(text.split())


def estimate_tokens(text: str, language: str = "en") -> int:
    """粗略 token 估算，仅用于成本预警，不用于计费。

    中文按 1 字 ≈ 0.7 token；英文按 4 字符 ≈ 1 token。
    """
    if language.startswith("zh"):
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cjk
        return int(cjk * 0.7 + other / 4) + 1
    return int(len(text) / 4) + 1


def truncate_keep_tail(text: str, max_chars: int) -> tuple[str, bool]:
    """按字符数截断（保留头部），返回 (文本, 是否被截断)。"""
    if max_chars is None or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def format_table(rows: Iterable[Sequence[str]]) -> str:
    """把二维表渲染成 Markdown 表格。"""
    rendered = []
    for row_index, row in enumerate(rows):
        rendered.append("| " + " | ".join(str(cell) for cell in row) + " |")
        if row_index == 0:
            rendered.append("| " + " | ".join("---" for _ in row) + " |")
    return "\n".join(rendered)
