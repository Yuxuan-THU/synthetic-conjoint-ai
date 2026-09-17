"""分析 01 · 描述统计与数据有效性检查。

输出：
    outputs/tables/descriptives_cells.csv        分单元的描述统计
    outputs/tables/descriptives_sessions.csv     分时段
    outputs/tables/descriptives_parse.csv        解析质量（读清洗阶段汇总）
    outputs/tables/cost_summary.csv              成本核算
    outputs/figures/descriptives_*.png

用法：python source/analysis/01_descriptives.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    OUTPUTS_FIGURES,
    OUTPUTS_TABLES,
    attribute_metadata,
    ensure_dirs,
    read_table,
    setup_matplotlib,
    save_table,
)


def main() -> int:
    ensure_dirs()
    panel = read_table("choice_panel")
    metadata = attribute_metadata()
    print(f"载入 choice_panel：{len(panel)} 行")

    # --- 分单元 -------------------------------------------------------------
    group_keys = [
        key
        for key in ["model_key", "condition", "scenario", "jurisdiction", "cell_id"]
        if key in panel.columns
    ]
    rows = []
    for keys, group in panel.groupby(group_keys, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        record = dict(zip(group_keys, keys))
        usable = group[group["is_usable"]]
        record.update(
            {
                "n_calls": len(group),
                "n_usable": len(usable),
                "usable_share": round(len(usable) / len(group), 4),
                "n_refusal": int(group["is_refusal"].sum()) if "is_refusal" in group else 0,
                "n_truncated": int(group["is_truncated"].sum()) if "is_truncated" in group else 0,
                "share_choose_a": round(float((usable["choice_parsed"] == "A").mean()), 4)
                if len(usable)
                else None,
                "mean_explanation_words": round(float(usable["explanation_words"].mean()), 2)
                if len(usable)
                else None,
                "median_latency_ms": float(usable["latency_ms"].median())
                if "latency_ms" in usable and len(usable)
                else None,
                "n_anchor_calls": int((group["task_kind"] == "anchor").sum())
                if "task_kind" in group
                else 0,
                "n_distinct_sessions": group["session_label"].nunique()
                if "session_label" in group
                else 0,
            }
        )
        rows.append(record)
    cells = pd.DataFrame(rows)
    save_table(cells, "descriptives_cells")
    print(f"descriptives_cells.csv：{len(cells)} 行")

    # --- 分时段（这是 Huhe 特别关心的 precaution）-------------------------
    if "session_label" in panel.columns:
        session_rows = []
        for keys, group in panel.groupby(
            [key for key in ["model_key", "condition", "session_label"] if key in panel.columns]
        ):
            keys = keys if isinstance(keys, tuple) else (keys,)
            usable = group[group["is_usable"]]
            session_rows.append(
                {
                    "condition": keys[-1] if len(keys) == 1 else keys[1],
                    "session_label": keys[-1],
                    "n_calls": len(group),
                    "share_choose_a": round(float((usable["choice_parsed"] == "A").mean()), 4)
                    if len(usable)
                    else None,
                    "mean_explanation_words": round(
                        float(usable["explanation_words"].mean()), 2
                    )
                    if len(usable)
                    else None,
                    "requested_at_bj_min": group["requested_at_bj"].min()
                    if "requested_at_bj" in group
                    else None,
                    "requested_at_bj_max": group["requested_at_bj"].max()
                    if "requested_at_bj" in group
                    else None,
                }
            )
        sessions = pd.DataFrame(session_rows)
        save_table(sessions, "descriptives_sessions")
        print(f"descriptives_sessions.csv：{len(sessions)} 行")

    # --- 成本 ---------------------------------------------------------------
    if "estimated_cost_usd" in panel.columns:
        cost = (
            panel.groupby([key for key in ["model_key", "condition", "scenario"] if key in panel.columns])
            .agg(
                n_calls=("estimated_cost_usd", "size"),
                total_cost_usd=("estimated_cost_usd", "sum"),
                prompt_tokens=("usage_prompt_tokens", "sum"),
                completion_tokens=("usage_completion_tokens", "sum"),
                cache_hit_tokens=("prompt_cache_hit_tokens", "sum"),
            )
            .reset_index()
        )
        cost["cost_per_call_usd"] = (cost["total_cost_usd"] / cost["n_calls"]).round(6)
        cost["cache_hit_share"] = (
            cost["cache_hit_tokens"] / cost["prompt_tokens"].replace(0, pd.NA)
        ).round(4)
        save_table(cost, "cost_summary")
        print(f"cost_summary.csv：{len(cost)} 行，合计 ${cost['total_cost_usd'].sum():.4f}")

    # --- 解释长度与选择份额图 ----------------------------------------------
    _plot_length_distribution(panel)
    _plot_choice_share(cells)

    # --- 解析质量（沿用清洗阶段的汇总）------------------------------------
    parse_path = OUTPUTS_TABLES / "parse_quality_summary.csv"
    if parse_path.exists():
        print("\n解析质量汇总：")
        print(pd.read_csv(parse_path, encoding="utf-8-sig").to_string(index=False))

    print("\n描述统计完成。")
    return 0


def _plot_length_distribution(panel: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    setup_matplotlib()

    usable = panel[panel["is_usable"]]
    if usable.empty or "explanation_words" not in usable:
        return
    fig, axis = plt.subplots(figsize=(8, 4))
    for condition, group in usable.groupby("condition"):
        axis.hist(group["explanation_words"], bins=40, alpha=0.55, label=str(condition))
    axis.axvline(50, color="red", linestyle="--", linewidth=1)
    axis.text(51, axis.get_ylim()[1] * 0.9, "prompt 要求 ≤50 词", color="red", fontsize=8)
    axis.set_xlabel("解释词数")
    axis.set_ylabel("调用次数")
    axis.set_title("解释长度分布（按条件）")
    axis.legend()
    fig.tight_layout()
    path = OUTPUTS_FIGURES / "descriptives_explanation_length.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"figures：{path.name}")


def _plot_choice_share(cells: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    setup_matplotlib()

    if cells.empty or "share_choose_a" not in cells:
        return
    frame = cells.dropna(subset=["share_choose_a"]).copy()
    if frame.empty:
        return
    frame["label"] = (
        frame["condition"].astype(str)
        + "\n"
        + frame["scenario"].astype(str)
        + "\n"
        + frame.get("jurisdiction", pd.Series([""] * len(frame))).fillna("").astype(str)
    )
    fig, axis = plt.subplots(figsize=(max(6, 1.4 * len(frame)), 4))
    axis.bar(frame["label"], frame["share_choose_a"], color="#4a5568")
    axis.axhline(0.5, color="red", linestyle="--", linewidth=1)
    axis.set_ylabel("选择 Option A 的比例")
    axis.set_ylim(0, 1)
    axis.set_title("各单元的选择份额（0.5 = 无位置偏好）")
    fig.tight_layout()
    path = OUTPUTS_FIGURES / "descriptives_choice_share.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"figures：{path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
