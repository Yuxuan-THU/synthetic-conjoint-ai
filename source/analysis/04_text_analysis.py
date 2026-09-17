"""分析 04 · 解释文本分析（论文第二部分）。

三个层次，由浅到深：
    1. 描述性：解释长度、是否超 50 词、拒答比例，按条件对比；
    2. 框架词频：安全 / 责任 / 效率 / 法规 / 伦理 等话语框架的分布差异；
    3. 结构化编码：用固定版本的外部模型对解释文本做编码（可选，默认关闭，
       因为会产生额外 API 成本并引入第二个模型——必须显式开启并在论文中披露）。

输出：
    outputs/tables/text_descriptives.csv
    outputs/tables/text_frameworks.csv
    outputs/tables/text_framework_contrasts.csv
    outputs/tables/text_llm_coding.csv              （仅在开启编码时）
    outputs/figures/text_frameworks.png

用法：
    python source/analysis/04_text_analysis.py
    python source/analysis/04_text_analysis.py --llm-coding --coding-model deepseek-chat --coding-limit 400
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    OUTPUTS_FIGURES,
    OUTPUTS_OTHER,
    ensure_dirs,
    read_table,
    setup_matplotlib,
    save_table,
)

FRAMEWORK_DESCRIPTIONS = {
    "fw_safety": "安全与风险",
    "fw_casualties": "平民伤亡",
    "fw_accountability": "责任与监督",
    "fw_efficiency": "效率与时效",
    "fw_accuracy": "准确性与误差",
    "fw_law_regulation": "法规与合规",
    "fw_ethics_rights": "伦理与权利",
    "fw_institution": "机构属性",
    "fw_cost": "成本资源",
    "fw_trust": "公众信任",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="解释文本分析")
    parser.add_argument("--llm-coding", action="store_true", help="开启外部模型结构化编码")
    parser.add_argument("--coding-model", default="deepseek-chat")
    parser.add_argument("--coding-limit", type=int, default=400, help="编码的文本条数上限")
    parser.add_argument("--coding-seed", type=int, default=20261001)
    return parser.parse_args()


def text_descriptives(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    keys = [
        key
        for key in ["model_key", "condition", "scenario", "jurisdiction"]
        if key in panel.columns
    ]
    for group_keys, group in panel.groupby(keys, dropna=False):
        group_keys = group_keys if isinstance(group_keys, tuple) else (group_keys,)
        record = dict(zip(keys, group_keys))
        usable = group[group["choice_parsed"].notna()]
        record.update(
            {
                "n_responses": len(group),
                "n_usable": len(usable),
                "mean_words": round(float(usable["explanation_words"].mean()), 2)
                if len(usable)
                else None,
                "median_words": float(usable["explanation_words"].median()) if len(usable) else None,
                "share_over_50_words": round(float((usable["explanation_words"] > 50).mean()), 4)
                if len(usable)
                else None,
                "share_empty": round(float((group["explanation_chars"] == 0).mean()), 4),
                "share_refusal": round(float(group["is_refusal"].mean()), 4)
                if "is_refusal" in group
                else None,
                "share_limit_jurisdiction_mentioned": round(
                    float(usable["explanation_text"].astype(str).str.lower().str.contains(
                        "national people's congress|health commission", regex=True
                    ).mean()),
                    4,
                )
                if len(usable)
                else None,
            }
        )
        rows.append(record)
    return pd.DataFrame(rows)


def framework_table(panel: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in panel.columns if column.startswith("fw_")]
    if not columns:
        return pd.DataFrame()
    usable = panel[panel["choice_parsed"].notna()].copy()
    keys = [key for key in ["model_key", "condition", "scenario"] if key in usable.columns]
    aggregated = usable.groupby(keys, dropna=False)[columns].mean().reset_index()
    aggregated = aggregated.rename(columns=FRAMEWORK_DESCRIPTIONS)
    return aggregated


def framework_contrasts(panel: pd.DataFrame) -> pd.DataFrame:
    """每个框架在 government vs generic 之间的差异检验。"""
    from scipy import stats

    columns = [column for column in panel.columns if column.startswith("fw_")]
    usable = panel[panel["choice_parsed"].notna()]
    rows: list[dict[str, object]] = []
    for scenario, group in usable.groupby("scenario"):
        generic = group[group["condition"] == "generic"]
        government = group[group["condition"] == "government"]
        if generic.empty or government.empty:
            continue
        for column in columns:
            a = generic[column].astype(float)
            b = government[column].astype(float)
            t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)
            rows.append(
                {
                    "scenario": scenario,
                    "framework": FRAMEWORK_DESCRIPTIONS.get(column, column),
                    "mean_generic": round(float(a.mean()), 4),
                    "mean_government": round(float(b.mean()), 4),
                    "difference": round(float(b.mean() - a.mean()), 4),
                    "t_statistic": round(float(t_stat), 4) if np.isfinite(t_stat) else None,
                    "pvalue": round(float(p_value), 6) if np.isfinite(p_value) else None,
                    "n_generic": int(len(a)),
                    "n_government": int(len(b)),
                }
            )
    return pd.DataFrame(rows)


CODING_SYSTEM_PROMPT = (
    "You are a careful research assistant coding short explanations written by an AI "
    "decision-support system. Code only what the text explicitly says. Return a JSON object "
    "with these keys: cites_regulation (true/false: does it cite or reference regulations, "
    "laws, or official guidance?), tradeoff_stated (true/false: does it explicitly weigh a "
    "trade-off?), priority_theme (one of: safety, accountability, efficiency, accuracy, "
    "institution, cost, trust, other), self_consistent (true/false: does the stated reason "
    "support the stated choice?)."
)


def llm_coding(panel: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    """用外部模型对解释文本做结构化编码（默认关闭）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data" / "collection"))
    from _llm import config as collection_config  # noqa: E402
    from _llm import providers  # noqa: E402

    models_config = collection_config.load_models_config()
    model_config = (models_config["models"] or {}).get(args.coding_model)
    if not model_config:
        print(f"[skip] models.yaml 中没有 {args.coding_model}")
        return pd.DataFrame()

    usable = panel[panel["choice_parsed"].notna()].copy()
    if len(usable) > args.coding_limit:
        usable = usable.sample(n=args.coding_limit, random_state=args.coding_seed)

    api_config = dict(models_config.get("api_defaults", {}))
    rows: list[dict[str, object]] = []
    for index, row in enumerate(usable.itertuples(index=False), start=1):
        record = row._asdict()
        text = str(record.get("explanation_text", ""))[:1500]
        choice = record.get("choice_parsed")
        user_prompt = f"The system chose {choice}. Its explanation:\n\n{text}"
        try:
            response = providers.chat(
                args.coding_model, model_config, api_config, CODING_SYSTEM_PROMPT, user_prompt
            )
            payload = response.text
        except Exception as exc:  # noqa: BLE001 - 编码失败不应中断整个分析
            payload = f'{{"error": "{type(exc).__name__}: {exc}"}}'
        rows.append(
            {
                "task_id": record.get("task_id"),
                "cell_id": record.get("cell_id"),
                "condition": record.get("condition"),
                "scenario": record.get("scenario"),
                "choice_parsed": choice,
                "coding_model": args.coding_model,
                "coding_raw": payload,
            }
        )
        if index % 50 == 0:
            print(f"  编码进度 {index}/{len(usable)}")

    coded = pd.DataFrame(rows)
    import json

    def _extract(payload: str, key: str) -> object:
        try:
            return json.loads(payload).get(key)
        except Exception:  # noqa: BLE001
            return None

    for key in ("cites_regulation", "tradeoff_stated", "self_consistent", "priority_theme"):
        coded[f"code_{key}"] = coded["coding_raw"].map(lambda value, k=key: _extract(value, k))
    return coded


def plot_frameworks(frameworks: pd.DataFrame) -> None:
    if frameworks.empty:
        return
    import matplotlib.pyplot as plt

    setup_matplotlib()

    theme_columns = list(FRAMEWORK_DESCRIPTIONS.values())
    available = [column for column in theme_columns if column in frameworks.columns]
    if not available:
        return
    frame = frameworks.copy()
    frame["label"] = frame["condition"].astype(str) + "\n" + frame["scenario"].astype(str)
    fig, axis = plt.subplots(figsize=(max(8, 1.1 * len(frame)), 4.5))
    bottom = np.zeros(len(frame))
    for column in available:
        axis.bar(frame["label"], frame[column], bottom=bottom, label=column)
        bottom += frame[column].to_numpy()
    axis.set_ylabel("每次解释的平均提及次数")
    axis.set_title("解释文本的话语框架分布")
    axis.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    path = OUTPUTS_FIGURES / "text_frameworks.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"figures：{path.name}")


def main() -> int:
    args = parse_args()
    ensure_dirs()
    panel = read_table("choice_panel")
    print(f"载入 choice_panel：{len(panel)} 行")

    descriptives = text_descriptives(panel)
    if not descriptives.empty:
        save_table(descriptives, "text_descriptives")
        print(f"text_descriptives.csv：{len(descriptives)} 行")

    frameworks = framework_table(panel)
    if not frameworks.empty:
        save_table(frameworks, "text_frameworks")
        plot_frameworks(frameworks)
        print(f"text_frameworks.csv：{len(frameworks)} 行")

    contrasts = framework_contrasts(panel)
    if not contrasts.empty:
        save_table(contrasts, "text_framework_contrasts")
        print("\n=== generic vs government 的框架差异（按 |difference| 排序）===")
        print(
            contrasts.assign(abs_diff=lambda frame: frame["difference"].abs())
            .sort_values("abs_diff", ascending=False)
            .head(12)[["scenario", "framework", "mean_generic", "mean_government", "difference", "pvalue"]]
            .to_string(index=False)
        )

    if args.llm_coding:
        coded = llm_coding(panel, args)
        if not coded.empty:
            save_table(coded, "text_llm_coding")
            OUTPUTS_OTHER.mkdir(parents=True, exist_ok=True)
            coded.to_csv(
                OUTPUTS_OTHER / "text_llm_coding_raw.csv", index=False, encoding="utf-8-sig"
            )
            share = coded["code_cites_regulation"].astype(str).str.lower().eq("true")
            print(f"\nLLM 编码：{len(coded)} 条，其中引用法规的比例 = {share.mean():.2%}")
            print("注意：该结果依赖外部编码模型，须在论文中披露模型版本与编码提示词。")
    else:
        print(
            "\n（未开启 LLM 编码。若要开启：--llm-coding，会产生额外 API 成本，"
            "并需要在论文中披露第二个模型的版本与提示词。）"
        )

    print("\n文本分析完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
