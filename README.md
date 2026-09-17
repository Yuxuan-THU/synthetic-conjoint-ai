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

本仓库遵循 [research-project-template](https://github.com/Yuxuan-THU/research-project-template) 的生命周期结构：

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
- `.env`、`data/raw/`、`outputs/data/`、`outputs/models/`、`outputs/other/` 默认不进入 Git。
- 投稿阶段建议将 `responses/*.jsonl` 与冻结任务矩阵打包发布到 OSF/Zenodo，并在 `replication/MANIFEST.csv` 中登记。

## 关键文档

| 文件 | 内容 |
|---|---|
| `docs/00_work-plan.md` | 完整工作方案 + 待确认问题 Q1–Q21 |
| `docs/01_design-spec.md` | 随机化算法、渲染规则、字段规格（代码实现依据） |
| `docs/02_prompt-freeze.md` | 提示词版本冻结记录 |
| `docs/03_meeting-notes-2026-09-17.md` | 2026-09-17 技术对齐会纪要（含逐字稿） |
| `docs/project-notes.md` | 研究问题、操作化、分析计划、决策日志 |
