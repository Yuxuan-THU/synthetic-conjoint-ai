"""02 · 构建 treatment 法规文本（抽取 / 抓取 / 人工校订稿优先）。

背景（2026-09-18 核查）：
    ai legal text/china/ 下的三份 PDF 均无文本层；唯一的 OCR 版本错字极多
    （"生成式人工智能玻务管理暂行办法""第一量总""需二直"），不可用于 treatment。
    因此中国法规改为从网信办官方页面抓取；美国用本地 NIST AI RMF 的 PDF。

产物：
    data/raw/legal_texts/{law_text_id}.txt        纯文本（直接注入 prompt）
    data/raw/legal_texts/manifest.csv             版本登记：来源、sha256、字符数、审核状态
    data/raw/legal_texts/quality_report.csv       自动质检结果

优先级：manual/{id}.txt  >  fetch  >  pdf
    manual/ 目录用于放人工校订稿（例如从官方 PDF 誊录的文本），一旦存在即优先生效。

用法：
    python data/collection/02_build_legal_texts.py
    python data/collection/02_build_legal_texts.py --offline          # 只用本地已有文件
    python data/collection/02_build_legal_texts.py --only CN_generative_ai_interim_measures_2023 --force
    python data/collection/02_build_legal_texts.py --set-review-status US_nist_ai_rmf_1_0_2023=huhe_confirmed
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _llm import config as cfg  # noqa: E402
from _llm.io_utils import (  # noqa: E402
    estimate_tokens,
    iso_beijing,
    now_utc,
    sha256_text,
    truncate_keep_tail,
)

MANIFEST_COLUMNS = [
    "law_text_id",
    "jurisdiction",
    "enabled",
    "title_en",
    "title_zh",
    "issued",
    "mode_used",
    "source",
    "retrieved_at_beijing",
    "file",
    "chars",
    "chars_after_max_chars",
    "est_tokens",
    "sha256",
    "review_status",
    "quality_status",
    "extract_rules",
    "notes",
]

QUALITY_COLUMNS = [
    "law_text_id",
    "jurisdiction",
    "mode_used",
    "chars",
    "non_whitespace_chars",
    "cjk_ratio",
    "replacement_chars",
    "chars_per_page",
    "missing_markers",
    "articles_detected",
    "tables_or_garbage_flags",
    "quality_status",
    "quality_message",
]

# 中文法规条号：第一条、第二十四条……
CN_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百零〇]+条")
UNDECODEABLE_FLAGS = ("\ufffd", "\u0000", "�")

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


# --- HTML 转纯文本 ----------------------------------------------------------


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

    标记是显式写在 config 里的，可审计；剪掉多少字符会记入 manifest。
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


def extract_pdf_text(path: Path) -> tuple[str, int]:
    """用 PyMuPDF 抽取 PDF 文本层；返回 (文本, 页数)。"""
    import fitz  # PyMuPDF

    document = fitz.open(path)
    try:
        pages = [document.load_page(index).get_text() for index in range(document.page_count)]
        page_count = document.page_count
    finally:
        document.close()
    return "\n".join(pages), page_count


# --- 质检 -------------------------------------------------------------------


def quality_check(
    text: str,
    law: dict[str, Any],
    mode_used: str,
    page_count: int | None,
) -> tuple[dict[str, Any], str, str]:
    expected_language = str(law.get("retrieval", {}).get("expected_language", "en"))
    chars = len(text)
    non_ws = sum(1 for ch in text if not ch.isspace())
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    cjk_ratio = round(cjk / non_ws, 4) if non_ws else 0.0
    replacement_chars = sum(text.count(flag) for flag in UNDECODEABLE_FLAGS)
    chars_per_page = round(chars / page_count, 1) if page_count else ""

    markers = [str(m) for m in (law.get("quality", {}).get("must_contain") or [])]
    missing = [marker for marker in markers if marker not in text]

    articles_expected = law.get("quality", {}).get("expected_articles")
    articles_detected = len(set(CN_ARTICLE_RE.findall(text))) if expected_language == "zh" else None

    flags: list[str] = []
    if replacement_chars:
        flags.append(f"undecodable_chars={replacement_chars}")
    if page_count and isinstance(chars_per_page, float) and chars_per_page < 200:
        flags.append("likely_scanned_pdf_no_text_layer")
    if expected_language == "zh" and cjk_ratio < 0.5:
        flags.append(f"low_cjk_ratio={cjk_ratio}")
    if expected_language == "zh" and articles_detected is not None:
        if articles_expected and articles_detected < int(articles_expected):
            flags.append(f"articles_detected={articles_detected}<{articles_expected}")

    status = "ok"
    message = "通过"
    if not text.strip() or missing:
        status = "fail"
        message = (
            "文本为空" if not text.strip() else f"缺少锚点字符串：{missing}"
        )
    elif flags:
        status = "warn"
        message = "；".join(flags)

    report = {
        "law_text_id": law["id"],
        "jurisdiction": law["jurisdiction"],
        "mode_used": mode_used,
        "chars": chars,
        "non_whitespace_chars": non_ws,
        "cjk_ratio": cjk_ratio,
        "replacement_chars": replacement_chars,
        "chars_per_page": chars_per_page,
        "missing_markers": ";".join(missing),
        "articles_detected": "" if articles_detected is None else articles_detected,
        "tables_or_garbage_flags": ";".join(flags),
        "quality_status": status,
        "quality_message": message,
    }
    return report, status, message


# --- 主流程 -----------------------------------------------------------------


def read_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["law_text_id"]: row for row in csv.DictReader(handle)}


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建 treatment 法规文本")
    parser.add_argument("--only", action="append", default=None, help="只处理指定 law_text_id")
    parser.add_argument("--offline", action="store_true", help="不联网，只用本地已有文件")
    parser.add_argument("--force", action="store_true", help="忽略已有产物重新生成")
    parser.add_argument(
        "--set-review-status",
        action="append",
        default=None,
        metavar="ID=STATUS",
        help="人工把某份文本标记为 pending / huhe_confirmed / rejected",
    )
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
    manual_dir = cfg.resolve_path(paths_cfg["manual_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    manual_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "manifest.csv"
    quality_path = output_dir / "quality_report.csv"
    previous_manifest = read_manifest(manifest_path)

    # --- 人工更新审核状态（不重新抽取）-------------------------------------
    if args.set_review_status:
        updates: dict[str, str] = {}
        for item in args.set_review_status:
            if "=" not in item:
                raise SystemExit(f"--set-review-status 需要 ID=STATUS 形式：{item}")
            law_id, status = item.split("=", 1)
            if status not in {"pending", "huhe_confirmed", "rejected"}:
                raise SystemExit(f"未知审核状态：{status}")
            updates[law_id.strip()] = status.strip()
        rows = list(previous_manifest.values())
        for row in rows:
            if row["law_text_id"] in updates:
                row["review_status"] = updates[row["law_text_id"]]
        write_csv(manifest_path, rows, MANIFEST_COLUMNS)
        for law_id, status in updates.items():
            print(f"审核状态已更新：{law_id} -> {status}")
        return 0

    selected = set(args.only) if args.only else None
    manifest_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for law in legal_config["laws"]:
        law_id = str(law["id"])
        enabled = bool(law.get("enabled", False))
        # 未选中的、以及停用且未被 --only 点名的条目直接跳过，不抓取、不计入失败
        if selected is None and not enabled:
            if law_id in previous_manifest:
                manifest_rows.append(previous_manifest[law_id])
            continue
        if selected and law_id not in selected:
            # 未选中的条目保留原记录，避免 manifest 丢行
            if law_id in previous_manifest:
                manifest_rows.append(previous_manifest[law_id])
            continue

        output_path = output_dir / f"{law_id}.txt"
        manual_path = manual_dir / f"{law_id}.txt"
        retrieval = law.get("retrieval", {})
        mode = str(retrieval.get("mode", "manual"))

        if output_path.exists() and not args.force and not manual_path.exists():
            text = output_path.read_text(encoding="utf-8")
            mode_used = previous_manifest.get(law_id, {}).get("mode_used", mode)
            source = previous_manifest.get(law_id, {}).get("source", "")
            extract_note = previous_manifest.get(law_id, {}).get("extract_rules", "")
            page_count = None
            print(f"[skip] {law_id}: 已有文本（{len(text)} 字符），未重新生成")
        else:
            text = ""
            mode_used = mode
            source = ""
            extract_note = ""
            page_count = None

            if manual_path.exists():
                text = manual_path.read_text(encoding="utf-8")
                mode_used = "manual"
                source = f"manual override: {manual_path.relative_to(cfg.PROJECT_ROOT)}"
            elif mode == "pdf":
                pdf_path = source_root / str(retrieval["path"])
                if not pdf_path.exists():
                    failures.append(f"{law_id}: PDF 不存在 {pdf_path}")
                    continue
                text, page_count = extract_pdf_text(pdf_path)
                source = str(pdf_path.relative_to(cfg.PROJECT_ROOT))
            elif mode == "fetch":
                if args.offline:
                    print(f"[skip] {law_id}: --offline 且无人工校订稿，跳过抓取")
                    if law_id in previous_manifest:
                        manifest_rows.append(previous_manifest[law_id])
                    continue
                urls = [str(retrieval["url"])] + list(retrieval.get("fallback_urls") or [])
                last_error: Exception | None = None
                for url in urls:
                    try:
                        html = fetch_html(url)
                        text = html_to_text(html)
                        source = url
                        break
                    except Exception as exc:  # noqa: BLE001 - 逐个 fallback 尝试
                        last_error = exc
                        print(f"[warn] {law_id}: 抓取失败 {url} -> {type(exc).__name__}")
                if not text and last_error is not None:
                    failures.append(f"{law_id}: 所有 URL 均抓取失败（{last_error}）")
                    continue
            else:
                failures.append(f"{law_id}: 未知 retrieval.mode={mode}")
                continue

            # 网页导航/页脚等非文档内容必须剪除，否则 treatment 里会混进“设为首页加入收藏”
            extract_cfg = dict(law.get("extract") or {})
            try:
                text, applied = apply_extract_rules(text, extract_cfg)
            except ValueError as exc:
                failures.append(f"{law_id}: 起止标记定位失败（{exc}）")
                continue
            text, lines_removed = strip_page_furniture(
                text, list(law.get("strip_line_patterns") or [])
            )
            if applied.get("chars_removed_by_markers"):
                extract_note = (
                    f"markers: -{applied['chars_removed_by_markers']} chars "
                    f"(start={applied.get('start_marker', '')!r}, end={applied.get('end_marker', '')!r})"
                )
            if lines_removed:
                extract_note = (extract_note + f"; furniture: -{lines_removed} lines").strip("; ")

            text = clean_text(text, collapse_blank_lines=collapse_blank)

        # 截断（若配置）——必须记录，因为截断会改变 treatment 强度
        text, truncated = truncate_keep_tail(text, int(max_chars) if max_chars else None)
        if truncated:
            print(f"[warn] {law_id}: 文本按 processing.max_chars={max_chars} 截断")

        if not output_path.exists() or args.force or manual_path.exists():
            output_path.write_text(text, encoding="utf-8")

        digest = sha256_text(text)
        report, quality_status, quality_message = quality_check(text, law, mode_used, page_count)

        previous = previous_manifest.get(law_id, {})
        # 内容未变则沿用人工确认过的审核状态；内容变了则退回 pending
        if previous.get("sha256") == digest and previous.get("review_status"):
            review_status = previous["review_status"]
        else:
            review_status = "pending"

        manifest_rows.append(
            {
                "law_text_id": law_id,
                "jurisdiction": law["jurisdiction"],
                "enabled": int(enabled),
                "title_en": law.get("title_en", ""),
                "title_zh": law.get("title_zh", ""),
                "issued": law.get("issued", ""),
                "mode_used": mode_used,
                "source": source,
                "retrieved_at_beijing": iso_beijing(now_utc())[:19],
                "file": f"data/raw/legal_texts/{law_id}.txt",
                "chars": len(text),
                "chars_after_max_chars": len(text) if truncated else "",
                "est_tokens": estimate_tokens(
                    text, str(retrieval.get("expected_language", "en"))
                ),
                "sha256": digest,
                "review_status": review_status,
                "quality_status": quality_status,
                "extract_rules": extract_note,
                "notes": " ".join(str(law.get("notes", "")).split()),
            }
        )
        quality_rows.append(report)

        marker = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}[quality_status]
        print(
            f"[{marker}] {law_id}: {len(text)} 字符, ≈{manifest_rows[-1]['est_tokens']} tokens, "
            f"mode={mode_used}, review={review_status} ({quality_message})"
        )

    manifest_rows.sort(key=lambda row: (row["jurisdiction"], row["law_text_id"]))
    quality_rows.sort(key=lambda row: (row["jurisdiction"], row["law_text_id"]))
    write_csv(manifest_path, manifest_rows, MANIFEST_COLUMNS)
    write_csv(quality_path, quality_rows, QUALITY_COLUMNS)

    print(f"\nmanifest       : {manifest_path}")
    print(f"quality_report : {quality_path}")

    blocked = [
        row
        for row in manifest_rows
        if int(row["enabled"]) == 1 and row["review_status"] != "huhe_confirmed"
    ]
    if blocked:
        print("\n以下启用中的法规尚未人工确认（采集脚本会拒绝开跑）：")
        for row in blocked:
            print(f"  - {row['law_text_id']}  (review_status={row['review_status']})")
        print(
            "确认文本无误后执行：\n"
            "  python data/collection/02_build_legal_texts.py "
            f"--set-review-status {blocked[0]['law_text_id']}=huhe_confirmed"
        )

    if failures:
        print("\n失败项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
