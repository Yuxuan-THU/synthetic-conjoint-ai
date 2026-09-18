"""03 · 采集主运行器：向模型发送 conjoint 任务并落盘原始响应。

这是本项目的"数据采集"环节——等价于实施问卷、回收答卷。产物是
data/raw/responses/ 下的原始 JSONL，只追加、不重写。

设计要点（详见 docs/01_design-spec.md）：
    - 每次调用 memory-free：只有 system prompt + 单条 user 消息，不带历史。
    - 任务由 run_id 派生种子确定，断点续跑不会改变已跑过的任务。
    - 时段之间任务索引区间不重叠，因此 (run_id, task_id) 全局唯一。
    - 法规全文不写进每一行，而是归档到 _prompt_archive.jsonl（见 §6.1）。
    - 守卫检查：提示词未定稿时拒绝开跑（法规文本的确认门禁已于 2026-09-18 移除）。

用法：
    # 先看会发出去什么（不调用 API，不需要密钥）
    python data/collection/03_run_experiment.py --run-id <id> --dry-run

    # 冒烟测试：每个单元跑 2 次
    python data/collection/03_run_experiment.py --run-id <id>_smoke --session morning --limit 2

    # 正式：三个时段各触发一次
    python data/collection/03_run_experiment.py --run-id <id> --session morning
    python data/collection/03_run_experiment.py --run-id <id> --session afternoon
    python data/collection/03_run_experiment.py --run-id <id> --session evening
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _llm import config as cfg  # noqa: E402
from _llm import design as design_lib  # noqa: E402
from _llm import providers  # noqa: E402
from _llm import render as render_lib  # noqa: E402
from _llm.io_utils import (  # noqa: E402
    append_jsonl,
    beijing_hour,
    existing_keys,
    iso_beijing,
    iso_utc,
    iter_jsonl,
    now_utc,
    read_json,
    sha256_text,
    write_json,
)

SCENARIO_FILE_TEMPLATE = "{run_id}__tasks__{scenario}.csv"


@dataclass
class CallSpec:
    """一次待执行的模型调用。"""

    task: design_lib.Task
    plan: design_lib.CellPlan
    session_label: str


@dataclass
class RunContext:
    run_id: str
    session_label: str
    model_key: str
    model_config: Mapping[str, Any]
    api_config: Mapping[str, Any]
    answer_protocol: str
    language: str
    render_config: Mapping[str, Any]
    prompts_config: Mapping[str, Any]
    scenarios: dict[str, design_lib.Scenario]
    law_materials: dict[str, list[tuple[Mapping[str, Any], str]]]  # jurisdiction -> [(meta, text)]
    law_sha_by_id: dict[str, str]
    guards_skipped: bool
    session_file: Path
    error_file: Path
    archive_file: Path


# --- 参数与时段 -------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Conjoint 实验数据采集运行器")
    parser.add_argument("--run-id", required=True, help="运行标识；设计矩阵文件名的一部分")
    parser.add_argument("--model", default=None, help="models.yaml 中的模型键（默认取配置 default_model）")
    parser.add_argument(
        "--condition", default="all", choices=["generic", "government", "all"]
    )
    parser.add_argument("--scenario", default="all", help="情景 id 或 all")
    parser.add_argument("--jurisdiction", default="all", help="法域 id 或 all")
    parser.add_argument(
        "--session",
        default="auto",
        help="morning / afternoon / evening / auto（按北京时间自动判定）",
    )
    parser.add_argument("--limit", type=int, default=None, help="本次调用上限（冒烟测试用）")
    parser.add_argument(
        "--limit-per-cell",
        type=int,
        default=None,
        help="每个设计单元限定调用数（跨单元冒烟测试用，比 --limit 更实用）",
    )
    parser.add_argument("--no-anchors", action="store_true", help="本次不跑锚点任务")
    parser.add_argument("--dry-run", action="store_true", help="只渲染并写出样张，不调用 API")
    parser.add_argument("--dry-run-samples", type=int, default=6, help="dry-run 输出的样张条数")
    parser.add_argument("--auto-design", action="store_true", help="设计矩阵缺失时自动调用 01 脚本生成")
    parser.add_argument("--skip-guards", action="store_true", help="跳过守卫检查（会在数据里标记）")
    parser.add_argument(
        "--mock",
        action="store_true",
        help=(
            "不调用 API，用确定性伪回答跑通全流程（用于自检代码、给合作者演示）。"
            "强烈建议使用 MOCK_ 开头的 run-id；清洗脚本默认不读 MOCK_ 数据。"
        ),
    )
    parser.add_argument("--sleep-min", type=float, default=None)
    parser.add_argument("--sleep-max", type=float, default=None)
    return parser.parse_args()


def detect_session_label(experiment: Mapping[str, Any], hour: int | None = None) -> str:
    """按北京时间把当前时刻归入配置的时段；落在窗口外则按最近的窗口归属。"""
    hour = beijing_hour() if hour is None else hour
    sessions = list(experiment["sessions"])
    for session in sessions:
        window = str(session.get("local_window", ""))
        if "-" in window:
            start, end = window.split("-", 1)
            start_h, end_h = int(start.split(":")[0]), int(end.split(":")[0])
            if start_h <= hour < end_h:
                return str(session["label"])
    if hour < 12:
        return str(sessions[0]["label"])
    if hour < 19:
        return str(sessions[1]["label"]) if len(sessions) > 1 else str(sessions[0]["label"])
    return str(sessions[-1]["label"])


# --- 法规材料 ---------------------------------------------------------------


def load_law_materials(
    legal_config: Mapping[str, Any],
) -> tuple[dict[str, list[tuple[Mapping[str, Any], str]]], dict[str, str], list[str]]:
    """读取各法域启用中的法规文本；返回 (材料, id->sha256, 问题列表)。

    文本文件直接放在 data/raw/legal_texts/{law_text_id}.txt；目录里没有
    manifest / 质检报告，来源等文档信息登记在 config/legal_texts.yaml，
    sha256 在每次调用时对 txt 现算并写入响应行。
    """
    output_dir = cfg.resolve_path(legal_config["paths"]["output_dir"])
    problems: list[str] = []

    materials: dict[str, list[tuple[Mapping[str, Any], str]]] = {}
    sha_by_id: dict[str, str] = {}

    for law in legal_config["laws"]:
        if not law.get("enabled", False):
            continue
        law_id = str(law["id"])
        jurisdiction = str(law["jurisdiction"])
        text_path = output_dir / f"{law_id}.txt"
        if not text_path.exists():
            problems.append(f"法规文本缺失：{text_path}（先运行 02_build_legal_texts.py）")
            continue
        text = text_path.read_text(encoding="utf-8")
        meta = {
            "law_text_id": law_id,
            "jurisdiction": jurisdiction,
            "title_en": law.get("title_en", ""),
            "file": str(text_path.relative_to(cfg.PROJECT_ROOT)),
        }
        materials.setdefault(jurisdiction, []).append((meta, text))
        sha_by_id[law_id] = sha256_text(text)
    return materials, sha_by_id, problems


def guard_failures(
    experiment: Mapping[str, Any],
    prompts_config: Mapping[str, Any],
) -> list[str]:
    """开跑前的守卫检查：提示词必须已定稿（frozen）。

    法规文本的确认门禁（review_status == huhe_confirmed）已于 2026-09-18 移除：
    两份在用文本当时已由 Huhe 确认，门禁完成使命（见 docs/01_design-spec.md §5）。
    """
    guards = experiment.get("guards", {})
    failures: list[str] = []

    if guards.get("require_frozen_prompts", True):
        for prompt_id, prompt in prompts_config["prompts"].items():
            if prompt.get("status") != "frozen" and prompt.get("status") != "deprecated":
                failures.append(
                    f"提示词 {prompt_id} 状态为 {prompt.get('status')}，尚未定稿（frozen）"
                )
    return failures


# --- 调用计划 ---------------------------------------------------------------


def build_calls(
    run_id: str,
    experiment: Mapping[str, Any],
    plans: list[design_lib.CellPlan],
    session_label: str,
    scenarios: dict[str, design_lib.Scenario],
    include_anchors: bool,
) -> list[CallSpec]:
    """构造本次待调用的清单。

    锚点任务排在主任务之前：它们数量少但对稳健性检验最关键，
    排在前面就不会被 --limit / --limit-per-cell 截掉。
    """
    calls: list[CallSpec] = []
    for plan in plans:
        scenario = scenarios[plan.scenario_id]
        if include_anchors:
            for anchor_index, repeat_index, anchor_session in design_lib.anchor_plan(experiment, plan):
                if anchor_session != session_label:
                    continue
                calls.append(
                    CallSpec(
                        task=design_lib.sample_task(
                            scenario,
                            run_id=run_id,
                            cell_id=plan.cell_id,
                            task_kind="anchor",
                            task_index=anchor_index,
                            repeat_index=repeat_index,
                        ),
                        plan=plan,
                        session_label=session_label,
                    )
                )
        start, end = plan.task_index_range(session_label)
        for index in range(start, end):
            calls.append(
                CallSpec(
                    task=design_lib.sample_task(
                        scenario,
                        run_id=run_id,
                        cell_id=plan.cell_id,
                        task_kind="main",
                        task_index=index,
                    ),
                    plan=plan,
                    session_label=session_label,
                )
            )
    return calls


# --- 行构造与成本 -----------------------------------------------------------


def estimate_cost(model_key: str, pricing: Mapping[str, Any], usage: Mapping[str, Any]) -> dict[str, Any]:
    table = (pricing.get(model_key) or {}).get("per_million")
    if not table:
        return {"estimated_cost_usd": None, "pricing_as_of": None}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cache_hit = providers.usage_field(usage, "prompt_cache_hit_tokens", "cached_tokens")
    if cache_hit is None:
        cache_hit = 0
    cache_hit = min(int(cache_hit), prompt_tokens)
    cache_miss = prompt_tokens - cache_hit
    cost = (
        cache_hit / 1_000_000 * float(table["prompt_cache_hit"])
        + cache_miss / 1_000_000 * float(table["prompt_cache_miss"])
        + completion_tokens / 1_000_000 * float(table["completion"])
    )
    return {
        "prompt_cache_hit_tokens": cache_hit,
        "prompt_cache_miss_tokens": cache_miss,
        "estimated_cost_usd": round(cost, 6),
        "pricing_as_of": (pricing.get(model_key) or {}).get("as_of"),
    }


def mock_llm_response(spec: CallSpec, scenario: design_lib.Scenario, seed: int) -> providers.LLMResponse:
    """生成一条确定性的伪回答，只用于验证代码链路，不能用于任何实质分析。

    伪回答的生成规则是一个简单的效用模型（风险越低越好、问责机制越明确越好、
    时效越快越好），目的是让下游的解析与 AMCE 估计能跑出非退化的结果。
    """
    rng = random.Random(seed)
    weights = {
        "miss_military": 1.0,
        "civilian_casualties": 1.0,
        "missed_diagnosis": 1.0,
        "misdiagnosis": 1.0,
        "timeliness": 0.6,
        "efficiency": 0.6,
        "rnd_institution": 0.5,
        "accountability": 0.7,
        "legal_accountability": 0.7,
    }
    institution_score = {"public": 1.2, "domestic_private": 1.0, "multinational": 0.8}
    accountability_score = {
        "rnd_responsible": 1.0,
        "commander_responsible": 0.9,
        "physician_responsible": 0.9,
        "national_immunity": 0.1,
        "liability_waiver": 0.1,
    }

    def level_score(attribute_id: str, level_id: str) -> float:
        if level_id in institution_score:
            return institution_score[level_id]
        if level_id in accountability_score:
            return accountability_score[level_id]
        rank = scenario.attribute(attribute_id).level(level_id).dominance_rank
        return 4.0 - rank if rank is not None else 1.0

    utility_a = 0.0
    utility_b = 0.0
    for attribute in scenario.attributes:
        weight = weights.get(attribute.id, 0.5)
        utility_a += weight * level_score(attribute.id, spec.task.option_a[attribute.id])
        utility_b += weight * level_score(attribute.id, spec.task.option_b[attribute.id])
    if spec.plan.condition == "government":
        # 伪 treatment 效应：government 条件下更看重问责与合规
        for attribute_id in ("accountability", "legal_accountability"):
            if attribute_id in spec.task.option_a:
                utility_a += 0.4 * level_score(attribute_id, spec.task.option_a[attribute_id])
                utility_b += 0.4 * level_score(attribute_id, spec.task.option_b[attribute_id])

    probability_a = 1 / (1 + pow(2.718281828, -(utility_a - utility_b)))
    choice = "A" if rng.random() < probability_a else "B"
    chosen_attribute = max(
        scenario.attributes,
        key=lambda attribute: abs(
            level_score(attribute.id, spec.task.option_a[attribute.id])
            - level_score(attribute.id, spec.task.option_b[attribute.id])
        ),
    )
    reason = scenario.attribute(chosen_attribute.id).level(
        spec.task.option_a[chosen_attribute.id]
        if choice == "A"
        else spec.task.option_b[chosen_attribute.id]
    ).label_en
    text = (
        f"I would choose Option {choice}. The decisive consideration is {chosen_attribute.label_en.lower()}: "
        f"the selected option offers {reason[:120]}."
    )
    return providers.LLMResponse(
        text=text,
        model_returned="mock-model",
        response_id=f"mock-{spec.task.task_id}",
        finish_reason="stop",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        endpoint_host="mock",
    )


def build_row(
    context: RunContext,
    spec: CallSpec,
    rendered: render_lib.RenderedPrompt,
    call_index: int,
    response: providers.LLMResponse | None,
    requested_at,
    responded_at,
) -> dict[str, Any]:
    scenario = context.scenarios[spec.plan.scenario_id]
    task = spec.task
    usage: dict[str, Any] = dict(response.usage) if response else {}

    row: dict[str, Any] = {
        "run_id": context.run_id,
        "call_index": call_index,
        "session_label": spec.session_label,
        "model_key": context.model_key,
        "model_requested": providers.request_model_name(context.model_key, context.model_config),
        "condition": spec.plan.condition,
        "scenario": spec.plan.scenario_id,
        "jurisdiction": spec.plan.jurisdiction or "",
        "language": context.language,
        "cell_id": spec.plan.cell_id,
        "task_kind": task.task_kind,
        "task_id": task.task_id,
        "task_index": task.task_index,
        "repeat_index": task.repeat_index,
        "task_seed": task.seed,
        "task_signature": task.task_signature,
        "task_signature_pair": task.task_signature_pair,
        "task_signature_unordered": task.task_signature_unordered,
        "attribute_order": ">".join(task.attribute_order),
        "a_dominates": int(task.a_dominates),
        "b_dominates": int(task.b_dominates),
        "prompt_id": rendered.prompt_id,
        "prompt_status": rendered.prompt_status,
        "answer_protocol": rendered.answer_protocol,
        "render_style": rendered.render_style,
        "prompt_archive_id": rendered.prompt_archive_id,
        "system_prompt_sha256": rendered.system_prompt_sha256,
        "prefix_sha256": rendered.prefix_sha256,
        "task_screen_text": rendered.task_screen_text,
        "task_screen_sha256": rendered.task_screen_sha256,
        "user_message_sha256": rendered.user_message_sha256,
        "law_text_ids": "|".join(
            meta["law_text_id"] for meta, _ in context.law_materials.get(spec.plan.jurisdiction or "", [])
        ),
        "law_text_sha256": "|".join(
            context.law_sha_by_id.get(meta["law_text_id"], "")
            for meta, _ in context.law_materials.get(spec.plan.jurisdiction or "", [])
        ),
        "guards_skipped": int(context.guards_skipped),
        "requested_at_bj": iso_beijing(requested_at),
        "requested_at_utc": iso_utc(requested_at),
        "responded_at_bj": iso_beijing(responded_at),
        "responded_at_utc": iso_utc(responded_at),
        "latency_ms": int((responded_at - requested_at).total_seconds() * 1000),
    }
    for attribute in scenario.attributes:
        row[f"a__{attribute.id}"] = task.option_a[attribute.id]
        row[f"b__{attribute.id}"] = task.option_b[attribute.id]

    if response is not None:
        row.update(
            {
                "model_returned": response.model_returned,
                "response_id": response.response_id,
                "system_fingerprint": response.system_fingerprint,
                "finish_reason": response.finish_reason,
                "endpoint_host": response.endpoint_host,
                "attempts": response.attempts,
                "response_raw": response.text,
                "reasoning_content": response.reasoning_content or "",
                "usage_prompt_tokens": usage.get("prompt_tokens"),
                "usage_completion_tokens": usage.get("completion_tokens"),
                "usage_total_tokens": usage.get("total_tokens"),
            }
        )
        row.update(estimate_cost(context.model_key, cfg.load_models_config().get("pricing", {}), usage))
    return row


# --- 主流程 -----------------------------------------------------------------


def ensure_design_matrix(run_id: str, scenarios: list[str], auto: bool) -> None:
    missing = [
        scenario_id
        for scenario_id in scenarios
        if not (cfg.DESIGN_DIR / SCENARIO_FILE_TEMPLATE.format(run_id=run_id, scenario=scenario_id)).exists()
    ]
    if not missing:
        return
    message = (
        f"缺少设计矩阵：{missing}。请先运行：\n"
        f"  python data/collection/01_build_design_matrix.py --run-id {run_id}"
    )
    if not auto:
        raise SystemExit(message)
    print("设计矩阵缺失，自动调用 01_build_design_matrix.py ...")
    script = Path(__file__).resolve().parent / "01_build_design_matrix.py"
    subprocess.run([sys.executable, str(script), "--run-id", run_id], check=True, cwd=cfg.PROJECT_ROOT)


def write_dry_run_samples(
    context: RunContext, samples: list[tuple[CallSpec, render_lib.RenderedPrompt]]
) -> Path:
    path = cfg.OUTPUTS_OTHER / f"dryrun__{context.run_id}__{context.session_label}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = [
        f"# Dry run 样张 · run_id={context.run_id} · session={context.session_label}",
        "",
        f"- 模型：`{context.model_key}`（请求名 `{providers.request_model_name(context.model_key, context.model_config)}`）",
        f"- 答案协议：`{context.answer_protocol}`",
        f"- 提示词：`{samples[0][1].prompt_id if samples else 'n/a'}`",
        "- 本文件只用于人工核对会发出去什么，不含任何 API 调用。",
        "",
    ]
    for index, (spec, rendered) in enumerate(samples, start=1):
        blocks.extend(
            [
                f"---",
                f"## 样张 {index}",
                f"- cell：`{spec.plan.cell_id}`",
                f"- task_id：`{spec.task.task_id}`（{spec.task.task_kind}）",
                f"- 属性行序：`{' > '.join(spec.task.attribute_order)}`",
                f"- prompt_archive_id：`{rendered.prompt_archive_id}`",
                "",
                "### SYSTEM",
                "```text",
                rendered.system_prompt,
                "```",
                "",
                "### USER",
                "```text",
                rendered.user_message,
                "```",
                "",
            ]
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    cfg.ensure_output_dirs()

    experiment = cfg.load_experiment_config()
    models_config = cfg.load_models_config()
    prompts_config = cfg.load_prompts_config()
    legal_config = cfg.load_legal_texts_config()
    scenarios = design_lib.load_scenarios()

    model_key = args.model or str(experiment.get("default_model"))
    model_cfg = (models_config["models"] or {}).get(model_key)
    if not model_cfg:
        raise SystemExit(f"models.yaml 中没有模型 {model_key}")
    if not model_cfg.get("enabled", False) and not args.dry_run:
        raise SystemExit(
            f"模型 {model_key} 在 models.yaml 中 enabled=false。"
            f"确认型号后改为 true，或先用 --dry-run 检查渲染结果。"
        )

    conditions = (
        list(experiment["cells"]["conditions"]) if args.condition == "all" else [args.condition]
    )
    scenario_ids = (
        list(experiment["cells"]["scenarios"]) if args.scenario == "all" else [args.scenario]
    )
    jurisdictions = (
        list(experiment["cells"]["jurisdictions"])
        if args.jurisdiction == "all"
        else [args.jurisdiction]
    )
    language = str(experiment["cells"]["languages"][0])
    answer_protocol = str(experiment["answer_protocol"])

    session_label = args.session
    if session_label == "auto":
        session_label = detect_session_label(experiment)
        print(f"未指定 --session，按北京时间自动判定为：{session_label}")

    ensure_design_matrix(args.run_id, scenario_ids, args.auto_design)

    plans = design_lib.build_cell_plans(
        experiment, conditions=conditions, scenarios=scenario_ids, jurisdictions=jurisdictions
    )

    law_materials, law_sha_by_id, law_problems = load_law_materials(legal_config)
    if law_problems:
        for problem in law_problems:
            print(f"[warn] {problem}")

    failures = guard_failures(experiment, prompts_config)
    guards_skipped = bool(args.skip_guards) or args.dry_run
    if failures and not args.skip_guards and not args.dry_run:
        print("守卫检查未通过：")
        for failure in failures:
            print(f"  - {failure}")
        print("\n修正后重跑，或加 --skip-guards 强行开跑（会在每行数据里标记 guards_skipped=1）。")
        return 2
    if failures and (args.skip_guards or args.dry_run):
        print("守卫检查未通过，但已按参数继续（数据会标记 guards_skipped）：")
        for failure in failures:
            print(f"  - {failure}")

    context = RunContext(
        run_id=args.run_id,
        session_label=session_label,
        model_key=model_key,
        model_config=model_cfg,
        api_config=dict(models_config.get("api_defaults", {})),
        answer_protocol=answer_protocol,
        language=language,
        render_config=cfg.load_prompts_config()["render"],
        prompts_config=prompts_config,
        scenarios=scenarios,
        law_materials=law_materials,
        law_sha_by_id=law_sha_by_id,
        guards_skipped=guards_skipped,
        session_file=cfg.RESPONSES_DIR / f"{args.run_id}__{session_label}.jsonl",
        error_file=cfg.RESPONSES_DIR / f"{args.run_id}__{session_label}__errors.jsonl",
        archive_file=cfg.RESPONSES_DIR / "_prompt_archive.jsonl",
    )

    calls = build_calls(
        args.run_id, experiment, plans, session_label, scenarios, include_anchors=not args.no_anchors
    )
    if args.limit_per_cell is not None:
        limited: list[CallSpec] = []
        for cell_id in dict.fromkeys(call.plan.cell_id for call in calls):
            cell_calls = [call for call in calls if call.plan.cell_id == cell_id]
            limited.extend(cell_calls[: args.limit_per_cell])
        calls = limited
    if args.limit is not None:
        calls = calls[: args.limit]

    # 断点续跑：跳过已经跑过的 (run_id, task_id)
    done: set[tuple[Any, ...]] = set()
    for path in sorted(cfg.RESPONSES_DIR.glob(f"{args.run_id}__*.jsonl")):
        if path.name.endswith("__errors.jsonl"):
            continue
        done |= existing_keys(path, ["run_id", "task_id"])
    pending = [call for call in calls if (args.run_id, call.task.task_id) not in done]

    print(f"run_id        : {args.run_id}")
    print(f"session       : {session_label}")
    print(f"模型          : {model_key}")
    print(f"单元数        : {len(plans)}")
    print(f"本次计划调用  : {len(calls)}（已完成 {len(calls) - len(pending)}，待跑 {len(pending)}）")

    if args.dry_run:
        samples: list[tuple[CallSpec, render_lib.RenderedPrompt]] = []
        for spec in pending[: max(0, args.dry_run_samples)]:
            samples.append((spec, _render_for(context, spec)))
        if not samples:
            print("没有可渲染的任务。")
            return 0
        path = write_dry_run_samples(context, samples)
        print(f"\ndry-run 样张已写入：{path}")
        return 0

    if not pending:
        print("没有待跑任务，退出。")
        return 0

    # --- 归档 prefix（法规全文只存一次）-------------------------------------
    archived = existing_keys(context.archive_file, ["prompt_archive_id"])
    results = {
        "run_id": args.run_id,
        "session_label": session_label,
        "model_key": model_key,
        "started_at_bj": iso_beijing(now_utc()),
        "n_planned": len(pending),
        "n_succeeded": 0,
        "n_failed": 0,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0},
        "estimated_cost_usd": 0.0,
        "requests_per_minute_cap": experiment.get("runtime", {}).get("requests_per_minute_cap"),
    }

    sleep_cfg = experiment.get("runtime", {}).get("sleep_between_calls_s", [0, 0])
    sleep_min = args.sleep_min if args.sleep_min is not None else float(sleep_cfg[0])
    sleep_max = args.sleep_max if args.sleep_max is not None else float(sleep_cfg[1])
    max_consecutive_errors = int(experiment.get("runtime", {}).get("max_consecutive_errors", 8))
    progress_every = int(experiment.get("runtime", {}).get("progress_every", 50))
    rpm_cap = results["requests_per_minute_cap"]
    min_interval = 60.0 / float(rpm_cap) if rpm_cap else 0.0

    consecutive_errors = 0
    call_index = len(done)
    started = time.monotonic()

    for position, spec in enumerate(pending, start=1):
        rendered = _render_for(context, spec)
        if rendered.prompt_archive_id not in archived:
            append_jsonl(
                context.archive_file,
                {
                    "prompt_archive_id": rendered.prompt_archive_id,
                    "condition": spec.plan.condition,
                    "scenario": spec.plan.scenario_id,
                    "jurisdiction": spec.plan.jurisdiction or "",
                    "language": rendered.language,
                    "prompt_id": rendered.prompt_id,
                    "prompt_status": rendered.prompt_status,
                    "answer_protocol": rendered.answer_protocol,
                    "render_style": rendered.render_style,
                    "system_prompt": rendered.system_prompt,
                    "system_prompt_sha256": rendered.system_prompt_sha256,
                    "prefix_text": rendered.prefix_text,
                    "prefix_sha256": rendered.prefix_sha256,
                    "law_text_ids": "|".join(
                        meta["law_text_id"]
                        for meta, _ in context.law_materials.get(spec.plan.jurisdiction or "", [])
                    ),
                    "first_seen_at_bj": iso_beijing(now_utc()),
                },
            )
            archived.add(rendered.prompt_archive_id)

        requested_at = now_utc()
        try:
            if args.mock:
                response = mock_llm_response(
                    spec,
                    context.scenarios[spec.plan.scenario_id],
                    design_lib.stable_seed(args.run_id, spec.task.task_id, "mock"),
                )
            else:
                response = providers.chat(
                    context.model_key,
                    context.model_config,
                    context.api_config,
                    rendered.system_prompt,
                    rendered.user_message,
                )
        except providers.LLMCallError as exc:
            responded_at = now_utc()
            append_jsonl(
                context.error_file,
                {
                    "run_id": args.run_id,
                    "session_label": session_label,
                    "model_key": model_key,
                    "task_id": spec.task.task_id,
                    "cell_id": spec.plan.cell_id,
                    "error_type": exc.error_type,
                    "status_code": exc.status_code,
                    "retryable": int(exc.retryable),
                    "attempts": exc.attempts,
                    "message": str(exc)[:2000],
                    "requested_at_bj": iso_beijing(requested_at),
                    "responded_at_bj": iso_beijing(responded_at),
                },
            )
            results["n_failed"] += 1
            consecutive_errors += 1
            print(f"[error] {spec.task.task_id}: {exc.error_type} {exc}")
            if consecutive_errors >= max_consecutive_errors:
                print(f"连续失败 {consecutive_errors} 次，中止本次运行。")
                break
            continue

        responded_at = now_utc()
        consecutive_errors = 0
        call_index += 1
        row = build_row(context, spec, rendered, call_index, response, requested_at, responded_at)
        row["is_mock"] = int(bool(args.mock))
        append_jsonl(context.session_file, row)

        results["n_succeeded"] += 1
        usage = response.usage or {}
        results["usage"]["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        results["usage"]["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        results["usage"]["cache_hit_tokens"] += int(row.get("prompt_cache_hit_tokens") or 0)
        results["estimated_cost_usd"] += float(row.get("estimated_cost_usd") or 0.0)

        if position % progress_every == 0 or position == len(pending):
            elapsed = time.monotonic() - started
            rate = position / elapsed * 60 if elapsed > 0 else 0.0
            print(
                f"[{position}/{len(pending)}] 成功 {results['n_succeeded']} 失败 {results['n_failed']} "
                f"| {rate:.1f} 次/分钟 | 累计估算成本 ${results['estimated_cost_usd']:.4f}"
            )

        time.sleep(0 if args.mock else max(min_interval, random.uniform(sleep_min, sleep_max)))

    results["finished_at_bj"] = iso_beijing(now_utc())
    results["estimated_cost_usd"] = round(results["estimated_cost_usd"], 6)
    log_path = cfg.OUTPUTS_OTHER / f"{args.run_id}__{session_label}__run_log.json"
    write_json(log_path, results)

    manifest_path = cfg.RESPONSES_DIR / f"{args.run_id}__run_manifest.json"
    manifest = read_json(manifest_path, default={}) or {}
    manifest.setdefault("run_id", args.run_id)
    manifest.setdefault("model_key", model_key)
    manifest.setdefault("config_sha256", cfg.config_sha256())
    manifest.setdefault("started_at_bj", results["started_at_bj"])
    manifest["guards_skipped"] = int(guards_skipped)
    manifest["answer_protocol"] = answer_protocol
    manifest["language"] = language
    manifest["model_params"] = dict(model_cfg.get("params") or {})
    manifest["api_defaults"] = context.api_config
    sessions = set(manifest.get("sessions", []))
    sessions.add(session_label)
    manifest["sessions"] = sorted(sessions)
    write_json(manifest_path, manifest)

    print(
        f"\n完成：成功 {results['n_succeeded']}，失败 {results['n_failed']}，"
        f"估算成本 ${results['estimated_cost_usd']:.4f}\n"
        f"数据：{context.session_file}\n日志：{log_path}"
    )
    return 0 if results["n_failed"] == 0 else 1


def _render_for(context: RunContext, spec: CallSpec) -> render_lib.RenderedPrompt:
    scenario = context.scenarios[spec.plan.scenario_id]
    prompt_id, prompt_cfg = render_lib.select_prompt(
        context.prompts_config, spec.plan.condition, context.language
    )
    laws = context.law_materials.get(spec.plan.jurisdiction or "", []) or None
    return render_lib.render_prompt(
        scenario=scenario,
        task=spec.task,
        prompt_id=prompt_id,
        prompt_config=prompt_cfg,
        render_config=context.render_config,
        answer_protocol=context.answer_protocol,
        language=context.language,
        laws=laws,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已中断。本次已写入的数据保留在 JSONL 中，重跑会自动跳过已完成任务。")
        raise SystemExit(130)
