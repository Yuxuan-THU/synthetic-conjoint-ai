# CHANGELOG

本文件记录整个研究项目中具有研究意义、可能影响结果解释或正式交付的变化。

## Unreleased

### 项目

- 按 [research-project-template](https://github.com/Yuxuan-THU/research-project-template) 建立项目骨架（`docs/ data/ source/ outputs/ manuscript/ slides/ replication/`）。
- 确定本项目的结构映射：LLM 调用代码归入 `data/collection/`（等价于"实施问卷"），原始响应落 `data/raw/responses/`，清洗与分析分别归入 `source/cleaning/` 与 `source/analysis/`。
- 新增 `requirements.txt`、`.env.example`，后者仅含占位符，真实密钥不进入版本控制。

### 文档

- 新增 `docs/00_work-plan.md`：完整工作方案，含实验因子结构、样本量、提示词方案、法规文本问题清单、成本估算、执行安排、字段字典、分析计划、里程碑、风险清单，以及待确认问题 Q1–Q21。
- 新增 `docs/01_design-spec.md`：任务随机化算法、渲染顺序、提示词版本控制、法规文本 manifest 规格、原始响应落盘规格、分析数据规格。
- 新增 `docs/02_prompt-freeze.md`：`generic_v1` / `government_v1` 两版提示词草稿、与 Huhe 原稿的 5 处差异说明及理由、版本登记表。
- 建立 `docs/project-notes.md`：研究问题、四条初步假设、变量操作化、分析计划与决策日志。
- 归档 2026-09-17 技术对齐会纪要至 `docs/03_meeting-notes-2026-09-17.md`。

### 数据

- 归档原始研究工具（联合实验问卷 docx、其可机读文本抽取结果、Word 批注抽取结果）至 `data/raw/instrument/`。
- 核查 `ai legal text/` 下 12 份材料的可机读文本量，确认 5 份为无文本层扫描件（加拿大 C-27、韩国 AI 基本法、中国三部法规的非 OCR 版本），现成中国法规 OCR 文本存在大量错字，不可用于 treatment。处理方案见 `docs/00_work-plan.md` §5。
- 从 docx 批注中抽取三条此前未进入会议纪要的硬约束：属性行序随机；同一属性上甲、乙取值必须不同；最少三次随机 task。

### 待完成

- 提示词定稿（`draft` → `huhe_review` → `frozen`）。
- 法规文本整理与 Huhe 确认（`review_status: huhe_confirmed`）。
- 采集、清洗、分析代码（等 Q1–Q21 确认后开始）。
