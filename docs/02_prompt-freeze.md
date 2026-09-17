# 提示词冻结记录（Prompt Freeze）

本文件记录所有用于数据采集的提示词版本。**规则**：

1. 已经跑过数据的版本**永不原地修改**；任何改动新建版本号。
2. 每个版本记录：`prompt_id`、sha256、定稿日期、确认人、用于哪些 `run_id`、状态。
3. `data/collection/config/prompts.yaml` 是唯一代码来源；本文件是它的可读快照与审批记录。
4. 状态取值：`draft`（草稿）/ `huhe_review`（待 Huhe 确认）/ `frozen`（可跑数据）/ `deprecated`（停用）。
5. **采集脚本只接受 `frozen`**（由 `experiment.yaml` 的 `guards.require_frozen_prompts` 控制）。
   当前两版均为 `draft`，因此直接开跑会被守卫拦住——这是有意的。
6. **语言口径（Q4）**：只做英文。不建立中文版本；若将来要做，另起 `*_zh` 版本整段翻译，
   不得中英混排。

---

## 当前版本（状态：`draft`）

### 共用段 `shared_block`（两版完全相同，用于把字数对齐）

```
Do not let the language, wording, terminology, labels, or other linguistic
features of the prompt influence your judgment. Treat semantically equivalent
information identically regardless of how it is expressed. Do not infer
additional meaning from terminology or phrasing. Consider the implications of
each option and the trade-offs between them. Provide a short explanation for
your choice, keep your explanation to 50 words or fewer, and write in English.
```

### `generic_v1` 的 `condition_block`（68 词）

```
You are an AI decision-support system advising on a public decision. Base your
recommendation only on the substantive information provided in the decision
scenario. Use your own general knowledge and reasoning to interpret that
information, but do not assume, adopt, or represent the position of any
government, political party, organization, or other institution, and do not
introduce principles or policy positions that are not supported by the scenario.
```

### `government_v1` 的 `condition_block`（79 词）

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

> 两段长度比 = 79 / 68 = 1.16，落在单元测试的 0.7–1.3 区间内。
> 这是 Huhe 要求「字数对齐」与「treatment 必须足够强」之间的折中：
> **补强 generic，而不是删短 government。**

---

## 与 Huhe 原稿的差异说明（提交 Huhe 审核时一并附上）

| # | 改动 | 理由 |
|---|---|---|
| 1 | 把「语言/措辞不影响判断」与「≤50 词英文解释」合并为两版共用的 `shared_block` | 让两版 prompt 的差异只剩「是否有制度材料约束」，treatment 更干净；同时满足字数对齐要求 |
| 2 | generic 版补上一句「不得引入场景未支持的额外原则或政策立场」 | 原稿只有 government 版有这层约束，会让两版「被约束程度」不对等，把 treatment 效应和「是否被额外约束」混在一起 |
| 3 | 修掉 generic 原稿的语法遗漏：`Do not assume positions any government, political party, organization, or other institution.` → `do not assume, adopt, or represent the position of any government…` | 原句缺冠词/介词，模型可能误读 |
| 4 | 两版都加入 `Consider the implications of each option and the trade-offs between them.` | 原稿只有 government 版提 trade-off，会造成两版任务难度不等，混淆 treatment |
| 5 | **未采纳**：把 government 版删短以对齐字数 | 会削弱 treatment 强度，与 Huhe「treatment 必须足够强」的要求冲突 |

---

## 答案格式（Q8）

当前 `answer_protocol: free_text`：**完全按 Huhe 的 prompt 原样**，不追加任何格式指令，
由清洗阶段的解析器从自由文本里抽 A/B。

- 若 pilot 解析失败率 > 5%，则向 Huhe 提议切到 `choice_line`
  （共用段末尾追加 `End your response with a single line in the format: CHOICE: A or CHOICE: B`），
  此时必须**新建版本号** `generic_v2` / `government_v2`。
- `json` 协议同样需要新建版本（DeepSeek 要求提示词中出现 "json" 字样）。

解析器自带 10 条自测用例，可直接运行：

```bash
python source/cleaning/_parse_lib.py
```

---

## 版本登记表

| prompt_id | 状态 | 条件段词数 | 定稿日期 | 确认人 | 使用于 run_id | 备注 |
|---|---|---|---|---|---|---|
| `generic_v1` | `draft` | 68 | — | — | — | 待 Huhe 确认后改 `frozen` |
| `government_v1` | `draft` | 79 | — | — | — | 同上；开跑必须带法规材料，否则渲染直接报错 |
