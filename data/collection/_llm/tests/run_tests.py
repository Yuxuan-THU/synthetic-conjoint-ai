"""设计引擎与渲染层的单元测试。

直接运行（不需要 pytest）：
    python data/collection/_llm/tests/run_tests.py

这些测试锁定 docs/01_design-spec.md §2 的"必须满足的不变量"：
    1. 同一属性上甲、乙取值不同（docx 批注硬约束）
    2. 属性行序是完整随机排列
    3. 同一 (run_id, cell_id, task_kind, task_index) 可完全重放
    4. 锚点任务的各种重复共用同一个任务
    5. 每属性 6 种有序对近似均匀
    6. 时段配额互不重叠且覆盖全部任务
    7. 渲染前缀在同一单元内保持不变（prefix cache 与归档正确性的前提）
"""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _llm import config as cfg  # noqa: E402
from _llm import design as design_lib  # noqa: E402
from _llm import io_utils  # noqa: E402
from _llm import render as render_lib  # noqa: E402

SCENARIO_IDS = ["border_defense", "disease_diagnosis"]


class TestSampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenarios = design_lib.load_scenarios()

    def test_six_ordered_pairs_per_attribute(self) -> None:
        """有序不放回 => 每属性 6 种有序对；5 个属性 => 任务空间 6^5。"""
        for scenario_id in SCENARIO_IDS:
            scenario = self.scenarios[scenario_id]
            self.assertEqual(len(scenario.attributes), 5)
            for attribute in scenario.attributes:
                self.assertEqual(len(attribute.levels), 3)
                self.assertEqual(len(attribute.level_ids), 3)

    def test_options_differ_on_every_attribute(self) -> None:
        for scenario_id in SCENARIO_IDS:
            scenario = self.scenarios[scenario_id]
            for index in range(200):
                task = design_lib.sample_task(
                    scenario, run_id="t", cell_id="c", task_index=index
                )
                for attribute in scenario.attributes:
                    with self.subTest(attribute=attribute.id, index=index):
                        self.assertNotEqual(
                            task.option_a[attribute.id], task.option_b[attribute.id]
                        )

    def test_attribute_order_is_permutation(self) -> None:
        scenario = self.scenarios["border_defense"]
        orders = set()
        for index in range(200):
            task = design_lib.sample_task(
                scenario, run_id="t", cell_id="c", task_index=index
            )
            self.assertEqual(
                sorted(task.attribute_order), sorted(scenario.attribute_ids)
            )
            orders.add(task.attribute_order)
        # 行序必须真的在变，否则说明随机化没生效
        self.assertGreater(len(orders), 20)

    def test_reproducible_for_same_keys(self) -> None:
        scenario = self.scenarios["border_defense"]
        first = design_lib.sample_task(scenario, run_id="r1", cell_id="c1", task_index=7)
        second = design_lib.sample_task(scenario, run_id="r1", cell_id="c1", task_index=7)
        self.assertEqual(first, second)

    def test_different_run_id_gives_different_task(self) -> None:
        scenario = self.scenarios["border_defense"]
        first = design_lib.sample_task(scenario, run_id="r1", cell_id="c1", task_index=7)
        second = design_lib.sample_task(scenario, run_id="r2", cell_id="c1", task_index=7)
        self.assertNotEqual(first.task_signature, second.task_signature)

    def test_anchor_repeats_share_the_task(self) -> None:
        scenario = self.scenarios["disease_diagnosis"]
        tasks = [
            design_lib.sample_task(
                scenario,
                run_id="r1",
                cell_id="c1",
                task_kind="anchor",
                task_index=3,
                repeat_index=repeat,
            )
            for repeat in range(10)
        ]
        signatures = {task.task_signature for task in tasks}
        self.assertEqual(len(signatures), 1)
        # 但 task_id 必须各不相同，否则断点续跑会误判为已跑过
        self.assertEqual(len({task.task_id for task in tasks}), 10)

    def test_ordered_pairs_are_balanced(self) -> None:
        scenario = self.scenarios["border_defense"]
        attribute = scenario.attributes[1]
        counter: Counter[tuple[str, str]] = Counter()
        n = 1200
        for index in range(n):
            task = design_lib.sample_task(
                scenario, run_id="balance", cell_id="c", task_index=index
            )
            counter[(task.option_a[attribute.id], task.option_b[attribute.id])] += 1
        self.assertEqual(len(counter), 6)
        expected = n / 6
        chi_square = sum((count - expected) ** 2 / expected for count in counter.values())
        self.assertLess(chi_square, 15.086)  # df=5, p=0.01

    def test_signature_spaces_are_consistent(self) -> None:
        """三个指纹的取值个数必须分别落在 6^5*120 / 6^5 / 3^5 的空间里。"""
        scenario = self.scenarios["border_defense"]
        tasks = [
            design_lib.sample_task(scenario, run_id="sig", cell_id="c", task_index=i)
            for i in range(400)
        ]
        self.assertLessEqual(len({t.task_signature for t in tasks}), 6 ** 5 * 120)
        self.assertLessEqual(len({t.task_signature_pair for t in tasks}), 6 ** 5)
        self.assertLessEqual(len({t.task_signature_unordered for t in tasks}), 3 ** 5)


class TestDominance(unittest.TestCase):
    def test_dominance_flags_match_manual_check(self) -> None:
        scenario = design_lib.load_scenarios()["border_defense"]
        attribute = scenario.attribute("miss_military")
        # 手工构造：甲在漏报、误伤、时效上都更好，在机构与问责上不可排序 => 甲被判定为支配
        option_a = {
            "rnd_institution": "public",
            "miss_military": "low_1",
            "civilian_casualties": "low_0_5",
            "timeliness": "realtime",
            "accountability": "rnd_responsible",
        }
        option_b = {
            "rnd_institution": "multinational",
            "miss_military": "high_15",
            "civilian_casualties": "high_12",
            "timeliness": "five_minutes",
            "accountability": "national_immunity",
        }
        a_dominates, b_dominates = design_lib._dominance(scenario, option_a, option_b)
        self.assertTrue(a_dominates)
        self.assertFalse(b_dominates)
        self.assertEqual(attribute.level("low_1").dominance_rank, 1)


class TestCellPlans(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.experiment = cfg.load_experiment_config()

    def test_quota_sums_and_ranges(self) -> None:
        plans = design_lib.build_cell_plans(self.experiment)
        session_labels = [str(s["label"]) for s in self.experiment["sessions"]]
        for plan in plans:
            self.assertEqual(sum(plan.session_quotas.values()), plan.n_tasks)
            seen: list[int] = []
            for label in session_labels:
                start, end = plan.task_index_range(label)
                self.assertEqual(plan.session_quotas[label], end - start)
                seen.extend(range(start, end))
            self.assertEqual(sorted(seen), list(range(plan.n_tasks)))

    def test_government_is_split_across_jurisdictions(self) -> None:
        plans = design_lib.build_cell_plans(self.experiment)
        government = [p for p in plans if p.condition == "government"]
        self.assertEqual(len(government), len(SCENARIO_IDS) * 2)
        for scenario_id in SCENARIO_IDS:
            per_scenario = [p for p in government if p.scenario_id == scenario_id]
            self.assertEqual(sum(p.n_tasks for p in per_scenario), 1000)

    def test_expected_total_calls(self) -> None:
        plans = design_lib.build_cell_plans(self.experiment)
        main_calls = sum(plan.n_tasks for plan in plans)
        self.assertEqual(main_calls, 4000)
        anchors = sum(len(design_lib.anchor_plan(self.experiment, plan)) for plan in plans)
        self.assertEqual(anchors, 360)


class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenarios = design_lib.load_scenarios()
        cls.prompts = cfg.load_prompts_config()
        cls.render_config = cls.prompts["render"]

    def _render(self, condition: str, scenario_id: str, task_index: int = 0, laws=None):
        scenario = self.scenarios[scenario_id]
        task = design_lib.sample_task(
            scenario, run_id="render", cell_id=f"{condition}__{scenario_id}", task_index=task_index
        )
        prompt_id, prompt_cfg = render_lib.select_prompt(self.prompts, condition, "en")
        return render_lib.render_prompt(
            scenario=scenario,
            task=task,
            prompt_id=prompt_id,
            prompt_config=prompt_cfg,
            render_config=self.render_config,
            answer_protocol="free_text",
            language="en",
            laws=laws,
        )

    def test_prefix_stable_within_cell(self) -> None:
        first = self._render("generic", "border_defense", 0)
        second = self._render("generic", "border_defense", 1)
        self.assertEqual(first.prefix_sha256, second.prefix_sha256)
        self.assertEqual(first.prompt_archive_id, second.prompt_archive_id)
        # 但任务屏与整条 user message 必须不同
        self.assertNotEqual(first.task_screen_text, second.task_screen_text)
        self.assertNotEqual(first.user_message_sha256, second.user_message_sha256)

    def test_prefix_differs_across_conditions_and_scenarios(self) -> None:
        generic = self._render("generic", "border_defense", 0)
        government = self._render(
            "government",
            "border_defense",
            0,
            laws=[({"law_text_id": "LAW", "title_en": "T", "jurisdiction": "CN"}, "第一条 测试。")],
        )
        other_scenario = self._render("generic", "disease_diagnosis", 0)
        self.assertNotEqual(generic.prompt_archive_id, government.prompt_archive_id)
        self.assertNotEqual(generic.prompt_archive_id, other_scenario.prompt_archive_id)

    def test_government_without_laws_raises(self) -> None:
        """忘了注入法规文本必须直接报错，而不是静默跑出一批无干预数据。"""
        with self.assertRaises(ValueError):
            self._render("government", "border_defense", 0, laws=None)

    def test_government_requires_law_material(self) -> None:
        rendered = self._render(
            "government",
            "border_defense",
            0,
            laws=[({"law_text_id": "TEST_LAW", "title_en": "T", "jurisdiction": "CN"}, "第一条 测试文本。")],
        )
        self.assertIn("TEST_LAW", rendered.prefix_text)
        self.assertIn("第一条 测试文本。", rendered.prefix_text)

    def test_shared_block_is_identical_across_conditions(self) -> None:
        """两版 prompt 的唯一差异是 condition_block：shared_block 必须逐字相同。"""
        _, generic = render_lib.select_prompt(self.prompts, "generic", "en")
        _, government = render_lib.select_prompt(self.prompts, "government", "en")
        self.assertEqual(
            render_lib.normalize_ws(str(generic["shared_block"])),
            render_lib.normalize_ws(str(government["shared_block"])),
        )
        self.assertTrue(render_lib.normalize_ws(str(generic["condition_block"])))
        self.assertTrue(render_lib.normalize_ws(str(government["condition_block"])))

    def test_table_rows_follow_attribute_order(self) -> None:
        scenario = self.scenarios["border_defense"]
        task = design_lib.sample_task(scenario, run_id="t", cell_id="c", task_index=3)
        table = render_lib.build_task_table(scenario, task, self.render_config)
        labels = [line.split("|")[1].strip() for line in table.splitlines()[2:]]
        expected = [scenario.attribute(a).label_en for a in task.attribute_order]
        self.assertEqual(labels, expected)

    def test_missing_language_raises(self) -> None:
        scenario = self.scenarios["border_defense"]
        task = design_lib.sample_task(scenario, run_id="t", cell_id="c", task_index=0)
        prompt_id, prompt_cfg = render_lib.select_prompt(self.prompts, "generic", "en")
        with self.assertRaises(KeyError):
            render_lib.render_prompt(
                scenario=scenario,
                task=task,
                prompt_id=prompt_id,
                prompt_config=prompt_cfg,
                render_config=self.render_config,
                answer_protocol="free_text",
                language="zh",
            )


class TestIoUtils(unittest.TestCase):
    def test_dedupe_helpers_use_consistent_shapes(self) -> None:
        """existing_values 返回字符串集合，existing_keys 返回元组集合。

        历史 bug（2026-09-18 pilot 发现）：调用处把 existing_keys（元组集合）
        当字符串集合用，导致 _prompt_archive.jsonl 每次启动重复写入前缀。
        """
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            archives = Path(tmp) / "archive.jsonl"
            archives.write_text(
                json.dumps({"prompt_archive_id": "aaa"}) + "\n"
                + json.dumps({"prompt_archive_id": "bbb"}) + "\n",
                encoding="utf-8",
            )
            values = io_utils.existing_values(archives, "prompt_archive_id")
            self.assertEqual(values, {"aaa", "bbb"})
            self.assertIn("aaa", values)
            self.assertNotIn("ccc", values)

            responses = Path(tmp) / "responses.jsonl"
            responses.write_text(
                json.dumps({"run_id": "r", "task_id": "t1"}) + "\n",
                encoding="utf-8",
            )
            keys = io_utils.existing_keys(responses, ["run_id", "task_id"])
            self.assertIn(("r", "t1"), keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
