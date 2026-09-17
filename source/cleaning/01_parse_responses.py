"""清洗 01 · 解析原始响应，生成 choice panel。

输入：data/raw/responses/{run_id}__{session}.jsonl（原始响应，只读）
输出：outputs/data/choice_panel.{parquet,csv}    每次调用一行，含解析结果
      outputs/other/parse_audit_sample.csv       随机抽取的待人工核对样本
      outputs/tables/parse_quality_summary.csv   解析质量汇总

用法：
    python source/cleaning/01_parse_responses.py
    python source/cleaning/01_parse_responses.py --run-id 2026-10-05_deepseek_main
    python source/cleaning/01_parse_responses.py --audit-size 300
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    OUTPUTS_OTHER,
    OUTPUTS_TABLES,
    die,
    ensure_dirs,
    load_responses,
    prompt_archive,
    write_table,
)
from _parse_lib import count_frameworks, parse_choice  # noqa: E402

PARSE_COLUMNS = [
    "choice_parsed",
    "parse_method",
    "parse_confidence",
    "mentions_a",
    "mentions_b",
    "is_refusal",
    "explanation_text",
    "explanation_words",
    "explanation_chars",
    "choice_sentence",
    "is_truncated",
    "is_usable",
    "chose_a",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="解析模型响应为 choice panel")
    parser.add_argument("--run-id", default=None, help="只处理某个 run（默认全部）")
    parser.add_argument("--audit-size", type=int, default=200, help="人工核对样本量")
    parser.add_argument("--audit-seed", type=int, default=20261001)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dirs()

    frame = load_responses(args.run_id)
    if frame.empty:
        die(
            "没有找到任何响应文件。先运行采集：\n"
            "  python data/collection/03_run_experiment.py --run-id <id> --session morning"
        )

    protocol = (
        str(frame["answer_protocol"].dropna().iloc[0]) if "answer_protocol" in frame else "free_text"
    )
    print(f"载入 {len(frame)} 条响应，答案协议 = {protocol}")

    raw_text = frame.get("response_raw", pd.Series([""] * len(frame))).fillna("")
    parsed = [parse_choice(text, protocol) for text in raw_text]
    parsed_frame = pd.DataFrame([item.as_dict() for item in parsed])
    parsed_frame.columns = [
        "choice_parsed",
        "parse_method",
        "parse_confidence",
        "mentions_a",
        "mentions_b",
        "is_refusal",
        "explanation_words",
        "explanation_chars",
        "choice_sentence",
    ]
    parsed_frame["explanation_text"] = raw_text.values
    parsed_frame["is_truncated"] = (
        frame.get("finish_reason", pd.Series([None] * len(frame))).fillna("").eq("length")
    )
    # 可用样本：解析出 A/B，且不是截断导致的半截回答
    parsed_frame["is_usable"] = parsed_frame["choice_parsed"].notna() & ~parsed_frame["is_truncated"]
    # chose_a：1 = 选了甲，0 = 选了乙，缺失 = 无法解析
    parsed_frame["chose_a"] = parsed_frame["choice_parsed"].map({"A": 1, "B": 0})

    # 文本框架词频（第二部分的文本分析直接用，避免重复读大文本）
    framework_names = list(count_frameworks("").keys())
    framework_counts = [count_frameworks(text) for text in raw_text]
    for framework in framework_names:
        parsed_frame[f"fw_{framework}"] = [item[framework] for item in framework_counts]

    panel = pd.concat([frame.reset_index(drop=True), parsed_frame[PARSE_COLUMNS + [c for c in parsed_frame.columns if c.startswith("fw_")]]], axis=1)

    written = write_table(panel, "choice_panel")
    print(f"choice panel 已写入：{', '.join(str(p.name) for p in written)}")

    # --- 解析质量汇总 -------------------------------------------------------
    summary_rows = []
    total = len(panel)
    summary_rows.append({"metric": "n_calls", "value": total})
    summary_rows.append({"metric": "n_usable", "value": int(panel["is_usable"].sum())})
    summary_rows.append(
        {"metric": "usable_share", "value": round(float(panel["is_usable"].mean()), 4)}
    )
    summary_rows.append(
        {"metric": "unparsed_share", "value": round(float(panel["choice_parsed"].isna().mean()), 4)}
    )
    summary_rows.append(
        {"metric": "refusal_share", "value": round(float(panel["is_refusal"].mean()), 4)}
    )
    summary_rows.append(
        {"metric": "truncated_share", "value": round(float(panel["is_truncated"].mean()), 4)}
    )
    for method, count in panel["parse_method"].value_counts().items():
        summary_rows.append({"metric": f"method::{method}", "value": int(count)})
    if "condition" in panel.columns:
        for condition, group in panel.groupby("condition"):
            summary_rows.append(
                {
                    "metric": f"usable_share::{condition}",
                    "value": round(float(group["is_usable"].mean()), 4),
                }
            )

    summary = pd.DataFrame(summary_rows)
    OUTPUTS_TABLES.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUTPUTS_TABLES / "parse_quality_summary.csv", index=False, encoding="utf-8-sig")

    print("\n解析质量：")
    for row in summary_rows:
        print(f"  {row['metric']:<28} {row['value']}")

    # --- 人工核对样本 -------------------------------------------------------
    if args.audit_size > 0 and len(panel):
        sample = panel.sample(
            n=min(args.audit_size, len(panel)), random_state=args.audit_seed
        )
        audit_columns = [
            column
            for column in [
                "run_id",
                "task_id",
                "condition",
                "scenario",
                "jurisdiction",
                "session_label",
                "choice_parsed",
                "parse_method",
                "parse_confidence",
                "explanation_text",
                "choice_sentence",
            ]
            if column in sample.columns
        ]
        audit = sample[audit_columns].copy()
        if "explanation_text" in audit:
            audit["explanation_text"] = audit["explanation_text"].astype(str).str.slice(0, 600)
        audit["human_check_choice"] = ""
        audit["human_check_note"] = ""
        audit.to_csv(OUTPUTS_OTHER / "parse_audit_sample.csv", index=False, encoding="utf-8-sig")
        print(
            f"\n人工核对样本已写入：{OUTPUTS_OTHER / 'parse_audit_sample.csv'}"
            f"（{len(audit)} 条；请在 human_check_choice 列填 A/B/wrong，"
            f"据此计算解析准确率并写进论文附录）"
        )

    archive = prompt_archive()
    if archive:
        print(f"\n提示词前缀归档：{len(archive)} 条（法规全文只存一份，见 _prompt_archive.jsonl）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
