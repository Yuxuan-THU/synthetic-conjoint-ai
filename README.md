# AI 联合实验的合成数据模拟（Synthetic Conjoint AI）

用 LLM 模拟人类联合实验（conjoint experiment）的受访者，构造可与人类样本对照的"硅基样本"。

- **研究问题**：在 AI 风险与中美 AI 竞争背景下，AI 的公共决策偏好是否与人类一致？当把官方 AI 法规文本作为 treatment 注入时，AI 的偏好如何改变？
- **研究工具**：两个 conjoint 情景——AI 边境防御系统评估（"夜隼"）、AI 致命疾病诊断系统评估（"灵智"）；每个情景 5 个属性 × 3 个水平，强制二选一。
- **实验条件**：`generic`（无外力，基于自身知识推理）vs `government`（严格遵循所附法规文本）。
- **模型**：首批 DeepSeek（中国开源）；后续 智谱 GLM / 豆包（中国闭源）、OpenAI / Anthropic（美国闭源）。
- **样本**：每个（条件 × 情景）约 1 000 次选择，分早/中/晚三个时段执行。
- **负责人**：苏宇轩（代码、prompt、国内模型）；Huhe 老师（国外闭源模型、prompt draft、conjoint 分析 code、论文起草）；孟老师（研究统筹）。
- **当前阶段**：代码已全部写完并通过自检（19 个单元测试 + 全链路 `--mock` 验证）；
  待提示词定稿与法规文本人工确认后即可真实开跑。下一步与待确认事项见 `docs/00_work-plan.md` §15。

## 文件地图（每个文件是做什么的）

数据流单向、每个环节的产物都能由代码重建：

```text
data/collection/config/*.yaml
        │  01 冻结任务矩阵 → data/raw/design/
        │  02 构建法规文本 → data/raw/legal_texts/
        │  03 调用模型     → data/raw/responses/          ← 唯一花钱的一步
        ▼
source/cleaning/01–02  ──►  outputs/data/                  ← 解析答案、构造长表
        ▼
source/analysis/01–04  ──►  outputs/{tables,figures}/      ← 论文用表与图
```

读表约定：**「提交」** = 随 Git 提交（配置、研究工具、文档，体积小、无隐私、复现必需）；
**「运行后生成」** = 跑对应脚本才出现、默认不进 Git、可随时重建。
各目录里的 `.gitkeep` 只是占位文件，保证空目录能进 Git。

### 根目录

| 文件 | 作用 |
|---|---|
| `README.md` | 项目说明 + 本文件地图 |
| `CHANGELOG.md` | 唯一的变更记录（项目/数据/清洗/分析/论文/幻灯片/复现）；`AGENTS.md` 要求推送前必须更新 |
| `AGENTS.md` | 仓库规则：推送前更新 CHANGELOG、文件归属、不得在子目录新建 README/CHANGELOG |
| `requirements.txt` | Python 依赖（采集、清洗分析、PDF 抽取、绘图四组） |
| `.env.example` | 环境变量模板；复制成 `.env` 后填 API key。真实 `.env` 永不提交 |
| `.gitignore` | 忽略密钥、原始响应与 outputs 产物；**例外放行** `data/raw/{instrument,legal_texts,design}/` |

### `docs/`：方案与决策（代码的人读依据）

| 文件 | 作用 |
|---|---|
| `00_work-plan.md` | 总工作方案：因子结构、样本量、prompt 方案、法规文本问题、成本、里程碑、Q1–Q21 决策清单、§15 运行手册 |
| `01_design-spec.md` | 设计规格：随机化算法与不变量、三个指纹的空间定义、渲染顺序、落盘与归档规格——`design.py`/`render.py` 的实现依据 |
| `02_prompt-freeze.md` | 两版提示词的完整冻结正文：system prompt 全文与 sha256、每次调用的消息结构、输出约定 |
| `03_meeting-notes-2026-09-17.md` | 2026-09-17 技术对齐会纪要（含逐字稿） |
| `project-notes.md` | 研究问题、假设、变量操作化、分析计划、决策日志、待办 |

### `data/collection/`：采集（等价于"实施问卷"）

三个入口脚本按序号执行；`config/` 是实验参数的唯一来源；`_llm/` 是内部库（下划线开头，`run_all.py` 不会自动执行）。

| 文件 | 作用 |
|---|---|
| `01_build_design_matrix.py` | 生成并**冻结**随机任务矩阵（主任务 + 锚点）→ `data/raw/design/`；含不变量校验与随机化诊断 |
| `02_build_legal_texts.py` | 构建 treatment 法规文本（`manual/` 校订稿 > 官方页面 `fetch` > 本地 `pdf`）→ txt + `manifest.csv` + `quality_report.csv` |
| `03_run_experiment.py` | **主运行器**：渲染 → 调用 API → 追加写 JSONL；支持 `--dry-run`/`--mock`/断点续跑/时段配额/守卫检查。唯一会真实花钱的脚本，被 `replication/run_all.py` 显式排除 |
| `config/experiment.yaml` | 样本量（每格 1000）、时段与配额、锚点设置、答案协议、守卫开关、run_id 命名约定 |
| `config/models.yaml` | 模型注册表（`enabled` 开关）、采样参数、价格表；DeepSeek 已启用，GLM/豆包/OpenAI/Anthropic 预置停用 |
| `config/scenarios.yaml` | 两情景的 vignette 与 5 属性 × 3 水平展示文本、`dominance_rank`（支配诊断用） |
| `config/prompts.yaml` | generic/government 两版 system prompt、任务屏与法规块模板、三种答案指令、版本状态（当前 `frozen`，2026-09-18） |
| `config/legal_texts.yaml` | 法规清单、取文方式、质检锚点（`must_contain`）、人工审核状态 |
| `_llm/config.py` | 配置/路径/环境变量加载与 `config_sha256`（配置变了 = 新设计） |
| `_llm/design.py` | 随机化引擎：有序不放回抽样、三个任务指纹、单元 × 时段配额、锚点计划 |
| `_llm/render.py` | system prompt 与任务屏渲染、prefix 归档 id（哈希同时覆盖 system prompt） |
| `_llm/providers.py` | DeepSeek/智谱/火山/OpenAI/Anthropic 统一调用接口，重试与错误分类 |
| `_llm/io_utils.py` | 哈希、北京时间、JSONL 追加写、断点续跑去重、稳定种子 |
| `_llm/tests/run_tests.py` | 19 个单元测试，锁定"必须满足的不变量"；直接 `python` 运行，无需 pytest |
| `_llm/__init__.py` | 包声明，导出可被 import 的子模块 |

### `data/raw/`：原始输入与原始响应（只读）

| 路径 | 提交？ | 作用 |
|---|---|---|
| `instrument/` | 提交 | 人类问卷原件：`AI 联合分析实验.docx`、抽取文本、Word 批注 |
| `legal_texts/{law_text_id}.txt` | 提交 | treatment 法规纯文本（CN 暂行办法、US NIST AI RMF） |
| `legal_texts/manifest.csv` | 提交 | 版本登记：来源 URL、sha256、字符数/token 估算、`review_status` |
| `legal_texts/quality_report.csv` | 提交 | 自动质检结果（锚点字符串是否命中、条文数） |
| `legal_texts/manual/` | 提交 | 人工校订稿目录，同名 `{id}.txt` 存在时优先使用 |
| `design/{run_id}__tasks__{scenario}.csv` | 提交 | **冻结的随机题目**（只是题面，不含任何模型回答）；每情景一份 |
| `design/{run_id}__session_plan.csv` | 提交 | 单元 × 时段的任务索引区间与配额 |
| `design/{run_id}__design_manifest.json` | 提交 | 种子、配置指纹、随机化诊断 |
| `design/attribute_metadata.csv` | 提交 | 属性/水平字典，清洗与分析脚本读它 |
| `responses/{run_id}__{session}.jsonl` | 运行后生成 | **真实回答**：一行一次调用，含题面、prompt 哈希、原始输出、解析结果、token 用量 |
| `responses/{run_id}__{session}__errors.jsonl` | 运行后生成 | 调用失败记录（错误类型、HTTP 状态、重试次数），不污染主数据 |
| `responses/_prompt_archive.jsonl` | 运行后生成 | 提示词前缀归档（含法规全文，只存一份；响应行只引用 id） |
| `responses/{run_id}__run_manifest.json` | 运行后生成 | 该 run 的模型、参数、config 指纹、已跑时段 |

### `source/cleaning/`：响应 → 分析数据

| 文件 | 作用 |
|---|---|
| `01_parse_responses.py` | 自由文本 → 二选一 `choice_panel`；同时输出解析质量汇总与 200 条人工核对样本 |
| `02_build_analysis_data.py` | 构造 AMCE 回归用的长表 `choice_long` / `choice_option_long` 与重复任务分组 |
| `_parse_lib.py` | 答案解析器（5 级策略 + 置信度分级），自带 10 条自测用例，可单独运行 |
| `_common.py` | 路径常量、parquet + csv 双写、响应文件发现、`MOCK_` 过滤规则 |

### `source/analysis/`：结果产出

| 文件 | 作用 |
|---|---|
| `01_descriptives.py` | 分单元/时段的描述统计、解析质量、成本核算与图 |
| `02_conjoint_amce.py` | **论文核心**：AMCE、treatment 交互项、法域交互与图 |
| `03_variance_checks.py` | 稳健性：锚点一致性（同题重复 12 次）、时段效应、属性行序效应 |
| `04_text_analysis.py` | 解释文本：长度、话语框架词频、条件差异；可选 LLM 结构化编码 |
| `_common.py` | AMCE 估计（无截距 OLS + 按方案对聚类标准误）、读表、绘图设置 |

### `outputs/`：由代码生成（不要手改）

| 子目录 | 提交？ | 内容 |
|---|---|---|
| `data/` | 运行后生成 | `choice_panel`、`choice_long`、`choice_option_long`、`duplicate_groups`（parquet + csv 双份） |
| `tables/` | 提交 | 结果表：`amce_*`、`descriptives_*`、`anchor_consistency`、`session_effects`、`text_*`、`cost_summary` 等 |
| `figures/` | 提交 | `amce_*.png`、`descriptives_*.png`、`anchor_*`、`session_*`、`text_frameworks.png` |
| `models/` | 运行后生成 | 预留给拟合的模型对象（混合 logit 等），当前未使用 |
| `other/` | 运行后生成 | 运行日志、`dryrun__*.md` 样张、`parse_audit_sample.csv`、LLM 编码原始输出 |

### `replication/`：一键复现与产物登记

| 文件 | 作用 |
|---|---|
| `run_all.py` | 按文件名顺序跑 `source/cleaning/*` → `source/analysis/*`；`03_run_experiment.py` 被排除，必须人工执行 |
| `run_all.R` | R 版同构入口（与 Huhe 的 R 分析代码对接） |
| `MANIFEST.csv` | 全部产物的登记表：输出路径 ↔ 来源脚本 ↔ 输入数据 ↔ QA 状态；投稿时补 git commit 与生成时间 |

### `manuscript/` 与 `slides/`

| 路径 | 作用 |
|---|---|
| `manuscript/source/` | 论文工作稿源文件；`assets/` 放图与表素材 |
| `manuscript/source/references.bib` | BibTeX 文献库（建议由 Zotero / Better BibTeX 导出，保持引用键稳定） |
| `manuscript/releases/` | 定稿版本（提交的 PDF） |
| `slides/source/`、`slides/releases/` | 演示文稿源文件与定稿版本，结构同上 |

### 运行时文件的命名规律

- 一律用双下划线 `__` 分隔字段，便于 glob：`{run_id}__{session}.jsonl`、`{run_id}__tasks__{scenario}.csv`。
- `{run_id}` 建议按 `{date}_{model}_{condition}_{scenario}_{session}` 组织（见 `experiment.yaml` 的 `run_id_convention`），例如 `2026-10-05_deepseek_main`。
- 任务 id 带语义：`{cell_id}::main-0007`、`{cell_id}::anchor-02-rep05`；锚点的重复序号只在 `task_id` 里、不在种子里（所以 12 次重复共用同一道题）。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env          # 填入 DEEPSEEK_API_KEY

# 1) 自检（不需联网、不花钱）
python data/collection/_llm/tests/run_tests.py
python source/cleaning/_parse_lib.py

# 2) 冻结随机任务矩阵（主任务 4000 + 锦点 360）
python data/collection/01_build_design_matrix.py --run-id <run_id>

# 3) 准备 treatment 法规文本（抓官方原文 + 质检）
python data/collection/02_build_legal_texts.py

# 4) 先看会发出去什么（不调 API）
python data/collection/03_run_experiment.py --run-id <run_id> --dry-run

# 5) 不花钱跑通全链路（伪回答，清洗默认忽略 MOCK_ 数据）
python data/collection/03_run_experiment.py --run-id MOCK_demo --mock --skip-guards --limit-per-cell 30

# 6) 真实调用（三个时段各触发一次）
python data/collection/03_run_experiment.py --run-id <run_id> --session morning

# 7) 清洗 + 分析
python replication/run_all.py
```

⚠️ `replication/run_all.py --include-collection` **不会**调用付费 API：
`03_run_experiment.py` 被显式排除，必须人工带参数执行。

## 目录说明

逐文件职责见上文「文件地图」；本仓库遵循 [research-project-template](https://github.com/Yuxuan-THU/research-project-template) 的生命周期结构：

```text
docs/                研究计划、设计规格、提示词冻结、会议记录
data/collection/     LLM 调用代码（等价于"实施问卷"）+ 配置文件
data/raw/            原始输入与原始响应（法规文本、冻结任务矩阵、JSONL 响应）
source/cleaning/     响应解析与分析数据构造
source/analysis/     conjoint 估计、稳健性检验、文本分析
outputs/             由代码生成的表、图、数据
manuscript/          论文工作稿与冻结版本
slides/              演示文稿
replication/         一键复现入口与结果—代码—数据对照表
```

## 环境与运行

```bash
pip install -r requirements.txt
cp .env.example .env          # 填入 DEEPSEEK_API_KEY
python replication/run_all.py                        # 清洗 + 分析
python replication/run_all.py --include-collection   # 含采集阶段（03_run_experiment.py 被排除，不会调 API）
```

## 数据与隐私

- 本项目数据为模型生成的合成数据，不含个人可识别信息。
- `.env`、`data/raw/responses/`、`outputs/{data,models,other}/` 默认不进入 Git；
  `data/raw/{instrument,legal_texts,design}/`（研究工具、treatment 材料、冻结任务矩阵）为例外，已提交。
- 投稿阶段建议将 `responses/*.jsonl` 与冻结任务矩阵打包发布到 OSF/Zenodo，并在 `replication/MANIFEST.csv` 中登记。

## 关键文档

| 文件 | 内容 |
|---|---|
| `docs/00_work-plan.md` | 完整工作方案 + 待确认问题 Q1–Q21 |
| `docs/01_design-spec.md` | 随机化算法、渲染规则、字段规格（代码实现依据） |
| `docs/02_prompt-freeze.md` | 两版提示词的完整冻结正文（可直接复制） |
| `docs/03_meeting-notes-2026-09-17.md` | 2026-09-17 技术对齐会纪要（含逐字稿） |
| `docs/project-notes.md` | 研究问题、操作化、分析计划、决策日志 |
