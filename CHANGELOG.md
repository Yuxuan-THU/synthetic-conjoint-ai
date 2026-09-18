# CHANGELOG

本文件记录整个研究项目中具有研究意义、可能影响结果解释或正式交付的变化。

## Unreleased

### 项目

- 按 [research-project-template](https://github.com/Yuxuan-THU/research-project-template) 建立项目骨架（`docs/ data/ source/ outputs/ manuscript/ slides/ replication/`）。
- 确定本项目的结构映射：LLM 调用代码归入 `data/collection/`（等价于"实施问卷"），原始响应落 `data/raw/responses/`，清洗与分析分别归入 `source/cleaning/` 与 `source/analysis/`。
- 新增 `requirements.txt`、`.env.example`（只含占位符，真实密钥不进入版本控制）。
- `.gitignore` 在模板默认基础上例外放开 `data/raw/instrument/`、`data/raw/legal_texts/`、`data/raw/design/`（体积小、无隐私、复现必需），响应数据仍排除。
- `replication/run_all.py` 增加 `COLLECTION_MANUAL_ONLY` 排除集：`03_run_experiment.py` 会真实调用付费 API，禁止被自动化复现误触发。

### 数据

- 归档原始研究工具（联合实验问卷 docx、其可机读文本抽取结果、Word 批注抽取结果）至 `data/raw/instrument/`。
- 核查 `ai legal text/` 下 12 份材料的可机读文本量，确认 5 份为无文本层扫描件（加拿大 C-27、韩国 AI 基本法、中国三部法规的非 OCR 版本）；现成中国法规 OCR 文本存在大量错字（如"生成式人工智能玻务管理暂行办法""第一量总"），不可用于 treatment。
- **中国法规改为从网信办官方页面抓取**并剪除网页导航：`CN_generative_ai_interim_measures_2023` 现为 3 668 字符的干净原文（含第 1–24 条完整）。
- 美国 treatment 使用本地 NIST AI RMF 1.0 PDF：105 623 字符、估算 26 406 token，并清理了 50 行逐页重复的页眉页脚。
- 法规材料目录精简为两份纯文本（统一命名 `{法域}_{简称}_{年份}.txt`）：`CN_generative_ai_interim_measures_2023.txt` 与 `US_nist_ai_rmf_2023.txt`（原 `US_nist_ai_rmf_1_0_2023.txt` 重命名）；来源与文档信息登记在 `config/legal_texts.yaml`。原先的 `manifest.csv`（版本登记）、`quality_report.csv`（质检报告）与 `manual/`（人工校订目录）已移除。
- 从 docx 批注中抽取三条此前未进入会议纪要的硬约束：属性行序随机；同一属性上甲、乙取值必须不同；最少三次随机 task。
- 两份 treatment 法规文本经 Huhe 确认（2026-09-18，全文口径、不节选）；法域篇幅差异（≈2 325 vs ≈26 406 token）在论文中说明。

### 采集

- 新增 `data/collection/01_build_design_matrix.py`：生成并冻结随机任务矩阵。**主任务 4 000 + 锚点 360，共 6 个设计单元**。
  - 随机化规则：每属性有序不放回（6 种有序对等概率）、属性行序随机；任务空间 `6^5 × 5! = 933 120`。
  - 输出三个层次的指纹：`task_signature`（呈现屏）/ `task_signature_pair`（同一对方案）/ `task_signature_unordered`（同一对档案）。
  - 内置不变量校验与随机化诊断：各单元每属性有序对 `chi2(df=5)` 全部未超过 p=0.01 临界值；被支配方案占比 22%–29%（已记录待 Huhe 确认）。
  - 自然重复诊断：呈现屏自然重复不足 1 个、同一对方案约 62 个——说明**不能指望靠自然重复做一致性检验，锚点任务是必需的**。
- 新增 `data/collection/02_build_legal_texts.py`：按 config 抓取/抽取 treatment 文本（源页面显式起止标记剪裁 + 页眉页脚清理 + 锚点校验），写入 `data/raw/legal_texts/{law_text_id}.txt`，已存在则跳过。
- 新增 `data/collection/03_run_experiment.py` 主运行器：
  - memory-free 单轮调用；断点续跑（去重键 `run_id, task_id`）；时段配额互不重叠；守卫检查（提示词须 `frozen`）失败即拒绝开跑。
  - 法规全文不逐行内嵌，改为 `_prompt_archive.jsonl` 前缀归档 + 哈希校验，避免数百 MB 冗余。
  - 支持 `--dry-run`（渲染样张，不调 API、不需密钥）与 `--mock`（伪回答，跑通链路）。
  - 锚点任务排在主任务之前，避免被 `--limit` 截掉。
- 新增 `data/collection/_llm/` 内部库：随机化引擎、渲染器、厂商适配器（DeepSeek/智谱/火山/OpenAI/Anthropic 统一接口）、IO 与重试。
- 新增 `data/collection/_llm/tests/run_tests.py`：19 个单元测试全部通过。
- 移除法规文本门禁（2026-09-18）：删除 `03_run_experiment.py` 的 `review_status` 校验、`experiment.yaml` 的 `require_confirmed_legal_texts` 配置与 `02` 脚本的 `--set-review-status`；提示词 `frozen` 守卫保留。02 脚本简化为仅构建 txt；03 改为运行时对 txt 现算 sha256 并写入响应行的 `law_text_sha256`。

### 清洗

- 新增 `source/cleaning/01_parse_responses.py`：自由文本 → 二选一解析，带 `parse_method` / `parse_confidence` 分级，并输出 200 条人工核对样本（论文附录需报告解析准确率）。
- 新增 `source/cleaning/02_build_analysis_data.py`：构造 `choice_long`（调用 × 属性）与 `choice_option_long`（调用 × 方案 × 属性）以及重复任务分组。
- 新增 `source/cleaning/_parse_lib.py`：答案解析器（含 10 条自测用例，`python source/cleaning/_parse_lib.py` 可直接验证）。

### 分析

- 新增 `source/analysis/01_descriptives.py`：分单元/分时段的描述统计、解析质量、成本核算与图表。
- 新增 `source/analysis/02_conjoint_amce.py`：AMCE（无截距 OLS，按 `task_signature_pair` 聚类标准误）、treatment 交互效应（论文核心参数）、government 内部 CN vs US 法域交互。
- 新增 `source/analysis/03_variance_checks.py`：锚点一致性（同任务重复 12 次的确定性比例）、控制任务构成后的时段效应、同一对方案在不同属性行序下的一致性。
- 新增 `source/analysis/04_text_analysis.py`：解释长度与超 50 词比例、话语框架词频、generic vs government 框架差异检验，以及可选的 LLM 结构化编码（默认关闭）。

### 文档

- 提示词定稿并冻结：`prompts.yaml` 以 `generic_v2` / `government_v2` 为当前版本（`frozen`，2026-09-18 讨论定稿），v1 标记 `deprecated`（未用于任何数据采集，采集脚本不会再选中）；`docs/02_prompt-freeze.md` 只保留当前版本的完整正文（system prompt 全文 + sha256 + 消息结构 + 输出约定）。单元测试中的“两版字数对齐”断言替换为“shared_block 逐字相同”的单一差异校验（v2 文本不再等长；长度不对齐、两版不对称与 generic 原文均经 2026-09-18 复核确认保留）。
- `docs/01_design-spec.md` 修正渲染顺序为「法规材料块 → 情景 vignette → 任务屏」（与 `render.py` 实现一致；原规格写作“情景之后”），并同步更新 §3.1 示例与 §6.1 前缀描述。
- README 新增「文件地图」：逐目录、逐文件说明职责、数据流位置、生成时机与是否提交，并标明运行时文件的命名规律；同步修正「数据与隐私」对 `.gitignore` 例外的表述。
- 新增 `docs/00_work-plan.md`：完整工作方案，含实验因子结构、样本量、提示词方案、法规文本问题清单、成本估算、执行安排、字段字典、分析计划、里程碑、风险清单、Q1–Q21 待确认问题，以及 §15 代码交付清单与运行手册。
- 新增 `docs/01_design-spec.md`：任务随机化算法与不变量、三个指纹的空间定义、渲染顺序、提示词版本控制、法规文本 manifest 规格、响应落盘与前缀归档规格、分析数据规格。
- 新增 `docs/02_prompt-freeze.md`：两版提示词的完整冻结正文（system prompt 全文与 sha256、调用消息结构、输出约定），可直接复制使用。
- 建立 `docs/project-notes.md`：研究问题、四条初步假设、变量操作化、分析计划与决策日志。
- 归档 2026-09-17 技术对齐会纪要至 `docs/03_meeting-notes-2026-09-17.md`。
- `replication/MANIFEST.csv` 登记 20 项产物与对应脚本、输入数据。

### 自检中发现并修复的缺陷（均已写入代码注释或单元测试）

1. `prompt_archive_id` 只哈希 user 前缀、未覆盖 system prompt，导致 generic 与 government 撞号 —— 条件差异恰好全在 system prompt 里。
2. 两版提示词的条件段原稿字数相差 1.61 倍，与"字数对齐"要求冲突；补强 generic 后降到 1.16 倍。
3. HTML 转纯文本时把 `<meta>`/`<link>` 等空元素当作容器标签计数，深度永远无法归零，导致抓到页面却抽出 0 字符。
4. 答案解析器把 "option because" 中的 b 误识别为 Option B。
5. 锚点一致性原按含重复序号的 `task_id` 分组，12 次重复被拆成 12 个"各只有 1 次"的任务，导致结论完全相反。
6. `chose_a` 未写入 choice panel，导致稳健性脚本报 KeyError。
7. matplotlib 默认字体不含汉字，图中文字全部显示为方块。

### 待完成

- 真实调用 DeepSeek 主跑 4 360 次（三时段），以及后续 GLM / OpenAI / Anthropic 复跑。
- 论文中说明法域 treatment 篇幅差异（≈2 300 vs ≈26 400 token）；被支配方案占比 22%–29% 待 Huhe 确认。
