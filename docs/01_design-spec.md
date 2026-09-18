# 设计规格（Design Spec）v1

本文件是 `data/collection/01_build_design_matrix.py` 与 `data/collection/_llm/render.py` 的**实现依据**。定稿后不再随意改动；如需改动，同步更新 `docs/00_work-plan.md` 与根目录 `CHANGELOG.md`。

---

## 1. 因子

| 因子 | 层次 | 是否随机分配给每次调用 |
|---|---|---|
| `condition` | generic / government | 否（由运行器参数决定，按 run 分层） |
| `scenario` | border_defense / disease_diagnosis | 是（各 50%） |
| `language` | en / zh | 见 Q4（默认 en 主跑） |
| `jurisdiction` | CN / US（默认，见 Q3） | 在 government 条件内随机 |
| `session` | morning / afternoon / evening | 由运行时刻决定，不由设计矩阵决定 |
| `task` | 见 §2 | 是 |

---

## 2. 任务（task）生成算法

**输入**：`scenarios.yaml` 中某情景的 5 个属性，每个属性 3 个水平（水平 = `level_id` + 各语言展示文本）。

**算法**（`_llm/design.py::sample_task`）：

```
seed  = stable_seed(run_id, cell_id, task_kind, task_index)   # 由 hash 派生，保证可重放
rng   = random.Random(seed)

for each attribute k in scenario.attributes:
    (a_k, b_k) = rng.sample(levels[k], 2)   # 有序不放回 → 甲≠乙，且 6 种有序对等概率

attr_order = rng.sample(scenario.attribute_ids, 5)   # 属性行序随机（批注要求）
```

> 关于“甲乙左右位随机化”：`rng.sample(levels, 2)` 返回的是**有序**对，
> 已经从 6 种排列中等概率抽取，因此“哪个方案落在 Option A 列”**已经被随机化了**。
> 再叠加一层位置交换只会引入冗余变量，所以代码**不做**这件事（即 Q12 的默认建议）。
> 锦点任务的各种重复共用同一任务：种子里**不含** `repeat_index`，只有 `task_id` 含它
> （为了断点续跑去重）。

**三个指纹**（分别对应三种“重复”口径，分析时不要混用）：

| 字段 | 含义 | 可能取值数 |
|---|---|---|
| `task_signature` | 呈现屏（含左右位与行序） | 6⁵ × 5! = 933 120 |
| `task_signature_pair` | 同一对方案（含左右位，不含行序） | 6⁵ = 7 776 |
| `task_signature_unordered` | 同一对档案（无左右位/行序） | 3⁵ = 243 |

**必须满足的不变量**（已写进单元测试 `_llm/tests/run_tests.py`，19 个测试全部通过）：

1. 对每个属性，`a_k != b_k`（批注：两种方案的随机值必须不同）；
2. 5 个属性全部出现且各出现一次，行序是完整随机排列；
3. 对固定 `(run_id, cell_id, task_kind, task_index)` 可完全重放；
4. 每个属性的 6 种有序对频次近似均匀（卡方 df=5，p > 0.01）；
5. 锦点重复共用同一任务，但 `task_id` 各不相同；
6. 各时段的任务索引区间互不重叠且覆盖全部任务；
7. 同一单元内渲染前缀保持稳定（prefix cache 与归档正确性的前提）。

---

## 3. 消息渲染（render.py）

一次调用的消息 = system prompt + user message（法规材料块 + 情景 vignette + 任务屏）。渲染顺序：

```
[system prompt]                       ← prompts.yaml，条件相关
[user message]                        ← 顺序固定，保证 prefix cache 命中
   1) [仅 government 条件] 法规材料块（law_texts/*.txt 全文，带 id 与标题行）
   2) 情景 vignette（按 language 取 zh/en）
   3) 任务屏引言
   4) 任务屏：属性表（按 attr_order 排列；列头 Option A / Option B）
   5) 提问句 + 答案格式指令（按 answer_protocol）
```

- 第 1)–3) 段构成 prompt 前缀（同一条件与情景内逐次不变，只归档一次）；第 4)–5) 段构成任务屏（逐任务不同）。
- 属性表用纯文本或 Markdown 表格均可，**同一 run 内必须固定一种**（记为 `render_style`）。
- 水平文本必须使用 attribute table 中给出的**完整描述**（不是缩写），因为描述本身是 treatment 的一部分。
- 法规材料块放在**最前（情景之前）**：内容对全部任务不变 → 落在 prefix 稳定区，最大限度命中缓存（2026-09-18 定稿顺序，`render.py` 即按此实现）。

### 3.1 英文消息示例（government 条件，border_defense，仅示意）

```
The following regulations and official guidance are attached. They establish the
institutional and regulatory framework that governs your recommendation.

<<<ATTACHED_MATERIALS
[<law_text_id>] <title_en> (<jurisdiction>)

<法规全文>
ATTACHED_MATERIALS>>>

Imagine you are ... (vignette)

Please review the two options below. Each option is a different version of the
same system, described by the following performance characteristics.

| Performance characteristic | Option A | Option B |
|---|---|---|
| R&D Institution | Public R&D institutions ... | Multinational tech corporations |
| ... | ... | ... |

Which option do you choose? Respond with your choice (Option A or Option B)
followed by a short explanation.
```

generic 条件没有法规材料块，其余相同。

---

## 4. 提示词与版本控制（prompts.yaml → docs/02_prompt-freeze.md）

- 每次调用记录 `prompt_id`（如 `generic_v2`）与 `prompt_sha256`。
- 任何文字改动必须新建 `prompt_id`（v2、v3…），**禁止原地覆盖**；旧版本保留在 yaml 中并标注 `deprecated: true` 与停用日期。
- 已经跑过数据的 prompt 版本永不复用编号。

---

## 5. 法规文本（treatment 材料）

- 目录只放最终纯文本：`data/raw/legal_texts/{law_text_id}.txt`（随仓库提交；没有 manifest、质检报告与人工校订目录）。
- 来源 URL / PDF 路径、标题与年份、质检锚点（`must_contain`）、页面剪裁标记等全部登记在 `data/collection/config/legal_texts.yaml`。
- `02_build_legal_texts.py` 按该配置重建 txt（已存在则跳过，`--force` 才重抓，写入前校验锚点）；文本 sha256 由 `03_run_experiment.py` 在每次调用时现算，写入每一行响应数据的 `law_text_sha256`，用于溯源。
- 命名规则 `{法域}_{简称}_{年份}.txt`。当前两份：

| law_text_id | 法域 | 体量 |
|---|---|---|
| `CN_generative_ai_interim_measures_2023` | CN | 3 668 字符 ≈2 325 token |
| `US_nist_ai_rmf_2023` | US | 105 623 字符 ≈26 406 token |

两份文本 2026-09-18 经 Huhe 确认（全文口径、不节选）；法域篇幅差异（约 10 倍）在论文中说明。

---

## 6. 原始响应落盘（JSONL，一行一次调用）

文件命名：`data/raw/responses/{run_id}__{session_label}.jsonl`

- 固定字段见 `docs/00_work-plan.md` §9；
- **只追加**，不重写；重跑同 `run_id` 时按 `(run_id, call_index)` 去重；
- 单次调用失败写 `data/raw/responses/{run_id}__{session_label}.errors.jsonl`，字段含 `error_type / http_status / attempt / message`。

### 6.1 提示词归档（避免把法规全文重复写进每一行）

政府条件下法规全文可能长达 2.7 万 token（NIST AI RMF），若每个响应行都内嵌完整 prompt，4000 行会产生数百 MB 冗余。因此采用**前缀归档**：

- `data/raw/responses/_prompt_archive.jsonl`：只对**唯一前缀**写一行，键为
  `prompt_archive_id = sha256(system_prompt + "\n\n" + prefix_text)[:16]`，
  内容为该前缀的完整文本（system prompt + 法规材料块 + 情景 vignette + 任务屏引言）。

  ⚠️ 必须把 **system prompt 一起纳入哈希**：条件差异就写在 system prompt 里，
  只哈希 user 前缀会让 generic 与 government 撞到同一个 id（这个 bug 真实发生过，
  现有单元测试盯着它）。组合数上限：2 条件 × 2 情景 × 1 语言 × 2 法域 = 8 行；
- 每个响应行只写 `prompt_archive_id`、`prompt_prefix_sha256`、`task_screen_text`（任务屏本身短且逐任务不同）以及 `user_prompt_sha256`；
- 复现时 `prefix(archive)` + `task_screen_text` 拼回完整 prompt，并用 `user_prompt_sha256` 校验。

### 6.2 调用顺序与断点续跑

- 每个单元内**锦点任务排在主任务之前**：锦点数量少但对稳健性检验最关键，
  排在前面就不会被 `--limit` / `--limit-per-cell` 截掉。
- 去重键 = `(run_id, task_id)`；`task_id` 带 `repeat_index`，所以锦点的 12 次重复
  不会被误判为“已跑过”。

### 6.3 mock 模式

`03_run_experiment.py --mock` 不调 API，用确定性伪回答生成合规格式的 JSONL，
用于验证整条链路与给合作者演示。约定：mock 数据的 `run_id` 以 `MOCK` 开头，
清洗脚本默认**不读** `MOCK` 数据（只有显式 `--run-id MOCK_...` 时才会读），
因此伪数据不可能污染真实分析。

这样既保证逐次可复现，又不产生数量级冗余。

---

## 7. 分析数据规格（outputs/data/）

| 文件 | 粒度 | 说明 |
|---|---|---|
| `choice_panel.parquet` | 一次调用一行 | 原始 JSONL 扁平化 + 设计矩阵 join |
| `choice_long.parquet` | 一次调用 × 一属性一行 | 供 AMCE 回归用（`attribute / level_a / level_b / chose_a`） |
| `choice_option_long.parquet` | 一调用 × 一方案 × 一属性一行 | AMCE 的标准输入（`attribute / level / chosen`） |
| `anchor_consistency.parquet` | 一锚点任务 × 条件一行 | 重复抽样的选择分布 |
| `session_effects.csv` | 时段 × 条件 | 时段效应估计 |

所有分析脚本只读 `outputs/data/`，不直接读 `data/raw/`（模板规则：raw 只读输入，清洗产物落 outputs）。
