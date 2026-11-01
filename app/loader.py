"""文档解析与切分。

设计要点：
1. PDF 按页读，保留页码——回答要引用出处，页码是最直观的定位。
2. Markdown 按标题切段，标题写进 metadata——检索时同一小节的内容更容易一起命中。
3. 切分用「滑动窗口 + 边界回退」：优先在句号/问号/换行处断开，避免把一句话从中间劈开。

核心逻辑只依赖标准库，pypdf 在真正读 PDF 时才导入，所以切分逻辑可以离线单测。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)

# 中文小说常见的章节写法：「第一章」「1、第一章」「第三卷」……
# 只认行首，避免正文里出现「第一章」三个字被误判。
CN_CHAPTER_RE = re.compile(
    r"^[ \t]*(?:\d+[ \t]*[、.．][ \t]*)?"
    r"第[0-9一二三四五六七八九十百千零〇两]+[章节回卷部篇].*$",
    re.M,
)

SENTENCE_ENDS = "。！？!?；;\n"


def read_text_auto(path: "Path | str") -> str:
    """按 UTF-8 / GB18030 的顺序尝试解码。

    中文小说 txt 大量是 GBK 编码。写死 UTF-8 不会报错，只会得到一屏乱码——
    乱码安安静静地入库，最后检索全废，而且很难查。
    """
    raw = Path(path).read_bytes()

    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="ignore")


def normalize(text: str) -> str:
    """压掉多余空白，但保留段落分隔。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_headings(text: str) -> list[tuple[int, int, str]]:
    """找出所有标题位置，返回 [(起, 止, 标题)]，按位置排序。

    同时支持 Markdown 的 `## 标题` 和中文小说的「第一章」「1、第一章」。
    """
    marks: list[tuple[int, int, str]] = []

    for match in HEADING_RE.finditer(text):
        marks.append((match.start(), match.end(), match.group(2).strip()))

    for match in CN_CHAPTER_RE.finditer(text):
        marks.append((match.start(), match.end(), match.group(0).strip()))

    marks.sort(key=lambda item: item[0])

    # 同一行被两条规则同时命中时只保留一个
    deduped: list[tuple[int, int, str]] = []
    for mark in marks:
        if deduped and mark[0] < deduped[-1][1]:
            continue
        deduped.append(mark)
    return deduped


def split_by_heading(text: str) -> list[tuple[str, str]]:
    """按标题把正文切成 (标题, 正文) 段；没有标题时返回 [('', 全文)]。"""
    matches = _find_headings(text)
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []
    # 第一个标题之前的内容（书名、简介、文案等）
    if matches[0][0] > 0:
        head = text[: matches[0][0]].strip()
        if head:
            sections.append(("", head))

    for i, (start_pos, end_pos, title) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        body = text[end_pos:end].strip()
        if body:
            sections.append((title, body))
    return sections


def chunk_text(text: str, size: int = 512, overlap: int = 64) -> list[str]:
    """滑动窗口切分，尽量在句子边界断开。"""
    text = normalize(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + size, length)

        if end < length:
            window = text[start:end]
            # 只在窗口后半段找断点，避免切出过短的块
            cut = -1
            for ch in SENTENCE_ENDS:
                cut = max(cut, window.rfind(ch))
            if cut >= size // 2:
                end = start + cut + 1

        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)

        if end >= length:
            break
        start = max(end - overlap, start + 1)

    return chunks


def read_pdf(path: Path) -> Iterable[tuple[int, str]]:
    """逐页产出 (页码, 文本)。pypdf 只在调用时才导入。"""
    from pypdf import PdfReader  # noqa: WPS433  (延迟导入，避免测试依赖)

    reader = PdfReader(str(path))
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            yield index + 1, text


def load_file(path: Path, size: int = 512, overlap: int = 64) -> list[Chunk]:
    """把一个文件切成若干 Chunk，metadata 里带来源、页码/标题、块序号。"""
    path = Path(path)
    suffix = path.suffix.lower()
    source = path.name
    chunks: list[Chunk] = []

    if suffix == ".pdf":
        for page_no, text in read_pdf(path):
            for i, piece in enumerate(chunk_text(text, size, overlap)):
                chunks.append(
                    Chunk(
                        text=piece,
                        metadata={
                            "source": source,
                            "page": page_no,
                            "section": "",
                            "chunk_index": len(chunks),
                        },
                    )
                )
        return chunks

    text = read_text_auto(path)
    for section, body in split_by_heading(text):
        for piece in chunk_text(body, size, overlap):
            chunks.append(
                Chunk(
                    text=piece,
                    metadata={
                        "source": source,
                        "page": 0,
                        "section": section,
                        "chunk_index": len(chunks),
                    },
                )
            )
    return chunks


def describe_location(metadata: dict) -> str:
    """把 metadata 变成一句人看得懂的出处。"""
    source = metadata.get("source", "未知文档")
    page = metadata.get("page") or 0
    section = metadata.get("section") or ""
    if page:
        return f"{source} 第 {page} 页"
    if section:
        return f"{source} · {section}"
    return source
