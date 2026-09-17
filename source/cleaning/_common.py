"""清洗阶段的公共工具：路径、读写、响应文件发现。

约定（research-project-template）：
    - 清洗脚本只读 data/raw/ 与 data/collection/config/，产物写 outputs/。
    - 所有中间与最终数据一律提供 parquet（装了 pyarrow 时）与 csv 双份，
      保证在没装 pyarrow 的机器上也能跑通。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESPONSES_DIR = PROJECT_ROOT / "data" / "raw" / "responses"
DESIGN_DIR = PROJECT_ROOT / "data" / "raw" / "design"
LEGAL_TEXT_DIR = PROJECT_ROOT / "data" / "raw" / "legal_texts"
OUTPUTS_DATA = PROJECT_ROOT / "outputs" / "data"
OUTPUTS_TABLES = PROJECT_ROOT / "outputs" / "tables"
OUTPUTS_FIGURES = PROJECT_ROOT / "outputs" / "figures"
OUTPUTS_OTHER = PROJECT_ROOT / "outputs" / "other"


def ensure_dirs() -> None:
    for directory in (
        OUTPUTS_DATA,
        OUTPUTS_TABLES,
        OUTPUTS_FIGURES,
        OUTPUTS_OTHER,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def write_table(frame: pd.DataFrame, stem: str, directory: Path | None = None) -> list[Path]:
    """写 parquet + csv 两份，返回实际写出的路径。"""
    directory = directory or OUTPUTS_DATA
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    parquet_path = directory / f"{stem}.parquet"
    try:
        frame.to_parquet(parquet_path, index=False)
        written.append(parquet_path)
    except Exception as exc:  # noqa: BLE001 - pyarrow 缺失时退化到 csv
        print(f"[warn] parquet 写入失败（{type(exc).__name__}），退化到 csv：{parquet_path.name}")
    csv_path = directory / f"{stem}.csv"
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    written.append(csv_path)
    return written


def read_table(stem: str, directory: Path | None = None) -> pd.DataFrame:
    """优先读 parquet，退化读 csv。"""
    directory = directory or OUTPUTS_DATA
    parquet_path = directory / f"{stem}.parquet"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    csv_path = directory / f"{stem}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 {parquet_path} 或 {csv_path}；请先运行清洗步骤。")
    return pd.read_csv(csv_path, encoding="utf-8-sig")


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    import json

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是合法 JSON 行：{exc}") from exc


def response_files(run_id: str | None = None) -> list[Path]:
    """列出所有响应 JSONL（排除错误日志与提示词归档）。"""
    if not RESPONSES_DIR.exists():
        return []
    pattern = f"{run_id}__*.jsonl" if run_id else "*.jsonl"
    files = []
    for path in sorted(RESPONSES_DIR.glob(pattern)):
        if path.name.endswith("__errors.jsonl"):
            continue
        if path.name == "_prompt_archive.jsonl":
            continue
        files.append(path)
    return files


def prompt_archive() -> dict[str, dict[str, Any]]:
    """读取提示词前缀归档（法规全文等只存一份的内容）。"""
    path = RESPONSES_DIR / "_prompt_archive.jsonl"
    if not path.exists():
        return {}
    return {row["prompt_archive_id"]: row for row in iter_jsonl(path)}


def load_responses(run_id: str | None = None, include_mock: bool | None = None) -> pd.DataFrame:
    """读取原始响应。

    默认不读 MOCK_ 开头的 run（自检/演示用的伪数据），
    除非显式指定了 run_id——这样自检数据永远不会污染真实分析。
    """
    if include_mock is None:
        include_mock = run_id is not None
    rows: list[dict[str, Any]] = []
    for path in response_files(run_id):
        if not include_mock and path.name.startswith("MOCK"):
            continue
        for record in iter_jsonl(path):
            record["_source_file"] = path.name
            rows.append(record)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    # 同一 (run_id, task_id) 只保留最后一次成功记录，避免重跑留下重复行
    if {"run_id", "task_id"}.issubset(frame.columns):
        frame = frame.sort_values(["run_id", "task_id", "call_index"]).drop_duplicates(
            subset=["run_id", "task_id"], keep="last"
        )
    return frame.reset_index(drop=True)


def attribute_metadata() -> pd.DataFrame:
    path = DESIGN_DIR / "attribute_metadata.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"找不到 {path}；请先运行 data/collection/01_build_design_matrix.py"
        )
    return pd.read_csv(path, encoding="utf-8-sig")


def session_plan(run_id: str | None = None) -> pd.DataFrame:
    """读取单元 × 时段的配额计划（取最新的一份或指定 run 的）。"""
    if run_id:
        candidates = [DESIGN_DIR / f"{run_id}__session_plan.csv"]
    else:
        candidates = sorted(DESIGN_DIR.glob("*__session_plan.csv"))
    for path in reversed(candidates):
        if path.exists():
            return pd.read_csv(path, encoding="utf-8-sig")
    return pd.DataFrame()


def write_csv_rows(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)
