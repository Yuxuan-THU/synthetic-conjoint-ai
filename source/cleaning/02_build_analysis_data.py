"""清洗 02 · 构造分析数据（长表 + 重复任务分组）。

输入：outputs/data/choice_panel.{parquet,csv}、data/raw/design/attribute_metadata.csv
输出：outputs/data/choice_long.{parquet,csv}     一次调用 × 一个属性一行（AMCE 回归用）
      outputs/data/choice_option_long.{parquet,csv}  一次调用 × 一个方案 × 一个属性一行
      outputs/data/duplicate_groups.csv          自然重复任务的分组
      outputs/tables/analysis_sample_summary.csv 分析样本构成

用法：
    python source/cleaning/02_build_analysis_data.py
    python source/cleaning/02_build_analysis_data.py --drop-duplicates   # 剔除重复抽取的任务
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    OUTPUTS_TABLES,
    attribute_metadata,
    die,
    ensure_dirs,
    read_table,
    write_table,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构造 conjoint 分析数据")
    parser.add_argument(
        "--drop-duplicates",
        action="store_true",
        help="剔除同一单元内完全相同的重复任务（只保留首次出现），用于稳健性检验",
    )
    parser.add_argument("--run-id", default=None, help="只保留某个 run")
    return parser.parse_args()


def build_long(panel: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    """把宽表熔成 (调用 × 属性) 长表。

    关键字段：
        attribute, level_a, level_b        该属性上甲乙两方案的取值
        chose_a                            1 = 选了甲，0 = 选了乙
        is_risk_attribute / direction       画图与解读顺序用
    """
    attributes = (
        metadata[["scenario", "attribute_id", "attribute_label_en", "higher_is_better"]]
        .drop_duplicates()
        .set_index(["scenario", "attribute_id"])
    )

    records: list[dict[str, Any]] = []
    base_columns = [
        column
        for column in [
            "run_id",
            "call_index",
            "session_label",
            "model_key",
            "condition",
            "scenario",
            "jurisdiction",
            "cell_id",
            "task_id",
            "task_kind",
            "task_index",
            "repeat_index",
            "task_signature",
            "task_signature_pair",
            "task_signature_unordered",
            "choice_parsed",
            "is_usable",
            "parse_method",
            "parse_confidence",
            "explanation_words",
            "requested_at_bj",
            "latency_ms",
        ]
        if column in panel.columns
    ]

    for row in panel.itertuples(index=False):
        row_dict = row._asdict()
        scenario = row_dict["scenario"]
        scenario_attributes = [
            column[3:]
            for column in row_dict
            if column.startswith("a__") and column[3:] in attributes.loc[scenario].index
        ]
        for attribute_id in scenario_attributes:
            level_a = row_dict[f"a__{attribute_id}"]
            level_b = row_dict[f"b__{attribute_id}"]
            meta = attributes.loc[(scenario, attribute_id)]
            record = {column: row_dict[column] for column in base_columns}
            record.update(
                {
                    "attribute": attribute_id,
                    "attribute_label_en": meta["attribute_label_en"],
                    "higher_is_better": meta["higher_is_better"],
                    "level_a": level_a,
                    "level_b": level_b,
                    "chose_a": (
                        None
                        if pd.isna(row_dict["choice_parsed"])
                        else int(row_dict["choice_parsed"] == "A")
                    ),
                }
            )
            records.append(record)
    return pd.DataFrame(records)


def build_option_long(long: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    """转成 (调用 × 方案 × 属性) 长表：AMCE 的标准输入格式。

    chosen = 1 表示该属性值出现在被选中的那个方案里。
    """
    level_labels = (
        metadata.set_index(["scenario", "attribute_id", "level_id"])["level_label_en"].to_dict()
    )
    option_rows: list[dict[str, Any]] = []
    for row in long.itertuples(index=False):
        record = row._asdict()
        if record["chose_a"] is None:
            continue
        for option, level_key in (("A", "level_a"), ("B", "level_b")):
            entry = dict(record)
            entry["option"] = option
            entry["level"] = entry.pop(level_key)
            entry["chosen"] = int(option == ("A" if record["chose_a"] == 1 else "B"))
            entry["is_option_a"] = int(option == "A")
            entry["level_label_en"] = level_labels.get(
                (entry["scenario"], entry["attribute"], entry["level"]), entry["level"]
            )
            option_rows.append(entry)
    return pd.DataFrame(option_rows)


def main() -> int:
    args = parse_args()
    ensure_dirs()

    try:
        panel = read_table("choice_panel")
    except FileNotFoundError:
        die("找不到 choice_panel，请先运行 source/cleaning/01_parse_responses.py")
    metadata = attribute_metadata()

    if args.run_id:
        panel = panel[panel["run_id"] == args.run_id].reset_index(drop=True)
        if panel.empty:
            die(f"run_id={args.run_id} 没有数据")

    total_calls = len(panel)
    usable = panel[panel["is_usable"]].copy()
    dropped = total_calls - len(usable)
    print(f"总调用 {total_calls}，可用 {len(usable)}，剔除 {dropped}")

    # 重复任务分组：同一 (cell, task_signature) 出现多次即为自然重复
    duplicate_columns = ["cell_id", "task_signature"]
    if set(duplicate_columns).issubset(usable.columns):
        usable["dup_rank"] = usable.groupby(duplicate_columns).cumcount()
        usable["dup_size"] = usable.groupby(duplicate_columns)["task_id"].transform("size")
        dup_groups = (
            usable[usable["dup_size"] > 1]
            .sort_values(duplicate_columns + ["dup_rank"])
            .copy()
        )
    else:
        dup_groups = pd.DataFrame()

    if args.drop_duplicates and not dup_groups.empty:
        before = len(usable)
        usable = usable[usable.get("dup_rank", 0) == 0].copy()
        print(f"--drop-duplicates：剔除 {before - len(usable)} 条重复任务")

    long = build_long(usable, metadata)
    option_long = build_option_long(long, metadata)

    for frame, stem in ((long, "choice_long"), (option_long, "choice_option_long")):
        written = write_table(frame, stem)
        print(f"{stem}: {len(frame)} 行 -> {', '.join(p.name for p in written)}")

    if not dup_groups.empty:
        dup_path = Path(OUTPUTS_TABLES).parent / "data" / "duplicate_groups.csv"
        dup_groups.to_csv(dup_path, index=False, encoding="utf-8-sig")
        print(f"duplicate_groups: {len(dup_groups)} 行 -> {dup_path.name}")

    # --- 样本构成汇总 -------------------------------------------------------
    summary_rows: list[dict[str, Any]] = []
    for keys, group in usable.groupby(["model_key", "condition", "scenario", "jurisdiction"]):
        model_key, condition, scenario, jurisdiction = keys
        summary_rows.append(
            {
                "model_key": model_key,
                "condition": condition,
                "scenario": scenario,
                "jurisdiction": jurisdiction,
                "n_calls": len(group),
                "n_anchor": int((group["task_kind"] == "anchor").sum())
                if "task_kind" in group
                else 0,
                "share_choose_a": round(float((group["choice_parsed"] == "A").mean()), 4),
                "n_sessions": group["session_label"].nunique()
                if "session_label" in group
                else 0,
                "n_duplicate_tasks": int((group["dup_size"] > 1).sum())
                if "dup_size" in group
                else 0,
            }
        )
    summary = pd.DataFrame(summary_rows)
    OUTPUTS_TABLES.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUTPUTS_TABLES / "analysis_sample_summary.csv", index=False, encoding="utf-8-sig")
    print("\n样本构成：")
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
