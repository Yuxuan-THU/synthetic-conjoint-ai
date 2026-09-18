"""配置、路径与环境变量加载。

设计原则：
    - 所有可调参数都在 data/collection/config/*.yaml，代码里不写死实验参数。
    - 路径一律相对项目根目录解析，保证换机器后可跑。
    - 密钥只从环境变量（.env）读取，绝不写进任何落盘文件。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# data/collection/_llm/config.py -> parents[3] = 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "data" / "collection" / "config"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RESPONSES_DIR = RAW_DIR / "responses"
DESIGN_DIR = RAW_DIR / "design"
LEGAL_TEXT_DIR = RAW_DIR / "legal_texts"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
OUTPUTS_DATA = OUTPUTS_DIR / "data"
OUTPUTS_TABLES = OUTPUTS_DIR / "tables"
OUTPUTS_FIGURES = OUTPUTS_DIR / "figures"
OUTPUTS_OTHER = OUTPUTS_DIR / "other"

# Windows 上 tzdata 可能缺失，而中国无夏令时，固定 UTC+8 与区域时区完全等价。
BEIJING_OFFSET_HOURS = 8


def load_env() -> None:
    """读取项目根目录 .env（不存在则静默跳过）。已存在的环境变量优先。"""
    try:
        from dotenv import load_dotenv
    except ImportError:  # 允许未安装 python-dotenv 时用系统环境变量
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def require_env(name: str) -> str:
    value = get_env(name)
    if not value:
        raise RuntimeError(
            f"环境变量 {name} 未设置。请在 {PROJECT_ROOT / '.env'} 中填写"
            f"（可从 .env.example 复制），或设置同名系统环境变量。"
        )
    return value


@lru_cache(maxsize=None)
def load_config(filename: str) -> dict[str, Any]:
    """加载 data/collection/config/<filename>，结果按文件名缓存。"""
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在：{path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是映射（dict）：{path}")
    return data


def load_experiment_config() -> dict[str, Any]:
    return load_config("experiment.yaml")


def load_models_config() -> dict[str, Any]:
    return load_config("models.yaml")


def load_scenarios_config() -> dict[str, Any]:
    return load_config("scenarios.yaml")


def load_prompts_config() -> dict[str, Any]:
    return load_config("prompts.yaml")


def load_legal_texts_config() -> dict[str, Any]:
    return load_config("legal_texts.yaml")


def config_sha256() -> str:
    """四个采集配置文件的联合哈希，用于给设计矩阵打"配置指纹"。"""
    from .io_utils import sha256_file

    digest_parts = []
    for name in (
        "experiment.yaml",
        "models.yaml",
        "scenarios.yaml",
        "prompts.yaml",
        "legal_texts.yaml",
    ):
        path = CONFIG_DIR / name
        digest_parts.append(f"{name}:{sha256_file(path) if path.exists() else 'missing'}")
    from .io_utils import sha256_text

    return sha256_text("\n".join(digest_parts))


def resolve_path(path_like: str | os.PathLike[str]) -> Path:
    """把相对路径解析为相对项目根目录的绝对路径。"""
    path = Path(path_like)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def ensure_output_dirs() -> None:
    for directory in (
        RESPONSES_DIR,
        DESIGN_DIR,
        LEGAL_TEXT_DIR,
        OUTPUTS_DATA,
        OUTPUTS_TABLES,
        OUTPUTS_FIGURES,
        OUTPUTS_OTHER,
    ):
        directory.mkdir(parents=True, exist_ok=True)
