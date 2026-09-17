"""联合实验任务的随机化引擎。

实现依据：docs/01_design-spec.md §2，以及问卷 docx 的四条批注约束：
    1. 最少三次随机 task（人类问卷口径；AI 端计数口径由 config 的 tasks_per_call 控制）
    2. "性能特征"显示顺序随机
    3. 方案具体特征值随机产生
    4. 对每一个性能特征，两种方案的随机值必须不同

第 4 条决定了抽样必须用"有序不放回"：每个属性有 3×2=6 种有序对等概率，
属性之间独立，因此任务空间为 6^5 = 7776。

另外一点值得写进论文：由于有序对抽样本身就让"甲/乙"的语义位随机化，
不需要再叠加一层左右位置随机化（那样只会增加冗余变量）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .config import load_scenarios_config
from .io_utils import sha256_text, stable_seed

# --- 数据结构 ---------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    id: str
    label_en: str
    dominance_rank: int | None


@dataclass(frozen=True)
class Attribute:
    id: str
    label_en: str
    higher_is_better: bool | None
    levels: tuple[Level, ...]

    def level(self, level_id: str) -> Level:
        for level in self.levels:
            if level.id == level_id:
                return level
        raise KeyError(f"属性 {self.id} 不存在水平 {level_id}")

    @property
    def level_ids(self) -> tuple[str, ...]:
        return tuple(level.id for level in self.levels)


@dataclass(frozen=True)
class Scenario:
    id: str
    label_en: str
    label_zh: str
    vignette_en: str
    attributes: tuple[Attribute, ...]

    @property
    def attribute_ids(self) -> tuple[str, ...]:
        return tuple(attribute.id for attribute in self.attributes)

    def attribute(self, attribute_id: str) -> Attribute:
        for attribute in self.attributes:
            if attribute.id == attribute_id:
                return attribute
        raise KeyError(f"情景 {self.id} 不存在属性 {attribute_id}")


@dataclass(frozen=True)
class Task:
    """一个随机化的 conjoint 任务屏。"""

    task_id: str
    cell_id: str
    scenario_id: str
    task_kind: str  # main | anchor
    task_index: int
    repeat_index: int  # main 恒为 0；anchor 为重复序号
    seed: int
    attribute_order: tuple[str, ...]  # 呈现顺序（属性行序随机）
    option_a: dict[str, str]  # 语义甲：属性 id -> 水平 id
    option_b: dict[str, str]  # 语义乙
    a_dominates: bool
    b_dominates: bool
    # 三个层次的指纹，对应三个不同的随机空间（多重性随“是否含左右位/行序”变化）：
    #   task_signature         呈现屏（含左右位与行序）     空间 = 6^5 × 5! = 933,120
    #   task_signature_pair    同一对方案（含左右位，不含行序）空间 = 6^5       = 7,776
    #   task_signature_unordered 同一对档案（无左右位/行序）     空间 = 3^5       = 243
    task_signature: str
    task_signature_pair: str
    task_signature_unordered: str

    def level_id(self, option: str, attribute_id: str) -> str:
        return self.option_a[attribute_id] if option == "A" else self.option_b[attribute_id]


@dataclass(frozen=True)
class CellPlan:
    """一个（条件 × 情景 [× 法域]）设计单元的执行计划。"""

    cell_id: str
    condition: str
    scenario_id: str
    jurisdiction: str | None
    n_tasks: int
    session_quotas: dict[str, int]
    session_ranges: dict[str, tuple[int, int]]

    def task_index_range(self, session_label: str) -> tuple[int, int]:
        return self.session_ranges[session_label]


# --- 配置加载 ---------------------------------------------------------------


def load_scenarios() -> dict[str, Scenario]:
    raw = load_scenarios_config()
    scenarios: dict[str, Scenario] = {}
    for entry in raw["scenarios"]:
        attributes = []
        for attribute in entry["attributes"]:
            levels = tuple(
                Level(
                    id=level["id"],
                    label_en=" ".join(str(level["label_en"]).split()),
                    dominance_rank=level.get("dominance_rank"),
                )
                for level in attribute["levels"]
            )
            if len({level.id for level in levels}) != len(levels):
                raise ValueError(f"{entry['id']}.{attribute['id']} 存在重复水平 id")
            attributes.append(
                Attribute(
                    id=attribute["id"],
                    label_en=" ".join(str(attribute["label_en"]).split()),
                    higher_is_better=attribute.get("higher_is_better"),
                    levels=levels,
                )
            )
        scenarios[entry["id"]] = Scenario(
            id=entry["id"],
            label_en=" ".join(str(entry["label_en"]).split()),
            label_zh=str(entry.get("label_zh", "")),
            vignette_en=" ".join(str(entry["vignette_en"]).split()),
            attributes=tuple(attributes),
        )
    return scenarios


def get_scenario(scenario_id: str) -> Scenario:
    scenarios = load_scenarios()
    if scenario_id not in scenarios:
        raise KeyError(f"未知情景：{scenario_id}（可选：{sorted(scenarios)}）")
    return scenarios[scenario_id]


# --- 单元与配额 -------------------------------------------------------------


def make_cell_id(condition: str, scenario_id: str, jurisdiction: str | None) -> str:
    if jurisdiction:
        return f"{condition}__{scenario_id}__{jurisdiction}"
    return f"{condition}__{scenario_id}"


def _split_by_session_share(total: int, sessions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """按 quota_share 把总量分配到各时段；余数归最后一段，保证合计等于 total。"""
    quotas: dict[str, int] = {}
    allocated = 0
    for index, session in enumerate(sessions):
        label = str(session["label"])
        if index == len(sessions) - 1:
            quotas[label] = total - allocated
        else:
            quota = int(round(total * float(session["quota_share"])))
            quotas[label] = quota
            allocated += quota
    return quotas


def _session_ranges(quotas: Mapping[str, int], order: Sequence[str]) -> dict[str, tuple[int, int]]:
    ranges: dict[str, tuple[int, int]] = {}
    cursor = 0
    for label in order:
        quota = int(quotas.get(label, 0))
        ranges[label] = (cursor, cursor + quota)
        cursor += quota
    return ranges


def build_cell_plans(
    experiment: Mapping[str, Any],
    conditions: Iterable[str] | None = None,
    scenarios: Iterable[str] | None = None,
    jurisdictions: Iterable[str] | None = None,
) -> list[CellPlan]:
    """构造本次运行涉及的设计单元及配额。

    government 条件按 jurisdiction_balance 分配法域配额：
        balanced -> n 在法域间平摊（默认，CN/US 各 500）
        full     -> 每个法域各跑满 n（成本翻倍）
    generic 条件没有法域维度（不注入任何材料）。
    """
    cells_cfg = experiment["cells"]
    base_n = int(cells_cfg["n_per_condition_scenario"])
    balance = str(cells_cfg.get("jurisdiction_balance", "balanced"))
    sessions = list(experiment["sessions"])
    session_order = [str(session["label"]) for session in sessions]

    conditions = list(conditions or cells_cfg["conditions"])
    scenario_ids = list(scenarios or cells_cfg["scenarios"])
    jurisdiction_ids = list(jurisdictions or cells_cfg["jurisdictions"])

    plans: list[CellPlan] = []
    for condition in conditions:
        for scenario_id in scenario_ids:
            if condition == "government":
                if balance == "full":
                    allocations = [(j, base_n) for j in jurisdiction_ids]
                else:
                    share, remainder = divmod(base_n, len(jurisdiction_ids))
                    allocations = [
                        (j, share + (1 if index < remainder else 0))
                        for index, j in enumerate(jurisdiction_ids)
                    ]
            else:
                allocations = [(None, base_n)]

            for jurisdiction, n_tasks in allocations:
                quotas = _split_by_session_share(n_tasks, sessions)
                plans.append(
                    CellPlan(
                        cell_id=make_cell_id(condition, scenario_id, jurisdiction),
                        condition=condition,
                        scenario_id=scenario_id,
                        jurisdiction=jurisdiction,
                        n_tasks=n_tasks,
                        session_quotas=quotas,
                        session_ranges=_session_ranges(quotas, session_order),
                    )
                )
    return plans


# --- 任务抽样 ---------------------------------------------------------------


def _dominance(
    scenario: Scenario,
    option_a: Mapping[str, str],
    option_b: Mapping[str, str],
) -> tuple[bool, bool]:
    """判断是否存在"在全部可排序维度上都更好"的被支配方案（Q11 诊断用）。"""
    ranked = 0
    a_better = 0
    b_better = 0
    for attribute in scenario.attributes:
        rank_a = attribute.level(option_a[attribute.id]).dominance_rank
        rank_b = attribute.level(option_b[attribute.id]).dominance_rank
        if rank_a is None or rank_b is None:
            continue
        ranked += 1
        if rank_a < rank_b:
            a_better += 1
        elif rank_b < rank_a:
            b_better += 1
    if ranked == 0:
        return False, False
    return a_better == ranked, b_better == ranked


def sample_task(
    scenario: Scenario,
    run_id: str,
    cell_id: str,
    task_kind: str = "main",
    task_index: int = 0,
    repeat_index: int = 0,
) -> Task:
    """抽取一个随机任务。

    种子里【不含 repeat_index】：锚点任务的各次重复共用同一任务，这正是它存在的意义。
    """
    if task_kind not in {"main", "anchor"}:
        raise ValueError(f"未知 task_kind：{task_kind}")
    seed = stable_seed(run_id, cell_id, task_kind, task_index)
    rng = random.Random(seed)

    option_a: dict[str, str] = {}
    option_b: dict[str, str] = {}
    for attribute in scenario.attributes:
        level_ids = list(attribute.level_ids)
        level_a, level_b = rng.sample(level_ids, 2)  # 有序不放回 -> 甲 != 乙
        option_a[attribute.id] = level_a
        option_b[attribute.id] = level_b

    attribute_order = tuple(rng.sample(list(scenario.attribute_ids), len(scenario.attributes)))

    a_dominates, b_dominates = _dominance(scenario, option_a, option_b)

    ordered_signature = "|".join(
        f"{attribute_id}:{option_a[attribute_id]}~{option_b[attribute_id]}"
        for attribute_id in attribute_order
    )
    pair_signature = "|".join(
        f"{attribute_id}:{option_a[attribute_id]}~{option_b[attribute_id]}"
        for attribute_id in sorted(scenario.attribute_ids)
    )
    unordered_signature = "|".join(
        f"{attribute_id}:"
        + "~".join(sorted([option_a[attribute_id], option_b[attribute_id]]))
        for attribute_id in sorted(scenario.attribute_ids)
    )

    suffix = (
        f"main-{task_index:04d}"
        if task_kind == "main"
        else f"anchor-{task_index:02d}-rep{repeat_index:02d}"
    )
    return Task(
        task_id=f"{cell_id}::{suffix}",
        cell_id=cell_id,
        scenario_id=scenario.id,
        task_kind=task_kind,
        task_index=task_index,
        repeat_index=repeat_index,
        seed=seed,
        attribute_order=attribute_order,
        option_a=option_a,
        option_b=option_b,
        a_dominates=a_dominates,
        b_dominates=b_dominates,
        task_signature=sha256_text(ordered_signature)[:16],
        task_signature_pair=sha256_text(pair_signature)[:16],
        task_signature_unordered=sha256_text(unordered_signature)[:16],
    )


def anchor_plan(experiment: Mapping[str, Any], cell: CellPlan) -> list[tuple[int, int, str]]:
    """返回某单元的锚点调用计划：[(anchor_index, repeat_index, session_label), ...]。"""
    anchors_cfg = experiment.get("anchors", {})
    if not anchors_cfg.get("enabled", False):
        return []
    n_anchor_tasks = int(anchors_cfg.get("tasks_per_cell", 0))
    n_repeats = int(anchors_cfg.get("repeats_per_task", 0))
    if n_anchor_tasks <= 0 or n_repeats <= 0:
        return []

    session_labels = [str(session["label"]) for session in experiment["sessions"]]
    if not session_labels:
        return []
    if str(anchors_cfg.get("session_assignment", "round_robin")) != "round_robin":
        raise ValueError("目前只支持 anchors.session_assignment = round_robin")

    plan: list[tuple[int, int, str]] = []
    for anchor_index in range(n_anchor_tasks):
        for repeat_index in range(n_repeats):
            plan.append(
                (anchor_index, repeat_index, session_labels[repeat_index % len(session_labels)])
            )
    return plan
