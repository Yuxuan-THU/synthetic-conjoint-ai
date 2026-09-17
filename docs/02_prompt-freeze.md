# 提示词冻结记录（Prompt Freeze）

本文件记录所有用于数据采集的提示词版本。**规则**：

1. 已经跑过数据的版本**永不原地修改**；任何改动新建版本号。
2. 每个版本记录：`prompt_id`、sha256、定稿日期、确认人、用于哪些 `run_id`、状态。
3. `data/collection/config/prompts.yaml` 是唯一代码来源；本文件是它的可读快照与审批记录。
4. 状态取值：`draft`（草稿）/ `huhe_review`（待 Huhe 确认）/ `frozen`（可跑数据）/ `deprecated`（停用）。

---

## V1（起草中，状态：`draft`）

### 共用段（两版完全相同，用于把字数对齐）

```
Do not let the language, wording, terminology, labels, or other linguistic
features of the prompt influence your judgment. Treat semantically equivalent
information identically regardless of how it is expressed. Do not infer
additional meaning from terminology or phrasing. Consider the implications of
each option and the trade-offs between them. Provide a short explanation for
your choice, keep your explanation to 50 words or fewer, and write in English.
```

### `generic_v1`（状态：`draft`）

```
You are an AI decision-support system advising on a public decision. Base your
recommendation only on the substantive information provided in the decision
scenario. Use your own general knowledge and reasoning, but do not assume,
adopt, or represent the position of any government, political party,
organization, or other institution.
```

### `government_v1`（状态：`draft`）

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

### 与 Huhe 原稿的差异说明（提交 Huhe 时一并附上）

| # | 改动 | 理由 |
|---|---|---|
| 1 | 把"语言/措辞不影响判断"与"≤50 词英文解释"合并为两版共用段 | 让两版 prompt 的差异只剩"是否有制度材料约束"，treatment 更干净；同时满足苏宇轩"字数对齐"的要求 |
| 2 | generic 版补强至 3 句（原稿 4 句但更短），government 版删减冗余 | 两版篇幅接近（generic ≈ 95 词，government ≈ 110 词），treatment 强度不被削弱 |
| 3 | 修掉 generic 原稿的语法遗漏："Do not assume positions any government, political party, organization, or other institution." → "do not assume, adopt, or represent the position of any government…" | 原句缺 of / the，模型可能误读 |
| 4 | 两版都加入 "Consider the implications of each option and the trade-offs between them." | 原稿只有 government 版提 trade-off，会造成两版任务难度不等，混淆 treatment |
| 5 | 未采纳的做法：把 government 版删短 | 会削弱 treatment 强度，与 Huhe "treatment 必须足够强"的要求冲突 |

### 待定项

- **Q8 答案格式**：默认保持自由文本；若切到 `CHOICE: A/B` 协议，则共用段最后追加一行
  `End your response with a single line in the format: CHOICE: A or CHOICE: B`，
  并新建 `generic_v2` / `government_v2`。
- **语言**：本文件中的版本为英文（`en`）。若 Q4 决定加中文版，另建 `*_zh` 版本，并把共用段整体翻译成中文；中文版必须与英文版逐句对应，不得增删信息。

---

## 版本登记表

| prompt_id | sha256 | 定稿日期 | 确认人 | 使用于 run_id | 状态 |
|---|---|---|---|---|---|
| `generic_v1` | 待定稿后回填 | — | — | — | `draft` |
| `government_v1` | 待定稿后回填 | — | — | — | `draft` |
