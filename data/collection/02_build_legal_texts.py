"""02 · 构建 treatment 法规文本（官方页面抓取 / 本地 PDF 抽取）。

背景（2026-09-18 核查）：
    ai legal text/china/ 下的三份 PDF 均无文本层；唯一的 OCR 版本错字极多
    （"生成式人工智能玻务管理暂行办法""第一量总"），不可用于 treatment。
    因此中国法规改为从网信办官方页面抓取；美国用本地 NIST AI RMF 的 PDF。

产物：
    data/raw/legal_texts/{law_text_id}.txt    纯文本（直接注入 prompt）

说明：
    目录里只保留最终 txt。来源 URL / PDF 路径、标题、年份等文档信息登记在
    data/collection/config/legal_texts.yaml；脚本不写任何登记表或质检报告。
    文本哈希由采集运行器（03）在运行时计算，并写入每一行响应数据。

用法：
    python data/collection/02_build_legal_texts.py                  # 已有 txt 则跳过
    python data/collection/02_build_legal_texts.py --offline        # 不联网
    python data/collection/02_build_legal_texts.py --only <law_text_id> --force
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _llm import config as cfg  # noqa: E402
from _llm.io_utils import estimate_tokens, sha256_text, truncate_keep_tail  # noqa: E402

BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "table", "section", "article", "header",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dl", "dd", "dt",
}
# 容器型跳过标签：有闭合标签，可以安全地用深度计数
SKIP_CONTAINER_TAGS = {"script", "style", "noscript", "svg", "head", "iframe"}
# 空元素（void）：没有闭合标签，绝不能改变深度计数
# 之前的 bug 就出在这里：<meta>/<link> 在 <head> 里不断抬高深度，导致正文全被跳过。
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _HtmlToText(HTMLParser):
    """把正文 HTML 转成保留段落的纯文本；不做正文提取（官方页面结构简单，够用）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            if tag in BLOCK_TAGS and self._skip_depth == 0:
                self._chunks.append("\n")
            return
        if tag in SKIP_CONTAINER_TAGS:
            self._skip_depth += 1
            return
        if tag in BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # 自闭合写法 <meta /> <br /> 等，不改变深度
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        if tag in SKIP_CONTAINER_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag in BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def html_to_text(html: str) -> str:
    parser = _HtmlToText()
    parser.feed(html)
    parser.close()
    text = parser.text()
    if not text.strip():
        # 正文为空通常意味着页面结构异常（或触发了反爬页），让调用方去试 fallback_url
        raise ValueError("HTML 解析后正文为空（页面可能改版或返回了拦截页）")
    return text


def clean_text(text: str, collapse_blank_lines: bool = True) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    lines = [line.strip() for line in text.split("\n")]
    if collapse_blank_lines:
        result: list[str] = []
        blank_run = 0
        for line in lines:
            if not line:
                blank_run += 1
                if blank_run > 1:
                    continue
            else:
                blank_run = 0
            result.append(line)
        lines = result
    return "\n".join(lines).strip()


def find_nth(text: str, needle: str, occurrence: int) -> int:
    """返回 needle 第 occurrence 次出现的位置（1-based；负数表示从末尾数）。找不到返回 -1。"""
    if not needle:
        return -1
    if occurrence >= 0:
        index = -1
        for _ in range(max(1, occurrence)):
            index = text.find(needle, index + 1)
            if index < 0:
                return -1
        return index
    index = len(text)
    for _ in range(abs(occurrence)):
        index = text.rfind(needle, 0, index)
        if index < 0:
            return -1
    return index


def apply_extract_rules(text: str, extract: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """用起止标记剪掉网页导航/页脚等非文档内容（官方页面抓取时必须做）。

    标记显式写在 config 里，可审计；剪掉多少字符会打印出来。
    """
    applied: dict[str, Any] = {}
    original_length = len(text)

    start_marker = extract.get("start_marker")
    if start_marker:
        index = find_nth(text, str(start_marker), int(extract.get("start_occurrence", 1)))
        if index < 0:
            raise ValueError(f"start_marker 未找到：{start_marker!r}")
        text = text[index:]
        applied["start_marker"] = str(start_marker)

    end_marker = extract.get("end_marker")
    if end_marker:
        index = find_nth(text, str(end_marker), int(extract.get("end_occurrence", 1)))
        if index < 0:
            raise ValueError(f"end_marker 未找到：{end_marker!r}")
        text = text[: index + len(str(end_marker))]
        applied["end_marker"] = str(end_marker)

    applied["chars_removed_by_markers"] = original_length - len(text)
    return text, applied


def strip_page_furniture(text: str, patterns: list[str] | None) -> tuple[str, int]:
    """删除逐页重复的页眉/页脚/页码等排版残留（不删正文段落）。"""
    if not patterns:
        return text, 0
    compiled = [re.compile(pattern) for pattern in patterns]
    kept: list[str] = []
    removed = 0
    for line in text.split("\n"):
        if any(pattern.search(line) for pattern in compiled):
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept), removed


# --- 抓取与抽取 -------------------------------------------------------------


def fetch_html(url: str, timeout_s: int = 60) -> str:
    import requests

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 research-project-scraper/1.0"
            " (academic use; contact: project maintainer)"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    response = requests.get(url, headers=headers, timeout=timeout_s)
    response.raise_for_status()
    content = response.content

    encoding = response.encoding or ""
    if not encoding or encoding.lower() in {"iso-8859-1", "ascii"}:
        match = re.search(rb'charset=["\']?([\w\-]+)', content[:8192], re.IGNORECASE)
        encoding = match.group(1).decode("ascii", errors="ignore") if match else "utf-8"
    return content.decode(encoding, errors="replace")


def extract_pdf_text(path: Path) -> str:
    """用 PyMuPDF 抽取 PDF 文本层。"""
    import fitz  # PyMuPDF

    document = fitz.open(path)
    try:
        pages = [document.load_page(index).get_text() for index in range(document.page_count)]
    finally:
        document.close()
    return "\n".join(pages)


def build_text(law: dict[str, Any], source_root: Path, offline: bool) -> tuple[str, str]:
    """按 retrieval 配置取文；返回 (文本, 来源)。失败抛 ValueError。"""
    retrieval = dict(law.get("retrieval") or {})
    mode = str(retrieval.get("mode", ""))

    if mode == "pdf":
        pdf_path = source_root / str(retrieval["path"])
        if not pdf_path.exists():
            raise ValueError(f"PDF 不存在：{pdf_path}")
        return extract_pdf_text(pdf_path), str(pdf_path.relative_to(cfg.PROJECT_ROOT))

    if mode == "fetch":
        if offline:
            raise ValueError("--offline 下无法抓取网页")
        urls = [str(retrieval["url"])] + [str(url) for url in (retrieval.get("fallback_urls") or [])]
        last_error: Exception | None = None
        for url in urls:
            try:
                return html_to_text(fetch_html(url)), url
            except Exception as exc:  # noqa: BLE001 - 逐个 fallback 尝试
                last_error = exc
                print(f"[warn] 抓取失败 {url} -> {type(exc).__name__}")
        raise ValueError(f"所有 URL 均抓取失败（{last_error}）")

    raise ValueError(f"未知 retrieval.mode={mode}（支持 pdf / fetch）")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建 treatment 法规文本")
    parser.add_argument("--only", action="append", default=None, help="只处理指定 law_text_id（可多次）")
    parser.add_argument("--offline", action="store_true", help="不联网，只用本地已有文件")
    parser.add_argument("--force", action="store_true", help="忽略已有 txt 重新生成")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    legal_config = cfg.load_legal_texts_config()
    paths_cfg = legal_config["paths"]
    processing_cfg = legal_config.get("processing", {})
    collapse_blank = bool(processing_cfg.get("collapse_blank_lines", True))
    max_chars = processing_cfg.get("max_chars")

    source_root = cfg.resolve_path(paths_cfg["source_root"])
    output_dir = cfg.resolve_path(paths_cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = set(args.only) if args.only else None
    failures: list[str] = []

    for law in legal_config["laws"]:
        law_id = str(law["id"])
        if selected is not None and law_id not in selected:
            continue
        if selected is None and not bool(law.get("enabled", False)):
            continue

        retrieval = dict(law.get("retrieval") or {})
        language = str(retrieval.get("expected_language", "en"))
        output_path = output_dir / f"{law_id}.txt"

        if output_path.exists() and not args.force:
            text = output_path.read_text(encoding="utf-8")
            print(
                f"[skip] {law_id}: 已有文本（{len(text)} 字符，≈{estimate_tokens(text, language)} tokens）"
                f"；需要重建时加 --force"
            )
            continue

        try:
            text, source = build_text(law, source_root, args.offline)
        except ValueError as exc:
            failures.append(f"{law_id}: {exc}")
            continue

        try:
            text, applied = apply_extract_rules(text, dict(law.get("extract") or {}))
        except ValueError as exc:
            failures.append(f"{law_id}: 起止标记定位失败（{exc}）")
            continue
        text, lines_removed = strip_page_furniture(text, list(law.get("strip_line_patterns") or []))
        text = clean_text(text, collapse_blank_lines=collapse_blank)
        text, truncated = truncate_keep_tail(text, int(max_chars) if max_chars else None)
        if truncated:
            print(f"[warn] {law_id}: 文本按 processing.max_chars={max_chars} 截断")

        # 质检锚点：缺失即拒绝写入（防止把 OCR 乱码或错误页面写进 treatment）
        missing = [
            str(marker)
            for marker in (law.get("quality", {}).get("must_contain") or [])
            if str(marker) not in text
        ]
        if not text.strip() or missing:
            reason = "文本为空" if not text.strip() else f"缺少锚点字符串：{missing}"
            failures.append(f"{law_id}: {reason}")
            continue

        output_path.write_text(text, encoding="utf-8")

        notes: list[str] = []
        if applied.get("chars_removed_by_markers"):
            notes.append(f"剪除导航 {applied['chars_removed_by_markers']} 字符")
        if lines_removed:
            notes.append(f"删除页眉页脚 {lines_removed} 行")
        suffix = "；".join(notes)
        print(
            f"[ok] {law_id}: {len(text)} 字符，≈{estimate_tokens(text, language)} tokens"
            f"（sha256 {sha256_text(text)[:12]}…）\n"
            f"      来源：{source}{f'（{suffix}）' if suffix else ''}\n"
            f"      写入：{output_path.relative_to(cfg.PROJECT_ROOT)}"
        )

    if failures:
        print("\n失败项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
