"""提示词与任务屏渲染。

组装顺序（顺序固定，前面部分逐任务不变 → 最大化 DeepSeek 的 prefix cache 命中）：

    system  : condition_block + shared_block
    user    : [仅 government] 法规材料块
              + 情景 vignette
              + 任务屏引言
              + 属性表（行序随机）
              + 提问 + 答案格式指令

其中"任务屏之前"的部分被单独存为 prefix，逐次不变，只归档一次
（见 docs/01_design-spec.md §6.1）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .design import Scenario, Task
from .io_utils import format_table, normalize_ws, sha256_text


@dataclass(frozen=True)
class RenderedPrompt:
    prompt_id: str
    prompt_status: str
    answer_protocol: str
    render_style: str
    language: str
    system_prompt: str
    prefix_text: str
    task_screen_text: str
    user_message: str
    system_prompt_sha256: str
    prefix_sha256: str
    task_screen_sha256: str
    user_message_sha256: str
    prompt_archive_id: str


def _pick_text(container: Mapping[str, Any], base_field: str, language: str) -> str:
    """按语言从配置字典取字段；目前配置只有英文口径（Q5），缺变体时明确报错。"""
    field = f"{base_field}_{language}"
    if field not in container:
        raise KeyError(
            f"配置缺少 {field}（语言 {language}）。当前设计只支持英文口径，"
            f"若要加中文版，需在 config 中补齐对应字段并新建版本号。"
        )
    return " ".join(str(container[field]).split())


def _pick_scenario_text(scenario: Scenario, base_field: str, language: str) -> str:
    """按语言从 Scenario 对象取字段。"""
    field = f"{base_field}_{language}"
    value = getattr(scenario, field, None)
    if value is None:
        raise KeyError(
            f"情景 {scenario.id} 缺少 {field}。当前设计只支持英文口径（Q5）。"
        )
    return str(value)


def select_prompt(
    prompts_config: Mapping[str, Any], condition: str, language: str
) -> tuple[str, Mapping[str, Any]]:
    """选出该条件/语言下版本号最高且未停用的提示词。"""
    candidates = [
        (prompt_id, cfg)
        for prompt_id, cfg in prompts_config["prompts"].items()
        if cfg.get("condition") == condition
        and cfg.get("language") == language
        and cfg.get("status") != "deprecated"
    ]
    if not candidates:
        raise KeyError(f"没有可用的提示词：condition={condition}, language={language}")
    candidates.sort(key=lambda item: int(item[1].get("version", 0)))
    return candidates[-1][0], candidates[-1][1]


def build_system_prompt(prompt_config: Mapping[str, Any]) -> str:
    condition_block = normalize_ws(str(prompt_config["condition_block"]))
    shared_block = normalize_ws(str(prompt_config["shared_block"]))
    return f"{condition_block}\n\n{shared_block}"


def build_legal_block(
    laws: Sequence[tuple[Mapping[str, Any], str]],
    render_config: Mapping[str, Any],
) -> str:
    """法规材料块。支持同一法域注入多份文件（一个法域一份以上时按配置顺序拼接）。

    法规正文按原文保留段落，只做 strip，不做空白折叠。
    每份材料前都带可追溯的描述行（id + 标题 + 法域）。
    """
    header = normalize_ws(str(render_config["legal_block_header"]))
    open_marker = str(render_config["legal_block_open"])
    close_marker = str(render_config["legal_block_close"])

    parts: list[str] = [header, "", open_marker]
    for law_meta, law_text in laws:
        descriptor = (
            f"[{law_meta['law_text_id']}] {law_meta.get('title_en', '')} "
            f"({law_meta.get('jurisdiction', '')})"
        ).strip()
        parts.extend([descriptor, "", law_text.strip(), ""])
    parts.append(close_marker)
    return "\n".join(parts)


def build_task_table(
    scenario: Scenario, task: Task, render_config: Mapping[str, Any]
) -> str:
    """按随机行序渲染属性表。"""
    header = [str(cell) for cell in render_config["table_header"]]
    rows: list[list[str]] = [header]
    for attribute_id in task.attribute_order:
        attribute = scenario.attribute(attribute_id)
        rows.append(
            [
                attribute.label_en,
                attribute.level(task.option_a[attribute_id]).label_en,
                attribute.level(task.option_b[attribute_id]).label_en,
            ]
        )
    return format_table(rows)


def build_task_screen(
    scenario: Scenario,
    task: Task,
    render_config: Mapping[str, Any],
    answer_protocol: str,
) -> str:
    table = build_task_table(scenario, task, render_config)
    question = normalize_ws(str(render_config["question"]))
    instruction = normalize_ws(str(render_config["answer_instructions"][answer_protocol]))
    return "\n\n".join([table, f"{question} {instruction}"])


def render_prompt(
    scenario: Scenario,
    task: Task,
    prompt_id: str,
    prompt_config: Mapping[str, Any],
    render_config: Mapping[str, Any],
    answer_protocol: str,
    language: str = "en",
    laws: Sequence[tuple[Mapping[str, Any], str]] | None = None,
) -> RenderedPrompt:
    """渲染一次调用所需的全部文本，并给出可追溯的哈希。

    laws: [(法规元数据, 法规正文), ...]；generic 条件传 None。
    """
    if answer_protocol not in render_config["answer_instructions"]:
        raise KeyError(
            f"未知答案协议：{answer_protocol}"
            f"（可选：{sorted(render_config['answer_instructions'])}）"
        )
    # 安全阀：government 条件必须真的带上法规材料，否则就是“treatment 忘了注入”的严重错误
    if str(prompt_config.get("condition")) == "government" and not laws:
        raise ValueError(
            "government 条件缺少法规材料（laws）。这类错误会让 treatment 静默失效，"
            "因此在这里直接报错，而不是跑出一批无干预的数据。"
        )
    system_prompt = build_system_prompt(prompt_config)

    prefix_parts: list[str] = []
    if laws:
        prefix_parts.append(build_legal_block(laws, render_config))
    prefix_parts.append(_pick_scenario_text(scenario, "vignette", language))
    prefix_parts.append(normalize_ws(str(render_config["task_intro"])))
    prefix_text = "\n\n".join(prefix_parts)

    task_screen_text = build_task_screen(
        scenario, task, render_config, answer_protocol
    )
    user_message = f"{prefix_text}\n\n{task_screen_text}"

    prefix_sha256 = sha256_text(prefix_text)
    # 归档 id 必须同时覆盖 system prompt（条件差异全在那里）与 prefix，
    # 否则 generic 与 government 会算成同一个 id（确实撞过）。
    archive_basis = f"{system_prompt}\n\n{prefix_text}"
    return RenderedPrompt(
        prompt_id=prompt_id,
        prompt_status=str(prompt_config.get("status", "unknown")),
        answer_protocol=answer_protocol,
        render_style=str(render_config["style_id"]),
        language=language,
        system_prompt=system_prompt,
        prefix_text=prefix_text,
        task_screen_text=task_screen_text,
        user_message=user_message,
        system_prompt_sha256=sha256_text(system_prompt),
        prefix_sha256=prefix_sha256,
        task_screen_sha256=sha256_text(task_screen_text),
        user_message_sha256=sha256_text(user_message),
        prompt_archive_id=sha256_text(archive_basis)[:16],
    )
