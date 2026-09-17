"""从模型自由文本回答中解析出二选一的结果。

为什么不干脆让模型输出 JSON？
    因为 Huhe 的 prompt 没有任何机器可读格式要求，改动 prompt 会改变 treatment
    本身。Q8 的决定是：prompt 保持原样（free_text 协议），解析放在清洗阶段，
    并且必须能被人工核查——因此这里同时输出 parse_method 与 parse_confidence，
    并另外抽 200 条人工核对（见 01_parse_responses.py）。

解析优先级：
    1. 协议自带标记（CHOICE: A / JSON 的 choice 字段）
    2. 明确的表态句（"...I would choose Option B..."）
    3. 全文只出现一个选项标签
    4. 兜底计数（低置信度，供人工复核）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any

# 选项标签。注意必须用负向先行断言收尾：[\b] 会让 "option because" 里的 b 被当成选项 B
# （这个 bug 真实存在过，自测用例专门盯住它）。
_OPTION_TAIL = r"(?![A-Za-z0-9])"
OPTION_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "A": [
        re.compile(r"\boption\b\s*[\(\[]?\s*a\s*[\)\]]?" + _OPTION_TAIL, re.I),
        re.compile(r"\bchoice\b\s*[\(\[]?\s*a\s*[\)\]]?" + _OPTION_TAIL, re.I),
        re.compile(r"\boption\s+(?:one|1)\b", re.I),
    ],
    "B": [
        re.compile(r"\boption\b\s*[\(\[]?\s*b\s*[\)\]]?" + _OPTION_TAIL, re.I),
        re.compile(r"\bchoice\b\s*[\(\[]?\s*b\s*[\)\]]?" + _OPTION_TAIL, re.I),
        re.compile(r"\boption\s+(?:two|2)\b", re.I),
    ],
}

# 表示"我选……"的动词/句式
CHOICE_VERB_RE = re.compile(
    r"(?:\bI\s+(?:would\s+|will\s+|do\s+)?(?:choose|select|pick|recommend|prefer|favor|favour|opt\s+for|go\s+with)"
    r"|\bmy\s+(?:choice|recommendation|selection|preference)\s+is"
    r"|\bthe\s+(?:better|best|most\s+appropriate|preferred)\s+(?:option|choice|system|version)\s+is"
    r"|\bI\s+(?:would\s+)?deploy"
    r"|\bI\s+(?:would\s+)?approve"
    r"|\bI\s+recommend\s+deploying"
    r")",
    re.I,
)

CHOICE_LINE_RE = re.compile(r"^\s*[>*\-\s]*choice\s*[:\-]\s*\**\s*([AB])\b", re.I | re.M)
INLINE_CHOICE_LINE_RE = re.compile(r"choice\s*[:\-]\s*\**\s*([AB])\b", re.I)

REFUSAL_PATTERNS = [
    re.compile(r"\bI\s+(?:cannot|can't|can not|am unable|am not able)\b", re.I),
    re.compile(r"\bI\s+must\s+decline\b", re.I),
    re.compile(r"\bas\s+an\s+AI\b", re.I),
    re.compile(r"\bI\s+don'?t\s+have\s+(?:personal\s+)?(?:preferences|opinions)\b", re.I),
    re.compile(r"\bI\s+am\s+not\s+able\s+to\s+(?:make|provide)\b", re.I),
    re.compile(r"无法(?:做出|提供|进行)?(?:选择|判断)"),
    re.compile(r"不能(?:做出|提供)(?:选择|判断)"),
]

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")

FIRST_SECOND_PATTERNS: dict[str, re.Pattern[str]] = {
    # 表头固定为 Option A | Option B（左 A 右 B），因此 first = A、second = B
    "A": re.compile(r"\b(?:the\s+)?first\s+(?:option|system|version|one)\b", re.I),
    "B": re.compile(r"\b(?:the\s+)?second\s+(?:option|system|version|one)\b", re.I),
}


@dataclass
class ParseResult:
    choice: str | None
    parse_method: str
    parse_confidence: str
    mentions_a: int
    mentions_b: int
    is_refusal: bool
    explanation_words: int
    explanation_chars: int
    choice_sentence: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mentions(text: str) -> tuple[int, int]:
    count_a = sum(len(pattern.findall(text)) for pattern in OPTION_PATTERNS["A"])
    count_b = sum(len(pattern.findall(text)) for pattern in OPTION_PATTERNS["B"])
    return count_a, count_b


def _detect_refusal(text: str) -> bool:
    return any(pattern.search(text) for pattern in REFUSAL_PATTERNS)


def _sentences(text: str) -> list[str]:
    return [chunk.strip() for chunk in SENTENCE_SPLIT_RE.split(text) if chunk.strip()]


def _parse_json_response(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    if not stripped:
        return None, ""
    candidate = stripped
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*", "", candidate)
        candidate = re.sub(r"```\s*$", "", candidate)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if not match:
            return None, ""
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None, ""
    if not isinstance(payload, dict):
        return None, ""
    raw_choice = str(payload.get("choice", "")).strip().upper()
    choice = raw_choice[0] if raw_choice[:1] in {"A", "B"} else None
    explanation = str(payload.get("explanation", "")).strip()
    return choice, explanation


def parse_choice(text: str, protocol: str = "free_text") -> ParseResult:
    """解析模型的二选一结果。text 允许为空（调用失败或被截断）。"""
    raw = text or ""
    normalized = raw.replace("\u2018", "'").replace("\u2019", "'")
    words = len(re.findall(r"[A-Za-z0-9'][A-Za-z0-9'-]*", normalized))
    mentions_a, mentions_b = _mentions(normalized)
    refusal = _detect_refusal(normalized)

    choice: str | None = None
    method = "unparsed"
    confidence = "none"
    evidence = ""

    # 1) 协议标记
    if protocol == "json":
        choice, explanation = _parse_json_response(normalized)
        if choice:
            method, confidence, evidence = "json_field", "high", explanation[:200]
    if choice is None and protocol in {"choice_line", "free_text"}:
        match = CHOICE_LINE_RE.search(normalized) or INLINE_CHOICE_LINE_RE.search(normalized)
        if match:
            choice = match.group(1).upper()
            method, confidence = "choice_marker", "high"
            evidence = match.group(0)

    # 2) 表态句（逐句找"选择动词 + 选项标签"）
    if choice is None:
        for sentence in _sentences(normalized):
            if not CHOICE_VERB_RE.search(sentence):
                continue
            has_a = any(p.search(sentence) for p in OPTION_PATTERNS["A"])
            has_b = any(p.search(sentence) for p in OPTION_PATTERNS["B"])
            if has_a and not has_b:
                choice, method, confidence, evidence = "A", "choice_sentence", "high", sentence
                break
            if has_b and not has_a:
                choice, method, confidence, evidence = "B", "choice_sentence", "high", sentence
                break

    # 3) 全文只提到一个选项
    if choice is None and mentions_a and not mentions_b:
        choice, method, confidence = "A", "single_mention", "medium"
    elif choice is None and mentions_b and not mentions_a:
        choice, method, confidence = "B", "single_mention", "medium"

    # 4) 序数表述（first / second）
    if choice is None:
        has_first = FIRST_SECOND_PATTERNS["A"].search(normalized) is not None
        has_second = FIRST_SECOND_PATTERNS["B"].search(normalized) is not None
        if has_first and not has_second:
            choice, method, confidence = "A", "ordinal_first", "medium"
        elif has_second and not has_first:
            choice, method, confidence = "B", "ordinal_second", "medium"

    # 5) 兜底：第一条句子里的标签 + 计数（低置信度）
    if choice is None and mentions_a != mentions_b and (mentions_a or mentions_b):
        choice = "A" if mentions_a > mentions_b else "B"
        method, confidence = "mention_counts", "low"
    if choice is None and mentions_a == mentions_b and mentions_a > 0:
        first_sentence = next(
            (
                sentence
                for sentence in _sentences(normalized)
                if any(p.search(sentence) for p in OPTION_PATTERNS["A"])
                or any(p.search(sentence) for p in OPTION_PATTERNS["B"])
            ),
            "",
        )
        match_a = any(p.search(first_sentence) for p in OPTION_PATTERNS["A"])
        match_b = any(p.search(first_sentence) for p in OPTION_PATTERNS["B"])
        if match_a != match_b:
            choice = "A" if match_a else "B"
            method, confidence, evidence = "first_label", "low", first_sentence

    if refusal and choice is None:
        method = "refusal"
    elif not normalized.strip():
        method = "empty_response"

    if not evidence and choice:
        for sentence in _sentences(normalized):
            if choice == "A" and any(p.search(sentence) for p in OPTION_PATTERNS["A"]):
                evidence = sentence
                break
            if choice == "B" and any(p.search(sentence) for p in OPTION_PATTERNS["B"]):
                evidence = sentence
                break

    return ParseResult(
        choice=choice,
        parse_method=method,
        parse_confidence=confidence,
        mentions_a=mentions_a,
        mentions_b=mentions_b,
        is_refusal=refusal,
        explanation_words=words,
        explanation_chars=len(normalized.strip()),
        choice_sentence=evidence[:500],
    )


# --- 文本分析用的框架词表（04_text_analysis.py 使用）------------------------

FRAMEWORK_KEYWORDS: dict[str, list[str]] = {
    "safety": ["safety", "safe", "harm", "risk", "protection", "protect"],
    "casualties": ["civilian", "casualt", "collateral", "injury", "death", "fatal"],
    "accountability": [
        "accountab", "responsib", "liab", "immunity", "blame", "oversight", "audit",
    ],
    "efficiency": ["efficien", "timel", "delay", "speed", "prompt", "fast", "latency"],
    "accuracy": ["accura", "precis", "reliab", "error", "false positive", "false negative", "miss"],
    "law_regulation": [
        "regulation", "law", "legal", "statut", "compliance", "compliant", "guidance",
        "framework", "provision", "article",
    ],
    "ethics_rights": ["ethic", "rights", "privacy", "dignity", "fair", "discriminat"],
    "institution": ["public", "private", "multinational", "government", "company", "university"],
    "cost": ["cost", "resource", "budget", "expens"],
    "trust": ["trust", "public confidence", "acceptance", "legitim"],
}


def count_frameworks(text: str) -> dict[str, int]:
    lowered = (text or "").lower()
    return {
        framework: sum(lowered.count(keyword) for keyword in keywords)
        for framework, keywords in FRAMEWORK_KEYWORDS.items()
    }


# --- 自测 -------------------------------------------------------------------

_SELF_TEST_CASES: list[tuple[str, str, str | None, str]] = [
    ("free_text", "Option B. Option A has lower civilian risk, but Option B is more accountable.", "B", "不确定"),
    ("free_text", "I would choose Option A because it minimizes civilian casualties.", "A", "high"),
    ("free_text", "My recommendation is Option B: real-time analysis matters most.", "B", "high"),
    ("free_text", "The most appropriate option is Option A.", "A", "high"),
    ("free_text", "I prefer the second option because of the accountability mechanism.", "B", "medium"),
    ("choice_line", "Stronger safeguards matter.\nCHOICE: B", "B", "high"),
    ("json", '{"choice": "A", "explanation": "Lower risk overall."}', "A", "high"),
    ("free_text", "I cannot make this decision without more information.", None, "none"),
    ("free_text", "As an AI, I do not have preferences.", None, "none"),
    ("free_text", "", None, "none"),
]


def _selftest() -> int:
    failures = 0
    for protocol, text, expected_choice, expected_confidence in _SELF_TEST_CASES:
        result = parse_choice(text, protocol)
        ok = result.choice == expected_choice
        if expected_confidence != "不确定" and ok:
            ok = result.parse_confidence == expected_confidence
        status = "ok  " if ok else "FAIL"
        print(
            f"[{status}] protocol={protocol:<11} choice={result.choice!s:<5} "
            f"method={result.parse_method:<15} conf={result.parse_confidence:<6} "
            f"text={text[:60]!r}"
        )
        failures += 0 if ok else 1
    print(f"\n{len(_SELF_TEST_CASES) - failures}/{len(_SELF_TEST_CASES)} 通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
