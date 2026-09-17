# Project Notes

## 研究问题

1. LLM 在联合实验（conjoint）任务上的选择偏好，是否以及在多大程度上能代表人类受访者的偏好？
2. 当把**官方 AI 法规文本**作为 treatment 注入时，模型（"government AI"）的偏好相对于"generic AI"发生什么变化？这是否可以被理解为制度环境对 AI 决策的塑造？

## 理论机制与假设

待与 Huhe/孟老师确认后填写。初步方向：

- H1：generic AI 与人类样本在属性边际效应（AMCE）的方向上大体一致，但在风险-效率权衡上更偏向某一端。
- H2：government 条件（注入法规）会显著改变"责任归属"与"安全"类属性的权重，且改变幅度与法规文本的具体内容相关。
- H3：同一任务重复调用不产生完全相同的回答，模型选择应被建模为概率分布而非确定性函数。
- H4：不同模型（开源/闭源 × 中/美）的 treatment 反应强度不同。

## 数据与样本

- **分析单位**：一次 API 调用 = 一位"硅基受访者"回答一屏 conjoint 任务 = 一个二选一观测。
- **样本量**：每个（模型 × 条件 × 情景）约 1 000 次，分 morning/afternoon/evening 三个时段。
- **对照数据**：人类 survey experiment，n ≈ 3 000+（待获取变量表）。
- **原始材料**：`data/raw/instrument/`（联合实验问卷 docx 及其抽取文本、批注）。
- **treatment 材料**：`data/raw/legal_texts/`（各法域 AI 法规纯文本 + `manifest.csv`）。

## 变量操作化

- **因变量**：`choice_parsed ∈ {A, B}`（强制二选一，无回避选项）。
- **自变量（属性）**：每情景 5 个属性 × 3 个水平，见 `docs/01_design-spec.md` §2 与 `docs/00_work-plan.md` §2。
- **处理变量**：`condition ∈ {generic, government}`；government 条件下追加记录 `jurisdiction` 与 `law_text_sha256`。
- **协变量/检验变量**：`session_label`、`attr_order`、`option_order`、`language`、`explanation_words`、`latency_ms`。
- **稳健性专用**：`is_anchor`、`dup_of_task_id`、`dup_index`。

## 分析计划

### 第一部分：算法模拟

1. 描述统计与数据有效性检查（解析成功率、解释长度、截断比例）。
2. 按 模型 × 条件 × 情景 估计 AMCE（Hainmueller, Hopkins & Yamamoto 2014）。
3. condition × attribute 交互项 = treatment 效应（核心参数）。
4. 与人类样本的 AMCE 对照（方向一致性 + 量级差异 + bootstrap）。
5. 稳健性：时段效应（以锚点任务为主）、中英语言版本、呈现顺序、属性行序、重复任务剔除。

### 第二部分：文本分析

6. 解释文本的描述性对比（长度、责任/安全/效率框架分布）。
7. 用固定版本第三方模型对解释文本做结构化编码（是否援引法规、援引方式、权衡逻辑）；
   先人工标注 200 条建立 gold set，报告编码一致性。
8. 检验"选择 → 理由"的自洽性。

### 方法与模型

- AMCE：线性概率模型 / `cregg` 或 `pyfixest` 实现（与 Huhe 的 R code 口径对齐）。
- 异质性：混合 logit 或带随机系数的条件 logit。
- 个体层选择概率：对锚点任务用重复抽样估计 p(choose A | task)。

## 重要研究决策

按日期记录分析选择及原因。会影响数据、结果或正式交付的变化，还应同步写入根目录 `CHANGELOG.md`。

- **2026-09-17**：确认不做正交/高效设计，采用纯随机任务生成（纪要：完全模拟人类联合实验的随机过程）。
- **2026-09-17**：确认每次调用 memory-free（context-free），不复用对话历史。
- **2026-09-17**：确认输出中必须记录模型执行任务的时间变量（用于时段 precaution）。
- **2026-09-17**（自 docx 批注）：每属性上甲、乙两方案的取值必须不同；属性行序随机；最少三次随机 task。
- **2026-09-17**：项目骨架按 research-project-template 建立；LLM 调用代码归入 `data/collection/`。

## 会议与讨论记录

- 2026-09-17 技术对齐会（苏宇轩 & Huhe）：`docs/03_meeting-notes-2026-09-17.md`。
- 待补：与孟老师的设计确认会；与 Huhe 的 prompt 定稿讨论。

## 待办事项

- [ ] 苏宇轩：确认 `docs/00_work-plan.md` 的 Q1–Q20。
- [ ] 苏宇轩：改写并对齐两段 prompt，发 Huhe 对比。
- [ ] 苏宇轩：确定国内闭源模型（倾向智谱 GLM）并发 Huhe 确认。
- [ ] 苏宇轩：整理干净的官方法规文本（中国三部法规 PDF 为扫描件）。
- [ ] 苏宇轩：编写实验代码，**10 月 1 日前**发 Huhe；run 前先发 running script 供确认。
- [ ] 苏宇轩：先在 DeepSeek 上 run 1000 次（generic + government），分早/中/晚时段。
- [ ] Huhe：发送两段 prompt draft；负责国外闭源模型；整理 conjoint 分析 code；起草文章可写部分。
- [ ] 双方：结果就绪后推进 final draft 与投稿（目标 11 月）。
