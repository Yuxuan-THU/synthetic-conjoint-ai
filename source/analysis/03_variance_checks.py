"""分析 03 · 稳健性检验（Huhe 关心的三件事）。

    1. 锚点一致性：同一任务重复 12 次，在不同时段是否给出一致回答
       —— 直接回应"identical 选择未必得到相同回应"。
    2. 时段效应：控制任务构成后，早/中/晚是否存在系统差异。
    3. 呈现顺序效应：同一对方案在不同属性行序下是否给出相同选择。

输出：
    outputs/tables/anchor_consistency.csv
    outputs/tables/session_effects.csv
    outputs/tables/order_effects.csv
    outputs/figures/anchor_*.png
    outputs/figures/session_*.png

用法：python source/analysis/03_variance_checks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    OUTPUTS_FIGURES,
    attribute_metadata,
    ensure_dirs,
    read_table,
    setup_matplotlib,
    save_table,
)


def anchor_consistency(panel: pd.DataFrame) -> pd.DataFrame:
    """每个锚点任务的选择分布 + 与 0.5 的偏离检验（二项检验）。

    分组键是【锚点任务本体】，不是 task_id：
    task_id 里带 rep{repeat_index}（为了断点续跑去重），直接按 task_id 分组会
    把 12 次重复拆成 12 个"各只有 1 次"的独立任务，结论全错（确实错过一次）。
    正确做法是按 (cell_id, task_index, task_signature) 分组。
    """
    from scipy import stats

    anchors = panel[(panel["task_kind"] == "anchor") & panel["is_usable"]].copy()
    if anchors.empty:
        return pd.DataFrame()
    anchors["anchor_group_id"] = (
        anchors["cell_id"].astype(str) + "::anchor-" + anchors["task_index"].astype(str).str.zfill(2)
    )

    rows: list[dict[str, object]] = []
    for (anchor_group_id, task_signature), group in anchors.groupby(
        ["anchor_group_id", "task_signature"]
    ):
        n = len(group)
        n_a = int((group["choice_parsed"] == "A").sum())
        share_a = n_a / n if n else np.nan
        # 若模型对同一任务其实是确定性回答，share 会是 0 或 1；
        # 否则会分布在中间。二项检验只用于描述"是否偏离 50/50"。
        binom_p = stats.binomtest(n_a, n, 0.5).pvalue if n else np.nan
        rows.append(
            {
                "cell_id": group["cell_id"].iloc[0],
                "anchor_group_id": anchor_group_id,
                "task_signature": task_signature,
                "n_repeats": n,
                "n_choose_a": n_a,
                "share_choose_a": round(share_a, 4),
                "is_deterministic": int(n_a in (0, n)),
                "n_distinct_sessions": group["session_label"].nunique(),
                "binom_p_vs_0.5": round(float(binom_p), 6) if n else None,
                "mean_explanation_words": round(float(group["explanation_words"].mean()), 2),
            }
        )
    table = pd.DataFrame(rows).sort_values(["cell_id", "anchor_group_id"])

    # 汇总：有多少锚点任务是"确定性的"、以及每个任务的回答分歧程度
    summary = (
        table.groupby("cell_id")
        .agg(
            n_anchor_tasks=("anchor_group_id", "nunique"),
            n_repeats_total=("n_repeats", "sum"),
            n_deterministic_tasks=("is_deterministic", "sum"),
            share_deterministic=("is_deterministic", "mean"),
            mean_share_choose_a=("share_choose_a", "mean"),
            sd_share_choose_a=("share_choose_a", "std"),
        )
        .reset_index()
    )
    for column in ("share_deterministic", "mean_share_choose_a", "sd_share_choose_a"):
        summary[column] = summary[column].round(4)
    print("\n=== 锚点一致性（同一任务重复 12 次）===")
    print(summary.to_string(index=False))
    print(
        "解读：share_deterministic = 12 次回答完全一致的锚点任务占比。"
        "若该值 <1，说明模型对同一任务并非确定性回答，"
        "这正是 Huhe 说的『identical 选择未必得到相同回应』的量化证据，"
        "也意味着单次选择只能视为一次抽样，而非模型偏好的点估计。"
    )
    return table


def session_effects(panel: pd.DataFrame) -> pd.DataFrame:
    """在控制属性取值后估计时段效应。

    做法：以 chose_a 为因变量，加入全部属性水平哑变量 + 时段哑变量，
    时段系数即在"任务构成被控制"之后仍存在的时段差异。
    """
    import statsmodels.api as sm

    main = panel[(panel["task_kind"] == "main") & panel["chose_a"].notna()]
    if main.empty or "session_label" not in main.columns:
        return pd.DataFrame()

    chunks: list[pd.DataFrame] = []
    for keys, group in main.groupby(["model_key", "condition", "scenario", "jurisdiction"]):
        model_key, condition, scenario, jurisdiction = keys
        if group["session_label"].nunique() < 2:
            continue
        attributes = [
            column[3:] for column in group.columns if column.startswith("a__")
        ]
        design_parts = []
        for attribute in attributes:
            for option in ("a", "b"):
                column = f"{option}__{attribute}"
                if column not in group:
                    continue
                dummies = pd.get_dummies(group[column], prefix=f"{option}_{attribute}", dtype=float)
                design_parts.append(dummies)
        if not design_parts:
            continue
        design = pd.concat(design_parts, axis=1)
        session_dummies = pd.get_dummies(group["session_label"], prefix="session", dtype=float)
        # 丢掉一个时段作为基准，避免与截距共线
        baseline_session = str(sorted(group["session_label"].unique())[0])
        session_dummies = session_dummies.drop(
            columns=[f"session_{baseline_session}"], errors="ignore"
        )
        design = pd.concat([design, session_dummies], axis=1)
        design = sm.add_constant(design, has_constant="add")

        model = sm.OLS(group["chose_a"].astype(float), design).fit(cov_type="HC1")
        for column in session_dummies.columns:
            chunks.append(
                {
                    "model_key": model_key,
                    "condition": condition,
                    "scenario": scenario,
                    "jurisdiction": jurisdiction,
                    "baseline_session": baseline_session,
                    "session": column.replace("session_", ""),
                    "estimate": float(model.params.get(column, np.nan)),
                    "std_error": float(model.bse.get(column, np.nan)),
                    "pvalue": float(model.pvalues.get(column, np.nan)),
                    "ci_low": float(model.params.get(column, np.nan))
                    - 1.96 * float(model.bse.get(column, np.nan)),
                    "ci_high": float(model.params.get(column, np.nan))
                    + 1.96 * float(model.bse.get(column, np.nan)),
                    "n_observations": int(len(group)),
                }
            )
    table = pd.DataFrame(chunks)
    if not table.empty:
        print("\n=== 时段效应（控制任务属性后，相对基准时段的选择概率变化）===")
        print(
            table[["condition", "scenario", "baseline_session", "session", "estimate", "std_error", "pvalue"]]
            .round(4)
            .to_string(index=False)
        )
    return table


def order_effects(panel: pd.DataFrame) -> pd.DataFrame:
    """同一对方案（task_signature_pair 相同）在不同属性行序下是否给出相同选择。"""
    usable = panel[(panel["task_kind"] == "main") & panel["chose_a"].notna()].copy()
    if "task_signature_pair" not in usable.columns or usable.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for (cell_id, pair_signature), group in usable.groupby(["cell_id", "task_signature_pair"]):
        if group["task_signature"].nunique() < 2:
            continue  # 只保留"同一对方案 + 不同行序"的情况
        rows.append(
            {
                "cell_id": cell_id,
                "task_signature_pair": pair_signature,
                "n_presentations": len(group),
                "n_distinct_orders": group["task_signature"].nunique(),
                "share_choose_a": round(float((group["chose_a"] == 1).mean()), 4),
                "n_choose_a": int((group["chose_a"] == 1).sum()),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        print(
            "\n没有出现「同一对方案 + 不同属性行序」的自然重复"
            "（见 01_build_design_matrix.py 的设计诊断）。"
        )
        return table

    from scipy import stats

    consistent = table[(table["share_choose_a"] == 0) | (table["share_choose_a"] == 1)]
    print("\n=== 属性行序效应 ===")
    print(f"可比较的方案对：{len(table)}")
    print(
        f"在同一行序不同时仍给出完全一致选择的方案对：{len(consistent)} "
        f"({len(consistent) / len(table):.1%})"
    )
    overall_n_a = int(table["n_choose_a"].sum())
    overall_n = int(table["n_presentations"].sum())
    if overall_n:
        pooled = stats.binomtest(overall_n_a, overall_n, 0.5)
        print(
            f"池化后选择 A 的比例：{overall_n_a / overall_n:.4f}"
            f"（二项检验 p={pooled.pvalue:.4f}，n={overall_n}）"
        )
    return table


def plot_anchor(anchors: pd.DataFrame) -> None:
    if anchors.empty:
        return
    import matplotlib.pyplot as plt

    setup_matplotlib()

    frame = anchors.copy()
    if "anchor_group_id" not in frame.columns:
        frame["anchor_group_id"] = (
            frame["cell_id"].astype(str)
            + "::anchor-"
            + frame["task_index"].astype(str).str.zfill(2)
        )
    frame["label"] = (
        frame["cell_id"].astype(str).str.slice(0, 22)
        + "\n"
        + frame["anchor_group_id"].str.split("::").str[-1]
    )
    fig, axis = plt.subplots(figsize=(max(8, 0.55 * len(frame)), 4))
    axis.bar(frame["label"], frame["share_choose_a"], color="#2f855a")
    axis.axhline(0.5, color="red", linestyle="--", linewidth=1)
    axis.set_ylabel("选择 Option A 的比例")
    axis.set_ylim(0, 1)
    axis.set_title("锚点任务重复 12 次的回答分布（0/1 = 完全确定，中间值 = 存在随机性）")
    axis.tick_params(axis="x", labelsize=6, rotation=90)
    fig.tight_layout()
    path = OUTPUTS_FIGURES / "anchor_consistency.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"figures：{path.name}")


def main() -> int:
    ensure_dirs()
    panel = read_table("choice_panel")
    attribute_metadata()  # 仅做存在性校验，保证设计矩阵已生成
    print(f"载入 choice_panel：{len(panel)} 行")

    anchors = anchor_consistency(panel)
    if not anchors.empty:
        save_table(anchors, "anchor_consistency")
        plot_anchor(anchors)

    sessions = session_effects(panel)
    if not sessions.empty:
        save_table(sessions, "session_effects")

    orders = order_effects(panel)
    if not orders.empty:
        save_table(orders, "order_effects")

    print("\n稳健性检验完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
