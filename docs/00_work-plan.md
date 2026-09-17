# 工作方案 v1

---

## 0. 一句话目标

把人类问卷里的 conjoint（联合实验）任务原样搬到 LLM 上：让同一个模型在**纯随机生成**的联合实验任务上重复做约 1000 次强制二选一，得到可与人样本（n≈3000+）对照的"硅基样本"；并用"注入官方 AI 法规"作为 treatment，检验模型偏好是否被制度文本改变。

---

## 1. 已定的设计（会议纪要 + docx 批注，不再讨论）


| 项             | 内容                                                                         | 来源             |
| ------------- | -------------------------------------------------------------------------- | -------------- |
| 研究工具          | 两个情景的 conjoint：①AI 边境防御系统评估（"夜隼"）②AI 致命疾病诊断系统评估（"灵智"）                      | docx           |
| 任务形式          | 一次任务 = 屏幕呈现两个方案（甲/乙）的 5 个属性 → 强制二选一 + ≤50 词英文解释                            | docx + 纪要      |
| 属性结构          | 每情景 5 个属性 × 3 个水平                                                          | docx           |
| 随机化           | **纯随机**，不做正交/高效设计；属性展示顺序随机；每个属性上甲乙两方案的取值**必须不同**                           | docx 批注        |
| 记忆            | 每次调用 context-free / memory-free，不带历史                                       | 纪要 00:17       |
| 条件（treatment） | generic/raw AI（无外力）vs government AI（严格遵循所附法规文本）                            | 纪要 01:32–07:16 |
| 模型            | 主跑 DeepSeek（中国开源）；后续 智谱 GLM/豆包（中国闭源）、OpenAI 或 Anthropic（美国闭源）              | 纪要 07:16–11:36 |
| 重复次数          | ~1000 次选择/条件；同一 identical 任务也可能给出不同回答，所以要留余量检验                             | 纪要 11:16–20:00 |
| 时段            | 早/中/晚三段（≈300+300+300），或至少"工作时间 vs 非工作时间"（北京时间）                             | 纪要 11:16–14:23 |
| 输出变量          | ①调用时间 ②随机任务内容（甲乙两方案）③AI 的选择 ④AI 的回应文本                                      | 纪要 23:16–25:16 |
| 分工            | 苏：写代码、改 prompt、定国内闭源模型；Huhe：国外闭源模型、两段 prompt draft、conjoint 分析 code、论文起草   | 纪要 待办          |
| 时间线           | 10/1 前把代码发给 Huhe → 先发 running script 确认 → DeepSeek 试跑 → 闭源模型重复 → 目标 11 月投出 | 纪要 25:16–27:31 |


### 1.1 docx 批注里额外发现的三条硬约束

从 `data/raw/instrument/AI 联合分析实验.docx` 的批注（`conjoint_instrument_comments.txt`）中抽出，会议里没细说，但直接决定代码怎么写：

1. **最少三次随机 task**；
2. **"性能特征"显示顺序随机**（属性行序随机）；
3. **方案具体特征值随机产生，随机值见 attribute table**；
4. **对每一个性能特征，两种方案的随机值必须不同**（即同一属性上甲 ≠ 乙，不允许并列）。

第 4 条影响很大：每个属性的 (甲,乙) 有序对只有 3×2=6 种，整个任务空间是 6⁵ = **7 776** 个任务（不是 3⁵=243，也不是 9⁵）。纯随机抽 1000 次，期望出现 **C(1000,2)/7776 ≈ 64 对重复任务**——正好可以用来检验"同一任务是否稳定给出同一回答"。

---

## 2. 两个情景的完整属性表（从 docx 抽出，代码里按此实现）

### 情景 A：AI 边境防御系统评估（"夜隼 / Night Falcon"）


| 属性                       | 水平 1                    | 水平 2               | 水平 3                 |
| ------------------------ | ----------------------- | ------------------ | -------------------- |
| 研发机构 R&amp;D Institution | 公共研发机构（公立大学、政府研究机构等）    | 国内私营机构（私营科技公司）     | 跨国科技企业               |
| 漏报军事目标概率                 | 15%（高）经常无法识别伪装目标，漏报频率较高 | 5%（中）偶尔在复杂天气下漏掉目标  | 1%（低）几乎任何环境都能精准识别    |
| 误伤平民目标概率                 | 12%（高）经常把民用目标误认为军事目标    | 4%（中）偶尔误认，存在一定误伤风险 | 0.5%（低）极少误认，基本杜绝误伤   |
| 作战时效                     | 实时分析（无延迟）               | 1 分钟（轻微延迟）         | 5 分钟（较长延迟）           |
| 问责机制                     | 研发机构负责                  | 现场指挥员负责            | 纳入国家豁免（视为技术意外，不追究责任） |


### 情景 B：AI 致命疾病诊断系统评估（"灵智 / IntelliMind"）


| 属性                       | 水平 1                    | 水平 2           | 水平 3                 |
| ------------------------ | ----------------------- | -------------- | -------------------- |
| 研发机构 R&amp;D Institution | 公共研发机构                  | 国内私营机构         | 跨国科技企业               |
| 漏诊概率（假阴性）                | 18%（高）平均每 5–6 名患者漏掉 1 人 | 8%（中）非典型案例偶发漏报 | 1%（低）几乎不漏            |
| 误诊概率（假阳性）                | 22%（高）大量健康人接受不必要的治疗     | 10%（中）部分健康人被误诊 | 0.5%（低）有效防止不必要治疗     |
| 诊疗效率                     | 即时出结果                   | 当天反馈           | 一周后反馈                |
| 法律问责制                    | 研发机构负责                  | 主治医生及医疗机构负责    | 引入免责条款（视为技术意外，不追究责任） |


> ⚠️ **中英文 vignette 不一致**：中文写"想象你正担任**公众代表**"，英文写"you are a **Deputy to the National People's Congress** serving on the National Security Commission"。两者不是语义等价的翻译，直接违反 prompt 里"treat semantically equivalent information identically"的要求。见 Q5。

---

## 3. 实验因子结构与样本量

```
模型 (DeepSeek → GLM/豆包 → OpenAI/Anthropic)
  × 条件 (generic | government)
  × 情景 (border_defense | disease_diagnosis)
  × 语言 (en | zh)                    ← 待定，见 Q4
  × 法域 (CN | US | …)                ← 仅 government 条件，待定，见 Q3
  × 时段 (morning | afternoon | evening)
```

**DeepSeek 主跑建议**（成本极低，见 §7）：


| 单元                              | 次数             | 说明                       |
| ------------------------------- | -------------- | ------------------------ |
| 2 条件 × 2 情景 × 1000              | 4 000          | 覆盖 Q6 的"每格 1000"口径       |
| 锚点任务（固定 15 个任务 × 10 次重复 × 3 时段） | 450            | 专门用来分离"时段效应"和"任务构成效应"    |
| 小计                              | **≈4 450 次调用** | 若 Q4 决定加中文版，则 ×2 ≈ 8 900 |


锚点任务的设计理由：如果不同时段的调用只是"随机任务不同"，那时段差异会和任务内容差异混淆。固定一组完全相同的任务在每个时段各跑一遍，才能干净地估计"同一任务在不同时段的回答是否不同"——这既是 robustness check，本身也是论文的一个卖点（可以在个体任务层面估计 p(选甲)，而不是只看单次选择）。

---

## 4. 提示词方案

### 4.1 现有两版 prompt（Huhe 草稿，纪要 01:32–03:32）

- **generic**：按自身 general knowledge 与 reasoning 选择，不代入任何政府/政党/机构立场；不让措辞影响判断；≤50 词英文解释。
- **government**：先读并严格遵守所附法规与官方指南的 policy position，不得引入材料之外立场；一致地适用各条款并权衡；≤50 词英文解释。

### 4.2 建议：长度对齐版（Q7，待你定稿后写入 config）

你提出的"把两段 prompt 字数对齐"我认为应当采纳，但**不能以削弱 treatment 强度为代价**。做法是：把 generic 版补强到与 government 版同等篇幅，而不是把 government 版删短。同时统一两版里重复出现的段落（语言效应那段、解释长度那段），只保留一处差异——**"是否有制度材料约束"**，这样 treatment 才是干净的单一差异。

建议统一的三段共用文本（两版完全相同）：

```
Do not let the language, wording, terminology, labels, or other linguistic
features of the prompt influence your judgment. Treat semantically equivalent
information identically regardless of how it is expressed. Do not infer
additional meaning from terminology or phrasing. Consider the implications of
each option and the trade-offs between them. Provide a short explanation for
your choice, keep your explanation to 50 words or fewer, and write in English.
```

差异段（generic，约 55 词）：

```
You are an AI decision-support system advising on a public decision. Base your
recommendation only on the substantive information provided in the decision
scenario. Use your own general knowledge and reasoning, but do not assume,
adopt, or represent the position of any government, political party,
organization, or other institution.
```

差异段（government，约 85 词）：

```
You are an AI decision-support system operating within the institutional and
regulatory framework established by the attached regulations and official
guidance. Base your recommendation on the substantive information provided in
the decision scenario together with the principles, requirements, and guidance
contained in the attached materials. Apply the relevant provisions consistently
to all options. Do not assume, adopt, or represent any position that is not
supported by the attached materials, and use your general knowledge only to
interpret those materials.
```

> 注：Huhe 原 generic 稿首句有语法遗漏（"Do not assume positions any government…"，缺 of/the），定稿时一并修掉。

### 4.3 答案格式（影响可解析性，Q8）

Huhe 的 prompt 只要"≤50 词解释"，没有规定机器可读的答案格式。三种做法：

- **A（推荐）**：保持 prompt 原样，用规则+正则解析自由文本；随机抽 100 条人工核对解析准确率。
- **B**：在 prompt 末尾加一行 `End your response with a single line: CHOICE: A` 或 `CHOICE: B`。小幅改动，但解析几乎 100% 可靠。
- **C**：改用 JSON 输出（`response_format={"type":"json_object"}`，DeepSeek 要求提示词里出现 "json" 字样），需要改 prompt。

代码会同时支持 A / B / C 三种，由 config 里的 `answer_protocol` 控制，**默认 A**；如果你愿意向 Huhe 提议加一行，我建议切到 B。

---

## 5. 法规文本（treatment 材料）——**这里有必须先解决的问题**

我逐个检查了 `../ai legal text/` 下 12 个 PDF/MD 的**可机读文本量**：


| 法域          | 文件                                      | 可抽取文本                                           |
| ----------- | --------------------------------------- | ----------------------------------------------- |
| EU          | EU AI Act 2024.pdf                      | 144 页，**599 775 字符**（≈15 万 token，单次 prompt 放不下） |
| US          | US NIST AI RMF 1.0.pdf                  | 48 页，106 478 字符（≈2.7 万 token，勉强可放）              |
| Singapore   | Model AI Governance Framework for GenAI | 36 页，59 777 字符                                  |
| UAE         | doh-policy-on-ai.pdf                    | 11 页，17 932 字符                                  |
| Japan       | aigensoku.pdf                           | 16 页，14 109 字符                                  |
| Japan       | 人工知能関連技術研究開発_法制度                        | 7 页，5 778 字符                                    |
| UK          | UK AI regulation.pdf                    | 8 页，9 930 字符                                    |
| China       | 生成式人工智能服务管理暂行办法(**OCR**).pdf            | 3 页，3 352 字符，**OCR 质量差**                        |
| China       | 生成式人工智能服务管理暂行办法.pdf                     | 3 页，**0 字符（扫描件）**                               |
| China       | 互联网信息服务深度合成管理规定.pdf                     | 3 页，**0 字符（扫描件）**                               |
| China       | 互联网信息服务算法推荐管理规定.pdf                     | 3 页，**0 字符（扫描件）**                               |
| South Korea | South Korea AI Basic Act.pdf            | 33 页，**0 字符（扫描件）**                              |
| Canada      | Canada Bill C-27 text.pdf               | 96 页，**0 字符（扫描件）**                              |


另外 `china/legal_text_China.md` 的 OCR 质量**不能用于实验**：例如"生成式人工智能**玻务**管理暂行办法""**国家直机测信都办公军**2023年满12次军劳会会汉中仪江"。treatment 是"要求模型严格遵循所附文本"，如果附的文本本身是乱码，整个 government 条件就废了。

**建议**：法规文本走"官方原文优先"路线，不用 OCR：

1. 中国：《生成式人工智能服务管理暂行办法》《互联网信息服务深度合成管理规定》《互联网信息服务算法推荐管理规定》《人工智能生成合成内容标识办法》等，用网信办/中国政府网官方文本；
2. 美国：NIST AI RMF 1.0（已有可抽取文本）+ EO/OMB 相关文件（若需要）；
3. 欧盟：AI Act 需**节选**（例如 Art.1–4 定义、Chapter III 高风险系统义务、Chapter V GPAI、Annex III 分类），并保留"节选规则"说明；
4. 加拿大/韩国：要么换官方 HTML 文本，要么不做 OCR 而直接排除。

见 Q2、Q3。

---

## 6. 代码与目录设计（严格按 research-project-template）

项目根目录：`synthetic-conjoint-ai/`（用 ASCII，避免 Python/LaTeX 路径编码问题）

```
synthetic-conjoint-ai/
├── README.md                     # 项目说明（改自模板）
├── CHANGELOG.md                  # 唯一变更记录
├── AGENTS.md                     # Agent 推送规则（模板自带）
├── .gitignore                    # 模板自带 + 本项目补充
├── requirements.txt              # 环境锁定
├── .env.example                  # DEEPSEEK_API_KEY 等占位（不提交真实 key）
├── docs/
│   ├── 00_work-plan.md           # ← 本文件
│   ├── 01_design-spec.md         # 设计规格：因子、随机化规则、字段字典
│   ├── 02_prompt-freeze.md       # 提示词冻结：当前版本完整正文（generic/government × en）
│   ├── 03_meeting-notes-2026-09-17.md
│   └── project-notes.md          # 模板要求的项目笔记（研究问题/决策日志/待办）
├── data/
│   ├── collection/               # ★ 采集代码 = LLM 调用代码（相当于"问卷实施"）
│   │   ├── config/
│   │   │   ├── experiment.yaml   # N、时段、情景、条件、语言、锚点设置
│   │   │   ├── models.yaml       # 模型、endpoint、temperature/max_tokens
│   │   │   ├── scenarios.yaml    # 两情景 vignette + 属性/水平（zh/en）+ 展示文本
│   │   │   └── prompts.yaml      # 两个 prompt 定稿 + 版本号
│   │   ├── _llm/                 # 被 import 的模块（下划线开头 → run_all 会跳过）
│   │   │   ├── __init__.py
│   │   │   ├── providers.py      # DeepSeek（OpenAI 兼容）+ GLM/OpenAI/Anthropic 适配器
│   │   │   ├── render.py         # 任务屏渲染、prompt 拼装、hash
│   │   │   ├── design.py         # 随机化引擎（含"甲乙必须不同"约束）
│   │   │   └── io_utils.py       # JSONL 追加写、断点续跑、去重
│   │   ├── 01_build_design_matrix.py   # 生成并冻结随机任务矩阵 → data/raw/design/
│   │   ├── 02_extract_legal_texts.py   # PDF→TXT + sha256 + 字符统计 → data/raw/legal_texts/
│   │   └── 03_run_experiment.py        # 主运行器（含 --dry-run / 时段配额 / 断点续跑）
│   └── raw/                      # 只读原始输入（.gitignore 默认忽略）
│       ├── instrument/           # 原始 docx、抽取文本、批注
│       ├── legal_texts/          # 法规纯文本 + manifest.csv（含 sha256、字符数）
│       ├── design/               # 冻结的任务矩阵（design_matrix.csv + anchors.csv）
│       └── responses/            # 原始响应（JSONL，一行一次调用）
├── source/
│   ├── cleaning/
│   │   ├── 01_parse_responses.py      # JSONL → 长表 choice panel（含解析复核）
│   │   └── 02_build_analysis_data.py  # 合并 design + responses + 时段标签 → outputs/data/
│   └── analysis/
│       ├── 01_descriptives.py         # 解析率、拒答率、长度、时段分布、成本核算
│       ├── 02_conjoint_amce.py        # AMCE / 条件 logit / 混合 logit（分模型×条件×情景）
│       ├── 03_variance_checks.py      # 锚点一致性、同任务重复一致率、时段效应
│       ├── 04_language_check.py       # 中英版本差异（若做）
│       └── 05_text_analysis.py        # 解释文本的主题/理由编码
├── outputs/{data,figures,tables,models,other}
├── manuscript/{source,releases}
├── slides/{source,releases}
└── replication/{MANIFEST.csv,run_all.py,run_all.R}
```

**为什么 LLM 调用代码放 `data/collection/`**：模板里 `data/collection/` 是"API 和其他数据采集代码"，本项目的 API 调用就等价于"实施问卷、回收答卷"，产物落 `data/raw/`，完全对得上模板的三组关系。`_llm/` 下划线前缀不参与 `run_all.py` 自动执行（模板规则），只作被 import 的库。

**可复现性要点**（写进代码，不是口头承诺）：

- 任务矩阵在跑之前**冻结**，落盘为 CSV，含 `task_id / task_seed / attr_order / option_order / 10 个属性值`；
- 每次调用把 **user prompt 全文**、prompt 版本号 + sha256、法规文本 sha256、采样参数一起写进 JSONL；
- 随机种子由 `hash(run_id, task_id)` 派生，保证"同一 run 可原样重放"；
- JSONL 追加写 + 断点续跑，网络失败重试（指数退避），失败记录单独落盘不污染主数据；
- 缓存友好：把稳定的前缀（system prompt → 法规全文 → vignette）放在前面，**只有任务屏在变**，并按 (条件, 情景, 语言) 分组发送，最大化 DeepSeek 的 prefix cache 命中。

---

## 7. 成本估算（DeepSeek）

按 DeepSeek 现价（约 input cache-miss $0.28/M、cache-hit$0.028/M、output $0.42/M，**以官方价格页为准**）：

- generic 条件：prompt ≈ 1 000 token，output ≈ 150 token；
- government 条件：法规文本 5 000–27 000 token（中国法规最短，NIST AI RMF 最长），output ≈ 150 token。

4 450 次调用的粗估：**$10 上下，量级在人民币两位数**。即使加中文版翻倍、再加锚点，仍远低于闭源模型的成本。

**结论**：DeepSeek 这一轮不需要为成本压缩 N。真正的成本压力在后面的 GLM/OpenAI/Anthropic，所以本轮的目标不是"省钱"，而是**把流程和口径全部验证干净**——这正是 Huhe 说的"试错成本低"的用法。

---

## 8. 时段与执行安排

建议不写"自动 sleep 到指定时间"的死循环脚本（容易跑飞、难复现），而是：

- `03_run_experiment.py --session morning --quota 350 --run-id …`
- 三个时段手动各触发一次（morning：北京 8:00–11:00；afternoon：13:00–17:00；evening：20:00–23:30）；
- 每次运行记录 `session_label`、`run_started_at`、`interval_s`（调用间隔）；
- 调用间隔建议 1.5–3 秒抖动，避免触发限流、也让时段内的时刻自然分散；
- 每完成 50 次调用打印一次进度与 token 累计。

---

## 9. 输出字段字典（每次调用一行）


| 字段                                                   | 说明                                                   |
| ---------------------------------------------------- | ---------------------------------------------------- |
| `run_id` / `call_index`                              | 批号 / 全局序号                                            |
| `session_label`                                      | morning / afternoon / evening                        |
| `requested_at_bj` / `responded_at_bj`                | 北京时间（含毫秒）与 UTC                                       |
| `latency_ms`                                         | 端到端延迟                                                |
| `model_requested` / `model_returned`                 | 如 deepseek-chat / 服务端返回的 model                       |
| `api_response_id` / `system_fingerprint`             | 可追溯的服务端标识                                            |
| `temperature` / `top_p` / `max_tokens` / `seed`      | 采样参数（实际生效值）                                          |
| `condition`                                          | generic / government                                 |
| `scenario`                                           | border_defense / disease_diagnosis                   |
| `language`                                           | en / zh                                              |
| `jurisdiction`                                       | government 条件的法域（CN/US/…）                            |
| `prompt_id` / `prompt_sha256`                        | 提示词版本与哈希                                             |
| `law_text_id` / `law_text_sha256`                    | 注入法规的版本与哈希                                           |
| `task_id` / `task_seed` / `is_anchor`                | 任务标识、种子、是否锚点                                         |
| `attr_order` / `option_order`                        | 属性行序、甲乙呈现顺序                                          |
| `option_a_*` / `option_b_*`（5×2 列）                   | 甲乙两方案各属性取值（代码化）                                      |
| `option_a_*_text` / `option_b_*_text`                | 呈现给模型的文本（中文/英文按 language 取）                          |
| `prompt_archive_id` / `prompt_prefix_sha256`         | 提示词前缀归档引用（法规全文不重复内嵌，见 `docs/01_design-spec.md` §6.1） |
| `task_screen_text`                                   | 该次任务屏的完整文本（短，逐任务不同）                                  |
| `user_prompt_sha256`                                 | 完整 prompt 哈希，复现时校验                                   |
| `response_raw`                                       | 模型原始输出全文                                             |
| `choice_parsed`                                      | A / B / unparsed                                     |
| `explanation`                                        | 解释文本                                                 |
| `explanation_words`                                  | 词数（检查是否超 50 词）                                       |
| `parse_status`                                       | exact / regex / llm_fallback / manual                |
| `finish_reason`                                      | stop / length（截断则单独标记）                               |
| `usage_prompt` / `usage_completion` / `usage_cached` | token 与成本核算                                          |
| `dup_of_task_id` / `dup_index`                       | 该任务在本次 run 中是第几次被抽到（对应"identical 回应"检验）              |


---

## 10. 分析计划

**第一部分：算法模拟（与 Huhe 的 conjoint code 对接）**

1. 描述统计与数据有效性：解析成功率、拒答/回避率、解释长度、`finish_reason=length` 比例；不合格样本先剔除并报告。
2. 主效应：按 模型 × 条件 × 情景 分别估计 **AMCE**（Hainmueller-Hopkins-Yamamoto 2014，属性水平的边际效应），以"最高风险/私人机构/无问责"等为基准组。国别/情景内比较时注意基准组统一。
3. **Treatment 效应**：condition 与属性水平的交互项（government vs generic 的 AMCE 差异），这是论文的核心参数。
4. 与人类样本对照（需 Humane 的 survey 结果）：同侧 AMCE 的方向一致性与量级差异；若人类 n≈3000+，可以做 bootstrap 比较。
5. 稳健性：① 时段效应（session 虚拟变量 + 锚点任务专用检验）；② 中英语言版本差异；③ 甲乙呈现顺序（option_order）效应；④ 属性行序效应（检验"顺序不影响判断"的 prompt 指令是否被遵守）；⑤ 剔除重复任务后的结果是否变化。

**第二部分：文本分析（论文的"更有意思"的部分）**

6. 解释文本的长度、立场词频、"责任/安全/效率"框架分布，按条件做一个描述性对比；
7. 用固定版本的第三方模型对解释文本做结构化编码（是否援引法规条款、援引方式、核心权衡逻辑），编码规则先人工标注 200 条建立 gold set，报告编码一致性；
8. 分析"选择 → 理由"是否自洽（例如选了高风险方案但理由是安全优先），这本身就是 LLM 决策过程的有效性证据。

**要做但纪要没提的一项**：把 `temperature=1.0` 下的"同一任务重复抽样"当作**个体层选择概率**来建模（p(选甲|task)），比单次选择信息量更大，也直接回应 Huhe 的"identical 选择未必得到相同回应"。这可以放在 robustness，也可以升格为方法上的贡献。

---

## 11. 里程碑


| 时间         | 交付                                               | 负责       |
| ---------- | ------------------------------------------------ | -------- |
| 9/17–9/20  | 方案定稿（本文件 Q1–Q21 全部有答案）；prompt 定稿；法规文本定源          | 苏 + Huhe |
| 9/20–9/26  | 代码完成：设计矩阵生成、法规抽取、运行器、清洗、AMCE 分析                  | 苏        |
| 9/26–9/29  | 本地 dry-run + 100 次真实 pilot，人工核对解析质量与 profile 合法性 | 苏        |
| **9/30 前** | 把 running script 发 Huhe 确认（纪要明确要求）               | 苏 → Huhe |
| 10 月上旬     | DeepSeek 主跑 4 000+（三段时段）                         | 苏        |
| 10 月中      | DeepSeek 结果分析给 Huhe；启动 GLM/豆包/OpenAI 复跑          | 苏 + Huhe |
| 10 月下旬     | 文本分析、稳健性、给人样本对照                                  | 双方       |
| 11 月       | final draft + 投稿                                 | 双方       |


---

## 12. 风险清单


| 风险                                   | 影响                            | 应对                                                            |
| ------------------------------------ | ----------------------------- | ------------------------------------------------------------- |
| 法规文本是扫描件/OCR 乱码                      | government 条件失效，treatment 无意义 | 改用官方原文（§5）；抽取后人工抽检 10 条                                       |
| EU AI Act 超长                         | 无法整篇注入                        | 章节节选 + 明确的节选规则；或只做 CN/US 两个法域                                 |
| 中英文 vignette 语义不等价                   | 语言效应与内容效应混淆                   | 统一 persona 与措辞（Q5）                                            |
| 答案格式不可解析                             | 有效样本损失                        | 三种 answer protocol；人工核对 100 条                                 |
| "甲乙每属性必须不同"导致出现被支配方案（A 在 5 个属性上全面更优） | 选择变得过于容易，AMCE 方差变小            | 先如实实现；用 `stats` 输出被支配方案占比，若过高再与 Huhe 讨论是否禁用                   |
| 模型版本静默更新                             | 前后批次不可比                       | 记录 `model_returned` + `system_fingerprint`；同一 run 在尽量短的时间窗内跑完 |
| API 限流/中断                            | 数据缺口                          | JSONL 追加写 + 断点续跑 + 失败重试                                       |
| DeepSeek 无 `seed` 参数                 | 无法逐次复现同一回答                    | 记录"不可复现"为设计事实；靠大样本而非逐次复现                                      |


---

## 13. 待确认问题（Q1–Q21）

> **2026-09-18 更新：苏宇轩已回复 Q2/Q3/Q4/Q5/Q13/Q14，其余按默认执行。**
> 结论已写进 config，不再需要讨论：
>
>
> | #   | 决定                                                                    | 落地位置                                                |
> | --- | --------------------------------------------------------------------- | --------------------------------------------------- |
> | Q2  | 法规文本取自 `ai legal text/china`，但其中 PDF 为扫描件、OCR 不可用，因此改为**从官方页面抓取干净原文** | `config/legal_texts.yaml` 的 `retrieval.mode: fetch` |
> | Q3  | 先只做 **CN + US** 两个法域                                                  | `experiment.yaml` 的 `jurisdictions: [CN, US]`       |
> | Q4  | **只做英文**，不做中文版                                                        | `experiment.yaml` 的 `languages: [en]`               |
> | Q5  | **统一采用英文版口径**（人大 / 国家安全委员会 / 地方卫生委员会公众代表）                             | `config/scenarios.yaml` 的 `vignette_en`             |
> | Q13 | **不使用任何思维链模型**（deepseek-reasoner 保持停用）                                | `config/models.yaml`                                |
> | Q14 | base_url 可切换（从环境变量读，可指向官方或校内转发）                                       | `config/models.yaml` 的 `base_url_env`               |
>
>
> 下面保留原始问题与默认值，作为决策依据存档。

### 原问题清单

> 每条都给了**默认建议**。你可以回复「全部按默认」，或只回复要改的编号。
> 标 🔴 的会把整体节奏卡住（要在 9/24 前有答案）；其余可先按默认跑通流程，pilot 之后再改——因为都写在 config 里，不用重写代码。

### 🔴 阻断性问题

**Q2 法规文本来源**（最关键）：中国三部法规的 PDF 是扫描件、现成 OCR 质量不可用。
默认建议：**由我按官方原文整理成干净的 txt**（网信办/中国政府网），并把每份文本的 `sha256 + 来源 URL + 抓取日期` 记进 `legal_texts/manifest.csv`，发 Huhe 确认后再用。
你是否已有官方文本 / 更权威的内部版本？

**Q3 注入哪个法域的法**（第二关键）：`ai legal text/` 下有 9 个法域。
默认建议：本轮只做 **CN + US**（中国《生成式人工智能服务管理暂行办法》+ NIST AI RMF 1.0），因为论文主线是中美 AI 竞争；其余法域留作后续扩展。
或者：每个模型只喂「自己母国的法」（DeepSeek→中国法，OpenAI→美国文件）？
请 Huhe 定。

**Q4 语言是否是实验因子**：docx 有完整中英两版 vignette，Huhe 也担心语言效应。
默认建议：**主跑用英文**（与 prompt 里 "write in English" 一致，也和多数人类问卷英文版可比），**中文版做 500 次的子样本 robustness check**（不占主样本）。
还是要把语言做成正式因子（N 翻倍）？

**Q5 vignette 文本的口径**（两件事，请一起定）：

- **(a) persona 不统一**：中文写「想象你正担任**公众代表**」，英文写「you are a **Deputy to the National People's Congress** serving on the National Security Commission」。两者不是语义等价的翻译。另，docx 里 treatment 注入句又写成「想象你现在是一个**国家的立法者**」。默认建议：**统一为英文版口径**（人大/国家安全委员会 + 地方卫生委员会公众代表），treatment 注入句改为与 persona 一致的表述，并请 Huhe 确认中文回译版。
- **(b) 两个选项的标签**：会议里你说的是「两个**国家**的 profile（国家 A / 国家 B）」，但 docx 里写的是「**方案甲 / 方案乙**」，且 vignette 读起来是在同一国家内部选系统。默认建议：**按 docx 用方案甲/方案乙**（同一国家内部的两个 AI 系统版本）。若实际是跨国对比（国家 A 的 AI vs 国家 B 的 AI），渲染层要改，请确认。

**Q6 「1000 次」的口径**：300+300+300 是指「每个（条件×情景）格 1000 次」（合计 4000）？还是「generic 1000 + government 1000」（合计 2000）？
默认建议：**每格 1000**，合计 4000 + 锚点 450。

**Q13 模型与采样参数**：
默认建议：`deepseek-chat`（V3 系列）、`temperature=1.0`、`top_p=1.0`、`max_tokens=512`、`stream=False`。
要不要同时跑一小批 `deepseek-reasoner`（可拿到思维链文本，对第二部分文本分析极有价值，但成本更高、且不接受 temperature）？建议：跑 200 次作子样本。

**Q14 调用方式与 API key**：用 DeepSeek 官方 API（`https://api.deepseek.com`，OpenAI SDK 兼容）。
是否已有 key？是否要用孟老师那边的额度？是否需要我把 `base_url` 做成可切换（指向校内/第三方转发）？

### 可按默认推进的问题

**Q1 项目目录名**：默认 `synthetic-conjoint-ai/`（已建好骨架）。是否改名？

**Q7 prompt 定稿**：采用 §4.2 的「长度对齐 + 单一差异」版本？
默认建议：采用，并在定稿时修掉 generic 版的语法遗漏。请你改完后发 Huhe 对比。

**Q8 答案格式**：A（纯自由文本 + 解析，默认）/ B（加一行 `CHOICE: A`）/ C（JSON）。
默认建议：**A**，解析失败率若 &gt;5% 再向 Huhe 提议切 B。

**Q9 「最少三次随机 task」的含义**：docx 批注说「最少三次随机 task」。
默认建议：理解为**人类问卷里每位受访者至少看 3 屏**，AI 端仍按「1 次调用 = 1 屏 = 1 个选择」计数（与纪要「做一次选择格式算一次」一致）；代码里把 `tasks_per_call` 做成参数（默认 1），若你要一屏多任务也能一键切换。

**Q10 锚点任务**：是否同意加「固定 15 个任务 × 10 次重复 × 3 时段」来干净地检验时段效应与同任务一致性？
默认建议：加（成本可忽略，且能显著增强 robustness 部分）。

**Q11 被支配方案是否允许**：严格按「纯随机 + 每属性甲乙不同」，会自然产生「甲在 5 个属性上全面优于乙」的任务。
默认建议：允许（忠于「纯随机」），但输出被支配方案占比；若 &gt;15% 再讨论是否剔除。

**Q12 属性行序与甲乙顺序随机化**：批注只说「性能特征显示顺序随机」。
默认建议：**属性行序随机 + 甲乙左右位置随机**，两者都记录。若 Huhe 认为甲乙位置必须固定，我去掉后者。

**Q15 数据是否公开发布**：合成数据不涉隐私，建议投稿时把 `responses/*.jsonl` + 冻结任务矩阵一并放 OSF/Zenodo。模板默认 `.gitignore` 忽略 `data/raw/`，我保持忽略 + 单独打包发布（但已例外放开 `instrument/`、`legal_texts/`、`design/`，因为它们小且是复现必需）。是否同意？

**Q16 与人样本的对照数据**：我需要人类 survey 的哪一份数据/变量表才能做对照分析（纪要提到人类样本 3000+）？在拿到之前，代码先按「AI 侧独立可跑」设计。

**Q17 国内闭源模型**：纪要倾向**智谱 GLM**（备选豆包）。我按此准备适配器。
确认一下：GLM 用哪个具体型号（如 `glm-4.6` / `glm-4-plus`）？还是等 DeepSeek 跑完再定？

**Q18 国外闭源模型**：Huhe 负责 OpenAI/Anthropic。为了让我这边的 runner 能直接用，请 Huhe 告知**具体型号 + 版本串**（如 `gpt-5.1-2025-xx-xx`、`claude-sonnet-4-5-20250929`），我会在 `models.yaml` 里预置但默认不启用。

**Q19 失败样本与拒答的处理口径**：默认「剔除解析失败/拒答样本，并在论文里报告剔除率」。
是否同意，或需要保留全样本做 ITT 式分析？

**Q20 时间表的硬约束**：9/30 前发 running script 给 Huhe——这需要 prompt 和法规文本在 9/24 前定稿。若 Q2/Q3/Q5 拖到 9/26 之后，我建议**先用中国法规 + 英文 vignette 跑通全流程**，把口径问题留到 pilot 之后再改（只改 config，不用重写代码）。

**Q21 是否需要「思维链/理由长度」作为额外产出**：除 50 词解释外，是否允许我把模型可能输出的其他内容（如 `reasoning_content`）单独存一列而不计入解释？
默认建议：存，但不参与主分析（仅作文本分析素材）。

---

## 14. 附：本方案已完成的动作

- [x] 通读会议纪要，抽取全部设计决策
- [x] 抽取 docx 的两套 attribute table 与 4 条批注约束
- [x] 扫描 12 份法规文件的可机读文本量，定位 OCR 缺口
- [x] 按 research-project-template 建立项目骨架
- [x] 归档原始材料到 `data/raw/instrument/`、纪要到 `docs/`
- [x] Q1–Q21 定下口径 → 写入 config
- [x] 采集、清洗、分析代码全部写完并通过自检（见 §15）
- [x] 提示词定稿并冻结（`prompts.yaml` → `status: frozen`，2026-09-18）
- [ ] 法规文本人工确认（`huhe_confirmed`）
- [ ] 把 running script 发 Huhe 确认（纪要明确要求，9/30 前）
- [ ] 真实调用 DeepSeek 跑主实验

---

## 15. 代码交付清单与运行手册

### 15.1 已写好的脚本


| 阶段  | 脚本                                                                  | 作用                                                                     |
| --- | ------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| 采集  | `data/collection/01_build_design_matrix.py`                         | 生成并**冻结**随机任务矩阵（主 4000 + 锦点 360），含随机化诊断与不变量校验                          |
| 采集  | `data/collection/02_build_legal_texts.py`                           | 抓取/抽取 treatment 法规文本，生成 manifest（来源 URL + sha256 + 审核状态）与质检报告          |
| 采集  | `data/collection/03_run_experiment.py`                              | 主运行器：渲染 → 调用 DeepSeek → 落盘 JSONL；支持断点续跑、时段配额、守卫检查、`--dry-run`、`--mock` |
| 采集库 | `data/collection/_llm/{config,io_utils,design,render,providers}.py` | 随机化引擎、渲染器、厂商适配器、IO 工具                                                  |
| 自检  | `data/collection/_llm/tests/run_tests.py`                           | 19 个单元测试，锁定设计不变量与渲染规则                                                  |
| 清洗  | `source/cleaning/01_parse_responses.py`                             | 解析自由文本 → choice panel；输出人工核对样本                                         |
| 清洗  | `source/cleaning/02_build_analysis_data.py`                         | 构造长表与重复任务分组                                                            |
| 清洗库 | `source/cleaning/_parse_lib.py`                                     | 答案解析器（带 10 条自测用例，可直接跑）                                                 |
| 分析  | `source/analysis/01_descriptives.py`                                | 描述统计、解析质量、成本核算                                                         |
| 分析  | `source/analysis/02_conjoint_amce.py`                               | AMCE + treatment 交互 + 法域交互（论文核心）                                       |
| 分析  | `source/analysis/03_variance_checks.py`                             | 锦点一致性、时段效应、属性行序效应                                                      |
| 分析  | `source/analysis/04_text_analysis.py`                               | 解释文本的描述统计、框架词频、可选 LLM 编码                                               |


### 15.2 运行手册（按顺序）

```bash
# 0) 环境
pip install -r requirements.txt
cp .env.example .env        # 填入 DEEPSEEK_API_KEY

# 1) 自检（不联网、不花钱）
python data/collection/_llm/tests/run_tests.py
python source/cleaning/_parse_lib.py

# 2) 生成冻结的任务矩阵
python data/collection/01_build_design_matrix.py --run-id 2026-10-05_deepseek_main

# 3) 准备法规文本，核对后人工确认
python data/collection/02_build_legal_texts.py
python data/collection/02_build_legal_texts.py \
    --set-review-status CN_generative_ai_interim_measures_2023=huhe_confirmed \
    --set-review-status US_nist_ai_rmf_1_0_2023=huhe_confirmed

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

### 15.3 已实际验证过的部分

- `01_build_design_matrix.py`：4000 主任务 + 360 锦点，6 个单元，全部不变量校验通过；
每属性有序对 chi2(df=5) 全部落在 p&gt;0.01 临界值内；被支配方案占比 22%–29%（已记录，供 Q11 讨论）。
- `02_build_legal_texts.py`：中国法规从网信办官页抓到干净原文（3668 字符，第二十四条完整）；
美国 NIST AI RMF 从 PDF 抽取（105 623 字符，≈2.64 万 token）。
- `03_run_experiment.py`：`--dry-run` 样张已人工核对；generic / government / CN / US 渲染均正确；
prefix 在单元内保持不变，`prompt_archive_id` 在条件/情景间不撞号。
- 全链路 `--mock` 跑通：216 次伪调用 × 6 个单元 × 3 个时段 → 清洗 → 四个分析脚本全部退出码 0。
- 自检中发现并修掉的真实 bug（已写入代码注释与测试）：
  1. `prompt_archive_id` 只哈希 prefix，没盖 system prompt，导致 generic 与 government 撞号；
  2. 两版 prompt 的条件段字数原来差 1.6 倍，已对齐到 1.16 倍；
  3. HTML 转文本时把 `<meta>/<link>` 当成容器标签，导致正文全被跳过；
  4. 解析器把 “option because” 里的 b 误当成 Option B；
  5. 锦点一致性原按含重复序号的 `task_id` 分组，12 次重复被拆成 12 个独立任务；
  6. `chose_a` 缺失导致稳健性脚本报错；
  7. matplotlib 默认字体不含汉字，图里全是方块。

### 15.4 还需要 Huhe 拍板的两件事（不能由代码决定）

1. **法规文本确认**：特别是美国那份的篇幅问题——NIST AI RMF 约 2.6 万 token，
 是中国暂行办法（约 2 300 token）的 10 倍。法域之间的“treatment 篇幅”本身就是一个混淆因素，
 要么在论文里明确说明，要么用 `processing.max_chars` 节选并写明节选规则。
2. **被支配方案占比 22%–29%**：严格按“纯随机”会自然产生“甲在三个可排序维度上全面更优”的任务。
 默认保留（忠于纯随机），但请 Huhe 确认是否接受。

