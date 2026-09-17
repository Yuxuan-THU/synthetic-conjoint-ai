"""分析阶段的公共工具：读表、AMCE 估计、绘图。

AMCE 的做法（Hainmueller, Hopkins & Yamamoto 2014）：
    把数据整理成 (调用 × 方案 × 属性) 的长表，对每个属性删掉一个基准水平，
    以 chosen 为因变量做无截距 OLS。系数即该水平相对基准水平的边际效应。
    标准误按 task_signature_pair 聚类：同一对方案可能被抽到多次，
    聚类避免把"重复暴露"当成独立观测。

    treatment 效应 = 在 X 中额外加入"属性哑变量 × 条件"的交互项，
    交互项系数即 government 相对 generic 的 AMCE 变化。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DIR = PROJECT_ROOT / "data" / "raw" / "design"
OUTPUTS_DATA = PROJECT_ROOT / "outputs" / "data"
OUTPUTS_TABLES = PROJECT_ROOT / "outputs" / "tables"
OUTPUTS_FIGURES = PROJECT_ROOT / "outputs" / "figures"
OUTPUTS_OTHER = PROJECT_ROOT / "outputs" / "other"


def ensure_dirs() -> None:
    for directory in (OUTPUTS_TABLES, OUTPUTS_FIGURES, OUTPUTS_OTHER):
        directory.mkdir(parents=True, exist_ok=True)


def read_table(stem: str, directory: Path | None = None) -> pd.DataFrame:
    directory = directory or OUTPUTS_DATA
    parquet_path = directory / f"{stem}.parquet"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    csv_path = directory / f"{stem}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 {stem}；请先运行 source/cleaning/ 下的脚本。")
    return pd.read_csv(csv_path, encoding="utf-8-sig")


def save_table(frame: pd.DataFrame, stem: str) -> Path:
    OUTPUTS_TABLES.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS_TABLES / f"{stem}.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def attribute_metadata() -> pd.DataFrame:
    path = DESIGN_DIR / "attribute_metadata.csv"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}；请先运行 data/collection/01_build_design_matrix.py")
    return pd.read_csv(path, encoding="utf-8-sig")


def reference_levels(metadata: pd.DataFrame, scenario: str) -> dict[str, str]:
    """每个属性的基准水平 = metadata 中该属性的第一个水平（即 attribute table 的第一档）。"""
    subset = metadata[metadata["scenario"] == scenario]
    references: dict[str, str] = {}
    for attribute_id, group in subset.groupby("attribute_id", sort=False):
        references[attribute_id] = group.sort_values("level_index").iloc[0]["level_id"]
    return references


def level_order(metadata: pd.DataFrame, scenario: str, attribute_id: str) -> list[str]:
    subset = metadata[
        (metadata["scenario"] == scenario) & (metadata["attribute_id"] == attribute_id)
    ]
    return list(subset.sort_values("level_index")["level_id"])


def level_label(metadata: pd.DataFrame, scenario: str, attribute_id: str, level_id: str) -> str:
    subset = metadata[
        (metadata["scenario"] == scenario)
        & (metadata["attribute_id"] == attribute_id)
        & (metadata["level_id"] == level_id)
    ]
    if subset.empty:
        return level_id
    return str(subset.iloc[0]["level_label_en"])


def _design_matrix(
    frame: pd.DataFrame,
    metadata: pd.DataFrame,
    scenario: str,
    interact_column: str | None = None,
    interact_value: Any = None,
) -> tuple[pd.DataFrame, pd.Series, dict[str, tuple[str, str]]]:
    references = reference_levels(metadata, scenario)
    frame = frame.copy()
    frame["attribute_level"] = frame["attribute"] + "::" + frame["level"]

    dummies = pd.get_dummies(frame["attribute_level"], dtype=float)
    drop_columns = [
        f"{attribute}::{level}"
        for attribute, level in references.items()
        if f"{attribute}::{level}" in dummies.columns
    ]
    dummies = dummies.drop(columns=drop_columns)
    # 保证列名稳定、可读
    dummies = dummies.reindex(sorted(dummies.columns), axis=1)

    design = dummies.copy()
    if interact_column:
        indicator = (frame[interact_column] == interact_value).astype(float)
        interaction = dummies.multiply(indicator, axis=0)
        interaction.columns = [f"{column}__x__{interact_value}" for column in interaction.columns]
        design = pd.concat([design, interaction], axis=1)

    labels: dict[str, tuple[str, str]] = {}
    for column in dummies.columns:
        attribute, level = column.split("::")
        labels[column] = (attribute, level)
    return design, frame["chosen"].astype(float), labels


def estimate_amce(
    frame: pd.DataFrame,
    metadata: pd.DataFrame,
    scenario: str,
    cluster_column: str = "task_signature_pair",
    interact_column: str | None = None,
    interact_value: Any = None,
    min_n: int = 30,
) -> pd.DataFrame:
    """估计一组 AMCE（可选叠加条件交互项）。"""
    usable = frame[frame["chosen"].notna()].copy()
    if len(usable) < min_n:
        return pd.DataFrame()

    references = references_of(metadata, scenario)
    design, outcome, labels = _design_matrix(
        usable, metadata, scenario, interact_column, interact_value
    )
    if design.empty:
        return pd.DataFrame()

    model = sm.OLS(outcome, design)
    if cluster_column in usable.columns and usable[cluster_column].nunique() > 1:
        results = model.fit(
            cov_type="cluster", cov_kwds={"groups": usable[cluster_column].astype(str)}
        )
    else:
        results = model.fit(cov_type="HC1")

    rows: list[dict[str, Any]] = []
    for column in design.columns:
        coefficient = float(results.params.get(column, np.nan))
        std_error = float(results.bse.get(column, np.nan))
        pvalue = float(results.pvalues.get(column, np.nan))
        if column.endswith(f"__x__{interact_value}"):
            base_column = column[: -len(f"__x__{interact_value}")]
            attribute, level = labels.get(base_column, (base_column, ""))
            term_type = "interaction"
            level_label_ = level_label(metadata, scenario, attribute, level)
        else:
            attribute, level = labels.get(column, (column, ""))
            term_type = "amce"
            level_label_ = level_label(metadata, scenario, attribute, level)
        rows.append(
            {
                "scenario": scenario,
                "attribute": attribute,
                "level": level,
                "level_label_en": level_label_,
                "term_type": term_type,
                "interact_value": interact_value if term_type == "interaction" else "",
                "reference_level": "" if term_type == "interaction" else references.get(attribute, ""),
                "estimate": coefficient,
                "std_error": std_error,
                "ci_low": coefficient - 1.96 * std_error,
                "ci_high": coefficient + 1.96 * std_error,
                "pvalue": pvalue,
                "n_observations": int(len(usable)),
                "n_clusters": int(usable[cluster_column].nunique())
                if cluster_column in usable.columns
                else 0,
                "r_squared": float(results.rsquared),
            }
        )
    return pd.DataFrame(rows)


_REFERENCE_CACHE: dict[str, dict[str, str]] = {}


def references_of(metadata: pd.DataFrame, scenario: str) -> dict[str, str]:
    if scenario not in _REFERENCE_CACHE:
        _REFERENCE_CACHE[scenario] = reference_levels(metadata, scenario)
    return _REFERENCE_CACHE[scenario]


def setup_matplotlib() -> None:
    """统一 matplotlib 设置：中文字体 + 无交互后端。

    默认字体不含汉字，否则图里全是方块（实际踩过）。
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "PingFang SC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def plot_amce(
    table: pd.DataFrame,
    title: str,
    path: Path,
    scenarios: Sequence[str] | None = None,
) -> Path | None:
    """按属性分面画 AMCE 点估计与 95% 置信区间。"""
    if table.empty:
        return None
    import matplotlib.pyplot as plt

    setup_matplotlib()

    frame = table[table["term_type"] == "amce"].copy()
    if scenarios:
        frame = frame[frame["scenario"].isin(scenarios)]
    if frame.empty:
        return None

    scenarios_present = list(dict.fromkeys(frame["scenario"]))
    fig, axes = plt.subplots(
        nrows=len(scenarios_present),
        ncols=1,
        figsize=(9, 3.2 * len(scenarios_present)),
        squeeze=False,
    )
    for row_index, scenario in enumerate(scenarios_present):
        axis = axes[row_index][0]
        subset = frame[frame["scenario"] == scenario].sort_values(["attribute", "level"])
        y_positions = np.arange(len(subset))
        axis.errorbar(
            subset["estimate"],
            y_positions,
            xerr=1.96 * subset["std_error"],
            fmt="o",
            color="#2b6cb0",
            ecolor="#90cdf4",
            capsize=3,
        )
        axis.axvline(0, color="#888", linewidth=0.8, linestyle="--")
        axis.set_yticks(y_positions)
        axis.set_yticklabels(
            [f"{r.attribute} · {r.level}" for r in subset.itertuples()], fontsize=8
        )
        axis.invert_yaxis()
        axis.set_xlabel("AMCE（相对该属性基准水平的选择概率变化）")
        axis.set_title(scenario)
    fig.suptitle(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def group_frames(
    frame: pd.DataFrame, keys: Iterable[str]
) -> list[tuple[tuple[Any, ...], pd.DataFrame]]:
    keys = [key for key in keys if key in frame.columns]
    if not keys:
        return [((), frame)]
    return [
        (key if isinstance(key, tuple) else (key,), group)
        for key, group in frame.groupby(keys)
    ]


def describe_choice(frame: pd.DataFrame) -> dict[str, Any]:
    valid = frame[frame["chose_a"].notna()]
    return {
        "n_observations": int(len(frame)),
        "n_valid": int(len(valid)),
        "share_choose_a": round(float((valid["chose_a"] == 1).mean()), 4) if len(valid) else None,
        "mean_explanation_words": round(float(valid["explanation_words"].mean()), 2)
        if "explanation_words" in valid and len(valid)
        else None,
    }
