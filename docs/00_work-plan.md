# 工作方案

本文件是本项目唯一的规划文档：研究问题、研究设计、数据规格、执行安排、分析计划与交付清单都在这里。
技术细节另见两份专项文档：`docs/01_design-spec.md`（随机化算法、渲染与落盘规格）、`docs/02_prompt-freeze.md`（提示词正文与哈希）。

---

## 1. 研究问题与假设

**研究问题**

1. LLM 在联合实验（conjoint）任务上的选择偏好，是否以及在多大程度上能代表人类受访者的偏好？
2. 当把**官方 AI 法规文本**作为 treatment 注入时，模型（"government AI"）的偏好相对于"generic AI"发生什么变化？这是否可以理解为制度环境对 AI 决策的塑造？

**初步假设**（具体机制待与合作者确认后补充）

- H1：generic AI 与人类样本在属性边际效应（AMCE）的方向上大体一致，但在风险—效率权衡上更偏向某一端。
- H2：government 条件（注入法规）会显著改变"责任归属"与"安全"类属性的权重，且改变幅度与法规文本的具体内容相关。
- H3：同一任务重复调用不产生完全相同的回答，模型选择应被建模为概率分布而非确定性函数。
- H4：不同模型（开源/闭源 × 中/美）的 treatment 反应强度不同。

---

## 2. 研究设计

### 2.1 研究工具

两个 conjoint 情景。一次任务 = 屏幕上并排呈现两个方案（Option A / Option B）的 5 个属性，**强制二选一**并给出不超过 50 词的英文解释。

- **情景 A：AI 边境防御系统评估（"夜隼 / Night Falcon"）**
- **情景 B：AI 致命疾病诊断系统评估（"灵智 / IntelliMind"）**

### 2.2 属性与水平（每情景 5 属性 × 3 水平）

**情景 A**

| 属性 | 水平 1 | 水平 2 | 水平 3 |
|---|---|---|---|
| R&D Institution | 公共研发机构（公立大学、政府研究机构等） | 国内私营机构（私营科技公司） | 跨国科技企业 |
| Probability of Missing Military Targets | 15%（高）经常无法识别伪装目标 | 5%（中）复杂天气下偶尔漏掉目标 | 1%（低）几乎任何环境都能精准识别 |
| Probability of Civilian Casualties | 12%（高）经常把民用目标误认为军事目标 | 4%（中）偶尔误认，存在一定误伤风险 | 0.5%（低）极少误认，基本杜绝误伤 |
| Operational Timeliness | 实时分析（无延迟） | 1 分钟（轻微延迟） | 5 分钟（较长延迟） |
| Accountability Mechanism | 研发机构负责 | 现场指挥员负责 | 纳入国家豁免（视为技术意外，不追究责任） |

**情景 B**

| 属性 | 水平 1 | 水平 2 | 水平 3 |
|---|---|---|---|
| R&D Institution | 公共研发机构 | 国内私营机构 | 跨国科技企业 |
| Probability of Missed Diagnosis（假阴性） | 18%（高）每 5–6 名患者漏掉 1 人 | 8%（中）非典型案例偶发漏报 | 1%（低）几乎不漏 |
| Probability of Misdiagnosis（假阳性） | 22%（高）大量健康人接受不必要治疗 | 10%（中）部分健康人被误诊 | 0.5%（低）有效防止不必要治疗 |
| Diagnostic Efficiency | 即时出结果 | 当天反馈 | 一周后反馈 |
| Legal Accountability | 研发机构负责 | 主治医生及医疗机构负责 | 引入免责条款（视为技术意外，不追究责任） |

实际渲染使用英文水平文本（完整描述，不用缩写），逐字定义在 `data/collection/config/scenarios.yaml`；中文仅为阅读方便。

### 2.3 任务生成与随机化

- **纯随机**任务生成，不做正交/高效设计，完整模拟人类联合实验的随机过程。
- 每个属性独立抽样，**同一属性上甲、乙两方案的取值必须不同**（有序不放回 → 6 种有序对等概率，不允许并列）。
- 属性行序随机；甲/乙左右位由有序对抽样天然随机化，不额外叠加位置随机化。
- 任务空间 = 6⁵ × 5! = 933 120；纯随机抽 1 000 次时"同一对方案"的自然重复约 62 个，所以另设锚点任务专门检验一致性。
- 每次调用 memory-free（context-free），不带任何对话历史。
- 算法细节与三个任务指纹（呈现屏 / 方案对 / 档案）见 `docs/01_design-spec.md` §2。

### 2.4 实验条件（treatment）

| 条件 | 说明 |
|---|---|
| `generic` | 对照：基于自身知识与推理作答，不代入任何政府、政党或机构立场 |
| `government` | 注入官方 AI 法规全文，要求严格遵循所附材料（法域：CN / US） |

两版 system prompt 由同一段共用文本 + 各自的条件段拼成，唯一差异是条件段；完整正文与 sha256 见 `docs/02_prompt-freeze.md`（当前版本 `generic_v2` / `government_v2`，2026-09-18 冻结）。

### 2.5 因子结构与样本量

```
模型（DeepSeek → GLM / 豆包 → OpenAI / Anthropic）
  × 条件（generic | government）
  × 情景（border_defense | disease_diagnosis）
  × 法域（CN | US，仅 government 条件）
  × 时段（morning | afternoon | evening）
语言：仅英文（en）
```

| 单元 | 次数 | 说明 |
|---|---|---|
| 2 条件 × 2 情景 × 1000 | 4 000 | government 的 1000 次在 CN / US 各 500 |
| 锚点任务（5 任务 × 12 重复 × 6 单元） | 360 | 分离"时段差异"与"任务构成差异" |
| 合计 | **4 360 次调用** | |

- 分析单位：一次 API 调用 = 一位"硅基受访者"回答一屏任务 = 一个二选一观测。
- 锚点任务在每单元内固定 5 道题，重复 12 次并按轮转分配到三个时段；种子里不含重复序号（12 次共用同一道题），任务 ID 含序号（用于断点续跑去重）。

### 2.6 时段安排

- 早/中/晚三段，按北京时间人工各触发一次：morning 8:00–11:00、afternoon 13:00–17:00、evening 20:00–23:30。
- 不使用"自动 sleep 到指定时间"的常驻脚本；每个时段的任务索引区间互不重叠、可复现。

### 2.7 模型与采样参数

- 主跑：`deepseek-chat`（中国开源权重），`temperature=1.0`、`top_p=1.0`、`max_tokens=512`、`stream=false`。
- 不使用思维链模型（`deepseek-reasoner` 保持停用）。
- 后续复跑：智谱 GLM / 豆包（中国闭源，型号待定）、OpenAI / Anthropic（美国闭源，型号与版本串待定）。
- `base_url` 从环境变量读取，可指向官方 API 或转发地址。

---

## 3. 变量与数据规格

### 3.1 变量操作化

- **因变量**：`choice_parsed ∈ {A, B}`（强制二选一，无回避选项）。
- **自变量（属性）**：每情景 5 属性 × 3 水平的取值。
- **处理变量**：`condition ∈ {generic, government}`；government 条件下追加 `jurisdiction` 与 `law_text_sha256`。
- **协变量/检验变量**：`session_label`（时段）、`attribute_order`（属性行序）、`language`、`explanation_words`、`latency_ms`。
- **稳健性专用**：`is_anchor`、`task_signature_pair`（重复分组键）、`model_returned` / `system_fingerprint`（版本追踪）。

### 3.2 落盘字段（每次调用一行）

| 字段 | 说明 |
|---|---|
| `run_id` / `call_index` | 批号 / 全局序号 |
| `session_label` | morning / afternoon / evening |
| `requested_at_bj` / `responded_at_bj` | 北京时间与 UTC |
| `latency_ms` | 端到端延迟 |
| `model_requested` / `model_returned` | 请求模型名 / 服务端返回的模型 |
| `api_response_id` / `system_fingerprint` | 可追溯的服务端标识 |
| `temperature` / `top_p` / `max_tokens` / `seed` | 实际生效的采样参数 |
| `condition` / `scenario` / `jurisdiction` / `language` | 实验单元标识 |
| `prompt_id` / `prompt_sha256` | 提示词版本与哈希 |
| `law_text_id` / `law_text_sha256` | 注入法规的版本与哈希 |
| `task_id` / `task_seed` / `is_anchor` | 任务标识、种子、是否锚点 |
| `attribute_order` | 属性行序 |
| `a__*` / `b__*`（5×2 列） | 甲、乙两方案各属性取值（代码化） |
| `prompt_archive_id` / `prefix_sha256` | 提示词前缀归档引用（法规全文不逐行内嵌，见 `docs/01_design-spec.md` §6.1） |
| `task_screen_text` / `task_screen_sha256` | 该次任务屏文本与哈希 |
| `user_message_sha256` | 完整 prompt 校验值 |
| `response_raw` | 模型原始输出全文 |
| `choice_parsed` / `parse_method` / `parse_confidence` | 解析结果与置信度 |
| `explanation_words` | 解释词数（检查是否超 50 词） |
| `finish_reason` | stop / length（截断单独标记） |
| `usage_prompt_tokens` / `usage_completion_tokens` | token 用量与成本核算 |
| `duplicate_of_task_id` / 重复分组 | 同一方案对第几次被抽到（"identical 回应"检验） |

### 3.3 分析数据（`outputs/data/`）

| 文件 | 粒度 |
|---|---|
| `choice_panel` | 一次调用一行（原始响应 + 解析结果 + 框架词频） |
| `choice_long` | 一次调用 × 一个属性一行 |
| `choice_option_long` | 一次调用 × 一个方案 × 一个属性一行（AMCE 标准输入） |
| `duplicate_groups` | 自然重复任务的分组 |

### 3.4 可复现性设计

- 任务矩阵在跑之前**冻结**落盘（CSV，含种子与三个指纹），跑过的任务不可被静默改变。
- 每次调用记录：prompt 版本号 + sha256、法规文本 sha256、采样参数、完整 user 消息哈希。
- 随机种子由 `(run_id, cell_id, task_kind, task_index)` 派生，同一 run 可原样重放。
- JSONL 只追加、不重写；断点续跑按 `(run_id, task_id)` 去重；失败单独落盘不污染主数据。
- 法规全文只归档一次（`_prompt_archive.jsonl`），哈希同时覆盖 system prompt。
- 前缀顺序固定（法规材料块 → 情景 vignette → 任务屏引言），使同单元内前缀不变，最大化 prefix cache 命中。

---

## 4. 分析计划

### 4.1 第一部分：算法模拟

1. 描述统计与数据有效性：解析成功率、拒答/回避率、解释长度、截断比例；不合格样本剔除并报告。
2. 主效应：按 模型 × 条件 × 情景 估计 **AMCE**（Hainmueller, Hopkins & Yamamoto 2014），基准组在各单元间保持统一。
3. **Treatment 效应**：condition × 属性水平交互项（government 相对 generic 的 AMCE 变化），论文核心参数。
4. 与人类样本对照（n ≈ 3 000+，变量表待获取）：方向一致性 + 量级差异 + bootstrap。
5. 稳健性：① 时段效应（锚点任务为主）；② 呈现顺序效应；③ 属性行序效应；④ 剔除重复任务；⑤ 模型版本变化（`model_returned` / `system_fingerprint`）。

### 4.2 第二部分：文本分析

6. 解释文本的描述性对比：长度、超 50 词比例、责任/安全/效率/法规等框架词频，按条件比较。
7. 用固定版本的第三方模型对解释文本做结构化编码（是否援引法规、援引方式、核心权衡逻辑）；先人工标注 200 条建立 gold set，报告编码一致性。
8. 检验"选择 → 理由"的自洽性（例如选了高风险方案却以安全为主要理由），作为 LLM 决策过程有效性的证据。

### 4.3 方法与模型

- AMCE：无截距线性概率模型，标准误按方案对聚类（`source/analysis/_common.py`）；与 R 侧 `cregg` 口径对齐。
- 异质性：混合 logit 或带随机系数的条件 logit。
- 个体层选择概率：对锚点任务用重复抽样估计 p(选甲 | 任务)。

---

## 5. 法规文本（treatment 材料）

- 每个法域一份纯文本：`data/raw/legal_texts/{law_text_id}.txt`，命名规则 `{法域}_{简称}_{年份}.txt`。

| law_text_id | 法域 | 体量 | 来源 |
|---|---|---|---|
| `CN_generative_ai_interim_measures_2023` | CN | 3 668 字符 ≈2 325 token | 网信办官方页面抓取（原始 PDF 为扫描件，现成 OCR 错字过多，不可用） |
| `US_nist_ai_rmf_2023` | US | 105 623 字符 ≈26 406 token | NIST 官方 PDF 抽取（自愿性框架，非法律） |

- 来源 URL / PDF 路径、标题、质检锚点与页面剪裁标记登记在 `data/collection/config/legal_texts.yaml`；需要重建时运行 `02_build_legal_texts.py`（已有文件则跳过，`--force` 才重抓，写入前校验锚点）。
- 两份文本 2026-09-18 经 Huhe 确认（全文口径、不节选）；法域篇幅差异（约 10 倍）在论文中说明。
- 运行器在每次调用时对 txt 现算 sha256 写入响应行（`law_text_sha256`），用于溯源。

---

## 6. 执行与交付

### 6.1 代码与目录

```
data/collection/                    采集（等价于"实施问卷"）
├── config/
│   ├── experiment.yaml             样本量、时段、锚点、答案协议、守卫
│   ├── models.yaml                 模型注册表、采样参数、价格表
│   ├── scenarios.yaml              两情景 vignette + 属性/水平（英文展示文本）
│   ├── prompts.yaml                两版 system prompt（当前 v2，frozen）+ 渲染模板
│   └── legal_texts.yaml            法规登记：来源、标题、锚点、剪裁标记
├── _llm/                           内部库：config / design / render / providers / io_utils
├── 01_build_design_matrix.py       生成并冻结随机任务矩阵
├── 02_build_legal_texts.py         按 config 构建法规纯文本
└── 03_run_experiment.py            主运行器（--dry-run / --mock / 断点续跑 / 守卫）

data/raw/                           只读原始材料
├── instrument/                     联合实验问卷 docx 与抽取文本（研究工具存档）
├── legal_texts/                    CN / US 两份法规纯文本
├── design/                         冻结的任务矩阵与设计诊断
└── responses/                      原始响应 JSONL（运行后生成）

source/cleaning/                    响应解析 → 分析数据
source/analysis/                    描述统计 / AMCE / 稳健性 / 文本分析
outputs/{data,tables,figures,models,other}
replication/{run_all.py,run_all.R,MANIFEST.csv}
```

### 6.2 调用节奏与守卫

- 调用间隔 1.5–3 秒抖动，避免限流并让时段内时刻自然分散；每 50 次打印进度与累计成本；连续失败 8 次自动中止。
- 守卫：提示词必须处于 `frozen` 状态，否则拒绝开跑。
- `--dry-run` 输出将发送的样张（不调 API）；`--mock` 用确定性伪回答跑通全链路（`MOCK_` 数据清洗默认不读，不会污染分析）。

### 6.3 成本估算（DeepSeek）

- generic 条件：prompt ≈1 000 token；government 条件：法规 2 300–26 400 token；输出 ≈150 token。
- 4 360 次调用粗估 **$10 量级**（以官方价格页当日价为准），远低于闭源模型；本轮目标是验证流程与口径，而不是压缩成本。

### 6.4 脚本清单

| 阶段 | 脚本 | 作用 |
|---|---|---|
| 采集 | `data/collection/01_build_design_matrix.py` | 生成并冻结随机任务矩阵（主 4000 + 锚点 360），含不变量校验与随机化诊断 |
| 采集 | `data/collection/02_build_legal_texts.py` | 构建 treatment 法规文本（页面剪裁 + 页眉页脚清理 + 锚点校验） |
| 采集 | `data/collection/03_run_experiment.py` | 主运行器：渲染 → 调用 → 落盘 JSONL；断点续跑、时段配额、守卫 |
| 自检 | `data/collection/_llm/tests/run_tests.py` | 20 个单元测试，锁定设计不变量、渲染规则与去重工具 |
| 清洗 | `source/cleaning/01_parse_responses.py` | 自由文本 → 二选一 `choice_panel`；输出 200 条人工核对样本 |
| 清洗 | `source/cleaning/02_build_analysis_data.py` | 长表与重复任务分组 |
| 清洗 | `source/cleaning/_parse_lib.py` | 答案解析器（10 条自测用例） |
| 分析 | `source/analysis/01_descriptives.py` | 描述统计、解析质量、成本核算 |
| 分析 | `source/analysis/02_conjoint_amce.py` | AMCE + treatment 交互 + 法域交互（论文核心） |
| 分析 | `source/analysis/03_variance_checks.py` | 锚点一致性、时段效应、属性行序效应 |
| 分析 | `source/analysis/04_text_analysis.py` | 解释文本描述统计、框架词频、可选结构化编码 |

### 6.5 运行手册（按顺序）

```bash
# 0) 环境
pip install -r requirements.txt
cp .env.example .env        # 填入 DEEPSEEK_API_KEY

# 1) 自检（不联网、不花钱）
python data/collection/_llm/tests/run_tests.py
python source/cleaning/_parse_lib.py

# 2) 生成冻结的任务矩阵
python data/collection/01_build_design_matrix.py --run-id 2026-10-05_deepseek_main

# 3) 法规文本（两份 txt 已随仓库提交，无需重建；仅更换文本时才运行）
python data/collection/02_build_legal_texts.py

# 4) 先看会发出去什么（不调用 API，不需要密钥）
python data/collection/03_run_experiment.py --run-id 2026-10-05_deepseek_main --dry-run

# 5) 跑通链路但不花钱（伪回答，run-id 以 MOCK_ 开头会被清洗脚本自动忽略）
python data/collection/03_run_experiment.py --run-id MOCK_demo --mock --skip-guards \
    --session morning --limit-per-cell 30

# 6) 真实调用：三个时段各触发一次
python data/collection/03_run_experiment.py --run-id 2026-10-05_deepseek_main --session morning
python data/collection/03_run_experiment.py --run-id 2026-10-05_deepseek_main --session afternoon
python data/collection/03_run_experiment.py --run-id 2026-10-05_deepseek_main --session evening

# 7) 清洗 + 分析
python replication/run_all.py
```

### 6.6 已完成的自检

- 设计矩阵：4000 主任务 + 360 锚点，6 个单元，全部不变量校验通过；每属性有序对 `chi2(df=5)` 未超 p=0.01 临界值；被支配方案占比 22%–29%（已记录，见 §8.2）。
- 运行器：`--dry-run` 样张人工核对；generic / government / CN / US 渲染正确；前缀在单元内稳定、归档 id 在条件与情景间不撞号。
- 全链路 `--mock`：216 次伪调用 × 6 单元 × 3 时段 → 清洗 → 四个分析脚本全部退出码 0。
- 自检中修掉的问题（均已写入代码注释或测试）：归档 id 漏掉 system prompt；HTML 解析器把空元素当容器；解析器误识别 "option because"；锚点一致性按重复序号分组导致拆题；`chose_a` 缺失；matplotlib 中文字体缺失。

### 6.7 最小化验证（pilot）结论

2026-09-18 用独立批号 `2026-09-18_deepseek_pilot` 做了一次最小化真实调用，共 **54 次**（12 次锚点 + 42 次主任务，6 个单元 × 7 题，evening 时段）：

- **链路打通**：54/54 成功，0 失败、0 拒答、0 截断，无错误文件；断点续跑正确跳过已完成任务；延迟 p50 1.5 s；prompt 缓存命中约 89%；总成本 $0.025。
- **修复 1 个真实 bug**：`_prompt_archive.jsonl` 去重失效——`existing_keys` 返回元组集合而调用处按字符串判断，导致每次启动重复写入前缀（实测 6 个前缀写成 12 行）；新增 `existing_values`（单字段取值集合）替换调用，清理重复行并补单元测试（20 个测试全部通过）。
- **实际模型名**：请求 `deepseek-chat`，服务端返回 `model=deepseek-flash`（`system_fingerprint` 恒定 `aeb56401…`）；论文表述与成本核算以响应行记录的 `model_returned` / `system_fingerprint` 为准。
- **解析质量**：54 条全部解析出选项（A 21 / B 33），但置信度偏低（low 13 / medium 40 / high 1）：模型以 `Option A. 解释…` 开头而不含选择动词。已逐条核对 13 条低置信度回答，**全部取到正确选项**；若要提高置信度，可在解析器增加“回答开头即标签”规则（不改提示词）。
- **偏差**：1 条未给解释（仅 "Option B"）；3 条解释超过 50 词（最长 64 词，均值 39.5）；无拒答、无截断。
- **treatment 起效迹象**：government 条件的回答会援引具体条款（如 "Article 4(5)"、"GOVERN 2.3"、"MEASURE 2.6"）。
- **主跑成本外推**：按 pilot 单次成本外推 4 360 次 ≈ **$1.7**（generic $0.26 + government $1.26 + 锚点 $0.17）。
- **数据管理**：pilot 产物（任务矩阵、响应、日志、样张）归档到 `outputs/other/pilot_2026-09-18/`，不进入正式分析；`data/raw/responses/` 只保留共享的提示词归档。

---

## 7. 里程碑与分工

| 时间 | 交付 | 负责 |
|---|---|---|
| 9/17–9/20 | 方案与提示词定稿；法规文本定源 | 苏 + Huhe |
| 9/20–9/26 | 代码完成（设计矩阵 / 法规抽取 / 运行器 / 清洗 / AMCE 分析） | 苏 |
| 9/26–9/29 | 本地 dry-run + 小规模 pilot，人工核对解析质量 | 苏 |
| 9/30 前 | running script 发 Huhe 确认 | 苏 → Huhe |
| 10 月上旬 | DeepSeek 主跑 4 360 次（三个时段） | 苏 |
| 10 月中 | DeepSeek 结果分析；启动 GLM / 豆包 / OpenAI 复跑 | 苏 + Huhe |
| 10 月下旬 | 文本分析、稳健性检验、与人类样本对照 | 双方 |
| 11 月 | final draft + 投稿 | 双方 |

分工：苏宇轩（代码、提示词、国内模型）；Huhe（国外闭源模型、conjoint 分析口径、论文起草）；孟老师（研究统筹）。

---

## 8. 风险与未决事项

### 8.1 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| 法规文本不可用（扫描件 / OCR 乱码） | government 条件失效 | 只采用官方原文（§5），写入前锚点校验 |
| 法域文本篇幅差异（≈10 倍） | 篇幅效应与制度内容效应混淆 | 论文中明确说明，必要时做篇幅稳健性检验 |
| 答案格式不可解析 | 有效样本损失 | 解析器分级 + 200 条人工核对；失败率高时再讨论加格式指令 |
| 被支配方案（甲在全部可排序维度更优）占比 22%–29% | 选择过于容易，AMCE 方差变小 | 默认保留（忠于纯随机），论文中报告占比 |
| 模型版本静默更新 | 前后批次不可比 | 记录 `model_returned` / `system_fingerprint`，同一 run 在短时间窗内跑完 |
| API 限流或中断 | 数据缺口 | JSONL 追加写 + 断点续跑 + 失败重试与单独落盘 |
| DeepSeek 无 `seed` 参数 | 单次回答不可复现 | 视为设计事实，靠大样本与锚点重复刻画随机性 |

### 8.2 未决事项

1. **被支配方案占比 22%–29%**：严格纯随机会自然产生"甲在三个可排序维度上全面更优"的任务；默认保留，待确认是否接受。
2. **锚点重复次数**：当前 5 个任务 × 12 次重复 × 每单元，是否足够做时段效应与同任务一致性检验。
3. **人类样本对照数据**：待获取变量表，用于 AI 与人类的 AMCE 对照。
4. **闭源模型型号**：国内（倾向智谱 GLM）与国外（OpenAI / Anthropic）的具体型号与版本串。

---

## 9. 决策日志

- **2026-09-17**：采用纯随机任务生成，不做正交/高效设计——完整模拟人类联合实验的随机过程。
- **2026-09-17**：每次调用 memory-free（context-free），不复用对话历史。
- **2026-09-17**：输出必须记录执行任务的时间变量，用于时段检验。
- **2026-09-17**：同一属性上甲、乙取值必须不同；属性行序随机；每位受访者至少三屏（AI 端 1 次调用 = 1 屏 = 1 个选择）。
- **2026-09-17**：项目骨架按 research-project-template 建立；LLM 调用代码归入 `data/collection/`。
- **2026-09-18**：口径确定——法规文本从官方页面/官方 PDF 取原文；本轮只做 CN + US 两个法域；只做英文；统一采用英文版 vignette 口径；不使用思维链模型；`base_url` 可切换。
- **2026-09-18**：两份 treatment 法规文本确认（全文口径、不节选），法域篇幅差异在论文中说明。
- **2026-09-18**：提示词定稿为 v2（`generic_v2` / `government_v2`），v1 停用（未用于任何数据采集）；保留三项有意设计：generic 版原文不改、两版条件段不做长度对齐、trade-off 提示仅出现在 government 版。
- **2026-09-18**：法规材料目录精简为两份纯文本；移除采集端的法规确认门禁与登记表、质检报告、人工校订目录。
- **2026-09-18**：文档精简为「工作方案 + 设计规格 + 提示词冻结」三份；本文件并入原项目笔记内容。

---

## 10. 待办事项

- [x] 方案与决策口径确认；提示词 v2 定稿；法规文本确认。
- [x] 代码完成（采集 / 清洗 / 分析 + 20 个单元测试 + 解析器自测 + 全链路 mock 验证）。
- [ ] 确定国内闭源模型（倾向智谱 GLM）与具体型号串。
- [ ] 把 running script 发 Huhe 确认（10 月 1 日前）。
- [ ] DeepSeek 主跑 4 360 次（三个时段）。
- [ ] Huhe：国外闭源模型型号与版本串；conjoint 分析代码；论文可起草部分。
- [ ] 双方：结果就绪后推进 final draft 与投稿（目标 11 月）。
