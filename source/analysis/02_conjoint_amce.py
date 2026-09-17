"""分析 02 · AMCE 与 treatment 效应（论文核心结果）。

做三件事：
    1. 各（模型 × 条件 × 情景）分别估计 AMCE，与人类样本对照时用同一基准组；
    2. 在同一情景内做 generic vs government 的完全交互模型，
       交互项系数即 treatment 效应（核心参数）；
    3. 在 government 条件下再做 CN vs US 的法域交互（探索性）。

输出：
    outputs/tables/amce_by_cell.csv           分单元 AMCE
    outputs/tables/amce_treatment_effect.csv  条件交互（treatment 效应）
    outputs/tables/amce_jurisdiction_effect.csv
    outputs/figures/amce_*.png

用法：python source/analysis/02_conjoint_amce.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    OUTPUTS_FIGURES,
    attribute_metadata,
    ensure_dirs,
    estimate_amce,
    plot_amce,
    read_table,
    save_table,
)


def main() -> int:
    ensure_dirs()
    option_long = read_table("choice_option_long")
    metadata = attribute_metadata()
    print(f"载入 choice_option_long：{len(option_long)} 行")

    usable = option_long[option_long["chosen"].notna()].copy()

    # --- 1) 分单元 AMCE -----------------------------------------------------
    cell_tables: list[pd.DataFrame] = []
    for keys, group in usable.groupby(["model_key", "condition", "scenario", "jurisdiction"]):
        model_key, condition, scenario, jurisdiction = keys
        table = estimate_amce(
            group, metadata, scenario, cluster_column="task_signature_pair"
        )
        if table.empty:
            print(f"[skip] {keys}：样本不足或设计矩阵缺列")
            continue
        table.insert(0, "model_key", model_key)
        table.insert(1, "condition", condition)
        table.insert(2, "jurisdiction", jurisdiction)
        cell_tables.append(table)

    if not cell_tables:
        print("没有可估计的单元。")
        return 0

    amce_all = pd.concat(cell_tables, ignore_index=True)
    save_table(amce_all, "amce_by_cell")
    print(f"amce_by_cell.csv：{len(amce_all)} 行")

    for (model_key, condition), group in amce_all.groupby(["model_key", "condition"]):
        path = OUTPUTS_FIGURES / f"amce_{model_key}_{condition}.png"
        plot_amce(group, f"AMCE · {model_key} · {condition}", path)
        print(f"figures：{path.name}")

    # --- 2) Treatment 效应（generic -> government）--------------------------
    treatment_tables: list[pd.DataFrame] = []
    for model_key, group in usable.groupby("model_key"):
        for scenario in sorted(group["scenario"].unique()):
            subset = group[group["scenario"] == scenario]
            if subset["condition"].nunique() < 2:
                print(f"[skip] treatment：{model_key}/{scenario} 只有一个条件")
                continue
            # generic 与 government 的 CN/US 都会进入比较；先整体看，再分法域
            table = estimate_amce(
                subset,
                metadata,
                scenario,
                cluster_column="task_signature_pair",
                interact_column="condition",
                interact_value="government",
            )
            if table.empty:
                continue
            table.insert(0, "model_key", model_key)
            table.insert(1, "comparison", "generic_vs_government_all_jurisdictions")
            treatment_tables.append(table)

            # 只在 government 内部区分法域意义有限（generic 没有法域），
            # 因此法域效应单独放到第 3 步估计。
    if treatment_tables:
        treatment = pd.concat(treatment_tables, ignore_index=True)
        save_table(treatment, "amce_treatment_effect")
        print(f"amce_treatment_effect.csv：{len(treatment)} 行")
        interactions = treatment[treatment["term_type"] == "interaction"]
        if not interactions.empty:
            path = OUTPUTS_FIGURES / "amce_treatment_interactions.png"
            plot_amce(
                interactions.assign(term_type="amce"),
                "Treatment 效应：government 相对 generic 的 AMCE 变化",
                path,
            )
            print(f"figures：{path.name}")

    # --- 3) 法域效应（government 内部 CN vs US）-----------------------------
    government = usable[usable["condition"] == "government"]
    jurisdiction_tables: list[pd.DataFrame] = []
    if not government.empty and government["jurisdiction"].nunique() > 1:
        for model_key, group in government.groupby("model_key"):
            for scenario in sorted(group["scenario"].unique()):
                subset = group[group["scenario"] == scenario]
                if subset["jurisdiction"].nunique() < 2:
                    continue
                table = estimate_amce(
                    subset,
                    metadata,
                    scenario,
                    cluster_column="task_signature_pair",
                    interact_column="jurisdiction",
                    interact_value="US",
                )
                if table.empty:
                    continue
                table.insert(0, "model_key", model_key)
                jurisdiction_tables.append(table)
        if jurisdiction_tables:
            jurisdiction = pd.concat(jurisdiction_tables, ignore_index=True)
            save_table(jurisdiction, "amce_jurisdiction_effect")
            print(f"amce_jurisdiction_effect.csv：{len(jurisdiction)} 行")

    # --- 4) 控制台摘要 ------------------------------------------------------
    print("\n=== AMCE 摘要（term_type=amce，按 |估计值| 排序前 15）===")
    top = (
        amce_all[amce_all["term_type"] == "amce"]
        .assign(abs_estimate=lambda frame: frame["estimate"].abs())
        .sort_values("abs_estimate", ascending=False)
        .head(15)
    )
    print(
        top[["model_key", "condition", "scenario", "attribute", "level", "estimate", "std_error", "pvalue"]]
        .round(4)
        .to_string(index=False)
    )

    if "amce_treatment_effect" in locals():
        print("\n=== Treatment 效应（交互项）===")
        interaction_rows = treatment[treatment["term_type"] == "interaction"]
        print(
            interaction_rows[
                ["model_key", "scenario", "attribute", "level", "estimate", "std_error", "pvalue"]
            ]
            .round(4)
            .to_string(index=False)
        )
        significant = interaction_rows[interaction_rows["pvalue"] < 0.05]
        print(f"\n显著交互项（p<0.05）：{len(significant)}/{len(interaction_rows)}")

    print("\nAMCE 分析完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
