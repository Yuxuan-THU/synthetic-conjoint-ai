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
- **treatment 材料**：`data/raw/legal_texts/`（CN/US 两份 AI 法规纯文本；来源登记在 `config/legal_texts.yaml`）。

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
- **2026-09-18**：Huhe 确认两份 treatment 法规文本（CN 暂行办法、US NIST AI RMF）；本轮采用全文口径（不节选），法域篇幅差异（≈2 300 vs ≈26 400 token）在论文中说明。同日移除采集脚本的法规确认门禁，提示词 `frozen` 守卫保留。
- **2026-09-18**：提示词按讨论定稿为 v2（`generic_v2` / `government_v2`）；v1 停用（未用于任何数据采集）。
- **2026-09-18**：精简法规材料：`legal_texts/` 只保留两份 txt（统一命名 `{法域}_{简称}_{年份}.txt`），移除 manifest / 质检报告 / 人工校订目录；02 脚本简化为仅构建 txt，03 运行时现算 sha256。
- **2026-09-18**：v2 复核后确认保留三项有意设计：generic 版 `Do not assume positions any government…` 按原文保留不改；两版条件段不再做长度对齐（39 vs 141 词）；trade-off 提示仅出现在 government 版（两版不对称可接受）。

## 会议与讨论记录

- 2026-09-17 技术对齐会（苏宇轩 & Huhe）：`docs/03_meeting-notes-2026-09-17.md`。
- 待补：与孟老师的设计确认会；与 Huhe 的 prompt 定稿讨论。

## 待办事项

- [x] 苏宇轩：确认 `docs/00_work-plan.md` 的 Q1–Q21（2026-09-18 确认 Q2/Q3/Q4/Q5/Q13/Q14，其余按默认）。
- [x] 苏宇轩：提示词定稿（v2，2026-09-18 讨论定稿；完整正文见 `docs/02_prompt-freeze.md`）。
- [x] 苏宇轩：编写实验代码（采集 / 清洗 / 分析 + 19 个单元测试 + 解析器自测 + 全链路 mock 验证）。
- [x] 苏宇轩：整理干净的官方法规文本（中国三部法规 PDF 为扫描件，已改为从网信办官方页面抓取）。
- [x] 苏宇轩：提示词定稿并冻结（`prompts.yaml` → `status: frozen`，2026-09-18）；完整正文见 `docs/02_prompt-freeze.md`。
- [x] 苏宇轩/Huhe：人工确认法规文本（`huhe_confirmed`，2026-09-18）；采集端门禁已移除。
- [ ] 苏宇轩：确定国内闭源模型（倾向智谱 GLM）并确认具体型号串。
- [ ] 苏宇轩：把 running script 发 Huhe 确认（**10 月 1 日前**）。
- [ ] 苏宇轩：先在 DeepSeek 上 run 1000 次（generic + government），分早/中/晚时段。
- [ ] Huhe：负责国外闭源模型（待提供型号与版本串）；整理 conjoint 分析 code；起草文章可写部分。
- [ ] 双方：结果就绪后推进 final draft 与投稿（目标 11 月）。

## 未决的方法学问题（需 Huhe 拍板）

1. **被支配方案占比 22%–29%**：严格纯随机会产生“甲在三个可排序维度上全面更优”的任务。
   默认保留（忠于纯随机），需 Huhe 确认是否接受。
2. **锦点重复次数**：当前 5 个锚点任务 × 12 次重复 × 每单元，是否足够做时段效应与同任务一致性检验。
