"""01 · 生成并冻结随机任务矩阵（设计矩阵）。

职责划分（research-project-template）：
    本脚本属于 data/collection —— 它生产"研究工具"（问卷的随机化实现），
    产物写入 data/raw/design/，此后只读；清洗与分析脚本一律读该产物，
    不再重新生成任务，保证"跑过的任务不可被静默改变"。

产物：
    data/raw/design/attribute_metadata.csv          属性/水平字典（供分析脚本使用）
    data/raw/design/{run_id}__tasks__{scenario}.csv 主任务 + 锚点任务（每情景一份）
    data/raw/design/{run_id}__session_plan.csv      单元 × 时段的任务索引区间与配额
    data/raw/design/{run_id}__design_manifest.json  种子、配置指纹、设计诊断统计

用法：
    python data/collection/01_build_design_matrix.py --run-id 2026-10-05_deepseek_main
    python data/collection/01_build_design_matrix.py --run-id <id> --scenario border_defense
    python data/collection/01_build_design_matrix.py --run-id <id> --force   # 覆盖重建（危险）
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _llm import config as cfg  # noqa: E402
from _llm.design import (  # noqa: E402
    CellPlan,
    Scenario,
    Task,
    anchor_plan,
    build_cell_plans,
    load_scenarios,
    sample_task,
)
from _llm.io_utils import iso_beijing, now_utc, write_json  # noqa: E402

ATTRIBUTE_METADATA_COLUMNS = [
    "scenario",
    "attribute_id",
    "attribute_label_en",
    "higher_is_better",
    "level_id",
    "level_label_en",
    "dominance_rank",
    "level_index",
]

TASK_COLUMNS = [
    "run_id",
    "cell_id",
    "condition",
    "scenario",
    "jurisdiction",
    "task_kind",
    "task_id",
    "task_index",
    "repeat_index",
    "seed",
    "attribute_order",
    "a_dominates",
    "b_dominates",
    "task_signature",
    "task_signature_pair",
    "task_signature_unordered",
]


# --- 校验 -------------------------------------------------------------------


def validate_task(scenario: Scenario, task: Task) -> list[str]:
    """逐条落实 docx 批注的硬约束；返回违规描述列表（空列表 = 通过）。"""
    problems: list[str] = []

    # 约束：对每一个性能特征，两种方案的随机值必须不同
    for attribute in scenario.attributes:
        if task.option_a[attribute.id] == task.option_b[attribute.id]:
            problems.append(
                f"{task.task_id}: 属性 {attribute.id} 上甲==乙（{task.option_a[attribute.id]}）"
            )

    # 约束：五个属性各出现且仅出现一次
    if sorted(task.attribute_order) != sorted(scenario.attribute_ids):
        problems.append(f"{task.task_id}: 属性行序不是完整排列：{task.attribute_order}")

    # 取值必须落在配置的水平集合内
    for attribute in scenario.attributes:
        for option in ("A", "B"):
            level_id = task.level_id(option, attribute.id)
            if level_id not in attribute.level_ids:
                problems.append(
                    f"{task.task_id}: 属性 {attribute.id} 的方案{option} 出现未知水平 {level_id}"
                )
    return problems


def task_row(
    task: Task,
    scenario: Scenario,
    run_id: str,
    condition: str,
    jurisdiction: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": run_id,
        "cell_id": task.cell_id,
        "condition": condition,
        "scenario": scenario.id,
        "jurisdiction": jurisdiction or "",
        "task_kind": task.task_kind,
        "task_id": task.task_id,
        "task_index": task.task_index,
        "repeat_index": task.repeat_index,
        "seed": task.seed,
        "attribute_order": ">".join(task.attribute_order),
        "a_dominates": int(task.a_dominates),
        "b_dominates": int(task.b_dominates),
        "task_signature": task.task_signature,
        "task_signature_pair": task.task_signature_pair,
        "task_signature_unordered": task.task_signature_unordered,
    }
    for attribute in scenario.attributes:
        row[f"a__{attribute.id}"] = task.option_a[attribute.id]
        row[f"b__{attribute.id}"] = task.option_b[attribute.id]
    return row


# --- 诊断 -------------------------------------------------------------------


def design_diagnostics(
    scenario: Scenario, tasks: list[Task]
) -> dict[str, Any]:
    """随机化质量诊断：有序对均匀性 + 被支配方案占比。"""
    main_tasks = [task for task in tasks if task.task_kind == "main"]
    n_main = len(main_tasks)

    per_attribute: dict[str, Any] = {}
    for attribute in scenario.attributes:
        counter: Counter[tuple[str, str]] = Counter()
        for task in main_tasks:
            counter[(task.option_a[attribute.id], task.option_b[attribute.id])] += 1
        expected = n_main / 6 if n_main else 0.0
        chi_square = (
            sum((count - expected) ** 2 / expected for count in counter.values())
            if expected
            else 0.0
        )
        per_attribute[attribute.id] = {
            "n_observed_pairs": len(counter),
            "n_possible_pairs": 6,
            "expected_per_pair": round(expected, 2),
            "chi_square_df5": round(chi_square, 3),
            "chi_square_critical_p01_df5": 15.086,
            "pairs": {f"{a}->{b}": c for (a, b), c in sorted(counter.items())},
        }

    attribute_order_counter = Counter(task.attribute_order for task in main_tasks)
    dominated = sum(
        1 for task in main_tasks if task.a_dominates or task.b_dominates
    )
    n_attributes = len(scenario.attributes)
    spaces = {
        "presented_screen": 6 ** n_attributes * _factorial(n_attributes),
        "ordered_pair": 6 ** n_attributes,
        "unordered_pair": 3 ** n_attributes,
    }
    observed = {
        "presented_screen": len({task.task_signature for task in main_tasks}),
        "ordered_pair": len({task.task_signature_pair for task in main_tasks}),
        "unordered_pair": len({task.task_signature_unordered for task in main_tasks}),
    }
    expected_distinct = {
        name: round(
            space * (1 - (1 - 1 / space) ** n_main) if n_main else 0.0, 2
        )
        for name, space in spaces.items()
    }

    return {
        "n_main_tasks": n_main,
        "n_attributes": n_attributes,
        "space_sizes": spaces,
        "n_distinct_observed": observed,
        "n_distinct_expected": expected_distinct,
        "n_duplicate_observed": {
            name: n_main - count for name, count in observed.items()
        },
        "n_duplicate_expected": {
            name: round(n_main - expected_distinct[name], 2) for name in spaces
        },
        "n_distinct_attribute_orders": len(attribute_order_counter),
        "n_possible_attribute_orders": _factorial(n_attributes),
        "share_dominated_task_screens": round(dominated / n_main, 4) if n_main else None,
        "n_dominated_task_screens": dominated,
        "per_attribute_randomisation": per_attribute,
    }


def _factorial(n: int) -> int:
    value = 1
    for i in range(2, n + 1):
        value *= i
    return value


# --- 主流程 -----------------------------------------------------------------


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成并冻结 conjoint 随机任务矩阵")
    parser.add_argument("--run-id", required=True, help="运行标识，任务种子由它派生")
    parser.add_argument("--condition", action="append", default=None, choices=["generic", "government"])
    parser.add_argument("--scenario", action="append", default=None)
    parser.add_argument("--jurisdiction", action="append", default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="已有设计矩阵时强制重建（会改变已跑数据的任务对应关系，慎用）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    experiment = cfg.load_experiment_config()
    scenarios = load_scenarios()
    cfg.ensure_output_dirs()

    selected_scenarios = args.scenario or list(experiment["cells"]["scenarios"])
    unknown = [s for s in selected_scenarios if s not in scenarios]
    if unknown:
        raise SystemExit(f"未知情景：{unknown}；可选：{sorted(scenarios)}")

    manifest_path = cfg.DESIGN_DIR / f"{args.run_id}__design_manifest.json"
    task_paths = {
        scenario_id: cfg.DESIGN_DIR / f"{args.run_id}__tasks__{scenario_id}.csv"
        for scenario_id in selected_scenarios
    }
    existing = [p for p in [*task_paths.values()] if p.exists()]
    if existing and not args.force:
        raise SystemExit(
            "设计矩阵已存在，拒绝覆盖：\n  "
            + "\n  ".join(str(p) for p in existing)
            + "\n如需重建请加 --force（并换用新的 run-id 更安全）。"
        )

    plans: list[CellPlan] = build_cell_plans(
        experiment,
        conditions=args.condition,
        scenarios=selected_scenarios,
        jurisdictions=args.jurisdiction,
    )

    all_rows: dict[str, list[dict[str, Any]]] = {sid: [] for sid in selected_scenarios}
    session_plan_rows: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    violations: list[str] = []
    total_main = 0
    total_anchor = 0

    for plan in plans:
        scenario = scenarios[plan.scenario_id]
        cell_tasks: list[Task] = []

        # 主任务
        for index in range(plan.n_tasks):
            task = sample_task(
                scenario,
                run_id=args.run_id,
                cell_id=plan.cell_id,
                task_kind="main",
                task_index=index,
            )
            violations.extend(validate_task(scenario, task))
            cell_tasks.append(task)
            all_rows[plan.scenario_id].append(
                task_row(task, scenario, args.run_id, plan.condition, plan.jurisdiction)
            )
        total_main += plan.n_tasks

        # 锚点任务
        anchors = anchor_plan(experiment, plan)
        for anchor_index, repeat_index, _session in anchors:
            task = sample_task(
                scenario,
                run_id=args.run_id,
                cell_id=plan.cell_id,
                task_kind="anchor",
                task_index=anchor_index,
                repeat_index=repeat_index,
            )
            violations.extend(validate_task(scenario, task))
            cell_tasks.append(task)
            all_rows[plan.scenario_id].append(
                task_row(task, scenario, args.run_id, plan.condition, plan.jurisdiction)
            )
        total_anchor += len(anchors)

        for session in experiment["sessions"]:
            label = str(session["label"])
            start, end = plan.task_index_range(label)
            session_plan_rows.append(
                {
                    "run_id": args.run_id,
                    "cell_id": plan.cell_id,
                    "condition": plan.condition,
                    "scenario": plan.scenario_id,
                    "jurisdiction": plan.jurisdiction or "",
                    "session_label": label,
                    "local_window": session.get("local_window", ""),
                    "task_index_start": start,
                    "task_index_end": end,
                    "n_tasks": end - start,
                    "n_anchor_calls": sum(1 for _, _, s in anchors if s == label),
                }
            )

        diagnostics[plan.cell_id] = design_diagnostics(scenario, cell_tasks)

    if violations:
        sample = "\n  ".join(violations[:10])
        raise SystemExit(
            f"设计矩阵校验失败，共 {len(violations)} 条违规（前 10 条）：\n  {sample}"
        )

    # --- 落盘 ---------------------------------------------------------------
    metadata_rows: list[dict[str, Any]] = []
    for scenario in scenarios.values():
        for attribute in scenario.attributes:
            for level_index, level in enumerate(attribute.levels):
                metadata_rows.append(
                    {
                        "scenario": scenario.id,
                        "attribute_id": attribute.id,
                        "attribute_label_en": attribute.label_en,
                        "higher_is_better": (
                            "" if attribute.higher_is_better is None else int(attribute.higher_is_better)
                        ),
                        "level_id": level.id,
                        "level_label_en": level.label_en,
                        "dominance_rank": "" if level.dominance_rank is None else level.dominance_rank,
                        "level_index": level_index,
                    }
                )
    write_csv(
        cfg.DESIGN_DIR / "attribute_metadata.csv",
        metadata_rows,
        ATTRIBUTE_METADATA_COLUMNS,
    )

    per_scenario_counts: dict[str, int] = {}
    for scenario_id, rows in all_rows.items():
        scenario = scenarios[scenario_id]
        columns = TASK_COLUMNS + [f"a__{a.id}" for a in scenario.attributes] + [
            f"b__{a.id}" for a in scenario.attributes
        ]
        write_csv(task_paths[scenario_id], rows, columns)
        per_scenario_counts[scenario_id] = len(rows)

    write_csv(
        cfg.DESIGN_DIR / f"{args.run_id}__session_plan.csv",
        session_plan_rows,
        [
            "run_id",
            "cell_id",
            "condition",
            "scenario",
            "jurisdiction",
            "session_label",
            "local_window",
            "task_index_start",
            "task_index_end",
            "n_tasks",
            "n_anchor_calls",
        ],
    )

    manifest = {
        "run_id": args.run_id,
        "created_at_beijing": iso_beijing(now_utc())[:19],
        "config_sha256": cfg.config_sha256(),
        "n_per_condition_scenario": experiment["cells"]["n_per_condition_scenario"],
        "jurisdiction_balance": experiment["cells"]["jurisdiction_balance"],
        "conditions": args.condition or experiment["cells"]["conditions"],
        "scenarios": selected_scenarios,
        "jurisdictions": args.jurisdiction or experiment["cells"]["jurisdictions"],
        "answer_protocol": experiment["answer_protocol"],
        "n_cells": len(plans),
        "n_main_calls": total_main,
        "n_anchor_calls": total_anchor,
        "n_calls_expected_total": total_main + total_anchor,
        "rows_per_scenario_file": per_scenario_counts,
        "cell_plans": [
            {
                "cell_id": plan.cell_id,
                "condition": plan.condition,
                "scenario": plan.scenario_id,
                "jurisdiction": plan.jurisdiction,
                "n_tasks": plan.n_tasks,
                "session_quotas": plan.session_quotas,
            }
            for plan in plans
        ],
        "diagnostics": diagnostics,
        "invariants_checked": [
            "同一属性上甲、乙取值不同",
            "属性行序为完整随机排列",
            "属性取值均来自配置水平集合",
        ],
        "notes": (
            "任务种子 = sha256(run_id | cell_id | task_kind | task_index) 取前 8 字节，"
            "因此同一 run_id 的设计矩阵可完全重放；锚点任务的各种重复共用同一任务（种子不含 repeat_index）。"
        ),
    }
    write_json(manifest_path, manifest)

    # --- 打印摘要 -----------------------------------------------------------
    print(f"run_id                : {args.run_id}")
    print(f"配置指纹 config_sha256 : {manifest['config_sha256'][:16]}…")
    print(f"设计单元 cells         : {len(plans)}")
    print(f"主任务调用数           : {total_main}")
    print(f"锚点调用数             : {total_anchor}")
    print(f"预计总调用数           : {total_main + total_anchor}")
    print("设计诊断（每单元）     :")
    for cell_id, stats in diagnostics.items():
        print(f"  - {cell_id}: n={stats['n_main_tasks']}, 被支配方案占比={stats['share_dominated_task_screens']}")
        for name in ("presented_screen", "ordered_pair", "unordered_pair"):
            print(
                f"      自然重复[{name:<17}] 观察={stats['n_duplicate_observed'][name]:<6}"
                f"期望={stats['n_duplicate_expected'][name]:<8}"
                f"（空间={stats['space_sizes'][name]}）"
            )
        for attribute_id, attr_stats in stats["per_attribute_randomisation"].items():
            flag = (
                "OK"
                if attr_stats["chi_square_df5"] < attr_stats["chi_square_critical_p01_df5"]
                else "偏斜(需结合多重比较解读)"
            )
            print(
                f"      {attribute_id:<22} chi2(df=5)={attr_stats['chi_square_df5']:<8} {flag}"
            )
    print(
        "\n说明：属性行序随机会把'呈现屏'空间放大 5!=120 倍，因此真正完全相同的呈现屏极少"
        "（自然重复不足 1 个），不能指望靠它做同任务一致性检验——这正是锚点任务存在的理由。"
        "'ordered_pair' 的自然重复约 60 个，可用于检验'同一对方案换一种属性行序是否给出相同选择'。"
    )
    print(f"\n设计矩阵已写入：{cfg.DESIGN_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
