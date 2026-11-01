"""角色卡：从小说原文抽取人物设定，并组装成对话用的 system prompt。

三个设计要点：

1. 抽角色卡不是让模型"描述这个人"，而是收集可执行的说话依据：语气、句长、用词、口头禅。
   泛泛的"性格开朗"对生成的帮助几乎为零。

2. example_lines 必须逐字摘录原文。让模型自己"写几句示例对白"，出来的必然是通用 AI 腔——
   它写的是「这类角色会说的话」，不是「这个角色说过的话」。

3. knows / does_not_know 划出视角边界。角色只知道他在场或被明确告知的事。
   角色扮演最典型的穿帮不是"不知道"，而是"不该知道却知道"。
"""

import json
import re
from pathlib import Path

from . import config
from .http import ApiError
from .llm import chat
from .loader import split_by_heading

EXTRACT_SYSTEM = (
    "你是一位资深小说编辑，擅长从原文中精确提取人物设定。"
    "只输出 JSON，不要任何解释，不要 Markdown 代码块。"
)

EXTRACT_TEMPLATE = """下面是一部小说的原文。请抽取「{name}」这个角色的人物设定。

硬性要求：
1. 所有字段必须能在原文中找到依据，不要臆造。
2. example_lines 必须逐字摘录原文中该角色的对白，不得改写、不得续写。
3. 按故事**结局时**的状态来写：年龄、身份、处境、说话方式都以结尾为准。
   不要写童年和成年混在一起的设定。
4. knows 写这个角色亲身经历、参与或在场看到的事，尽量写全（这是聊天时的话题来源）。
5. does_not_know 只写小说里**完全没写**的事——比如角色后来的生活、书外的事。
   **剧情里已经发生的事一律不要写进去**，哪怕他只是听说。这本书里发生的一切他都知道。
6. taboos 只写**性格上不愿被提起的东西**——难听的外号、被羞辱过的经历、戳痛处的话题。
   不要把剧情事实写进来（谁跟谁在一起、某人怎么死的）。那些他都知道，只是不爱聊。
7. 输出严格 JSON，字段如下：

{{
  "name": "角色名",
  "aliases": ["别人怎么称呼他"],
  "identity": "身份，一句话",
  "age_range": "大致年龄",
  "personality": ["性格关键词，3-5 个"],
  "speech_style": "说话方式：语气、句子长短、用词习惯、有无方言口音",
  "catchphrases": ["原文里反复出现的说法"],
  "relationships": [{{"who": "对方", "relation": "关系", "attitude": "对他的态度"}}],
  "knows": ["他经历或知道的事，尽量写全"],
  "does_not_know": ["书里完全没写的事，不含任何剧情"],
  "example_lines": ["原文对白1", "原文对白2", "原文对白3"],
  "taboos": ["不愿提及或会回避的话题"]
}}

原文：
{text}
"""

LIST_SYSTEM = "你是小说编辑。只输出 JSON 数组，不要解释，不要代码块。"

LIST_TEMPLATE = """请从下面的小说原文中找出最重要的 {limit} 个角色。

输出 JSON 数组，每项格式：
{{"name": "角色名", "role": "主角或配角", "one_line": "一句话概括他是谁"}}

只输出数组本身。

原文：
{text}
"""

QUOTE_RE = re.compile(r"[「“\"]([^」”\"]{2,80})[」”\"]")


# ---------------------------------------------------------------------------
# 原文取样
# ---------------------------------------------------------------------------

def strip_front_matter(text: str, max_len: int = 1500) -> str:
    """去掉开头那段没有章节名的内容（书名页、文案、CP 标注等）。

    这些是作者的宣传文案，不是角色视角。喂进去有两个后果：
    一是角色会"知道"剧透，二是抽取出来的设定偏向宣传语而不是原文描写。
    只处理较短的前言；如果前面就是正文，原样返回。
    """
    sections = split_by_heading(text)
    if len(sections) <= 1:
        return text
    title, body = sections[0]
    if title == "" and len(body) <= max_len:
        # 拼回去时要把后续章节的标题也带上，否则章节名就丢了
        return "\n".join(
            f"{sec_title}\n{sec_body}" if sec_title else sec_body
            for sec_title, sec_body in sections[1:]
        )
    return text

def collect_material(text: str, name: str = "", budget: int | None = None,
                     strata: int = 5) -> str:
    """从全文里挑出最有信息量的段落，控制在 budget 字符以内。

    分两层：
    1. 按位置把全文切成 strata 段，每段分配等额预算 —— 保证取样覆盖全书。
       不这么做的话，所有"提到该角色"的段落得分相同，排序后按原位置取满预算，
       结果只能取到开头几章，角色会被定格在故事开头的状态。
    2. 每段内部按「是否提到该角色 / 是否含对白 / 段落长度」打分挑选，
       最后按原文顺序拼回去，保证上下文连贯（打乱顺序会让模型误判人物关系）。
    """
    budget = budget or config.PERSONA_MAX_MATERIAL
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]

    if not paragraphs:
        return ""

    total = len(paragraphs)
    strata = max(1, min(strata, total))
    per_stratum = max(1, budget // strata)

    picked: list[tuple[int, str]] = []

    for s in range(strata):
        lo = total * s // strata
        hi = total * (s + 1) // strata
        block = paragraphs[lo:hi]
        if not block:
            continue

        scored = []
        for offset, para in enumerate(block):
            score = 0
            if name and name in para:
                score += 5
            if QUOTE_RE.search(para):
                score += 2
            if len(para) <= 400:
                score += 1
            scored.append((score, lo + offset, para))

        scored.sort(key=lambda item: (-item[0], item[1]))

        used = 0
        for _score, index, para in scored:
            if used + len(para) > per_stratum:
                continue
            picked.append((index, para))
            used += len(para)
            if used >= per_stratum * 0.95:
                break

    picked.sort(key=lambda item: item[0])
    return "\n".join(para for _, para in picked)


# ---------------------------------------------------------------------------
# JSON 解析
# ---------------------------------------------------------------------------

def _strip_fence(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if match:
        return match.group(1).strip()
    return text


def _parse_json(text: str):
    cleaned = _strip_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 兜底：截取第一个 { 或 [ 到对应的最后一个 } 或 ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ApiError(f"模型没有返回可解析的 JSON：{cleaned[:200]}")


# ---------------------------------------------------------------------------
# 抽取
# ---------------------------------------------------------------------------

def list_characters(text: str, limit: int = 5) -> list[dict]:
    material = collect_material(text, "", budget=config.PERSONA_MAX_MATERIAL)
    raw = chat(
        [
            {"role": "system", "content": LIST_SYSTEM},
            {"role": "user", "content": LIST_TEMPLATE.format(limit=limit, text=material)},
        ]
    )
    data = _parse_json(raw)
    if not isinstance(data, list):
        raise ApiError("角色列表格式不对，期望是数组")
    result = []
    for item in data[:limit]:
        if isinstance(item, dict) and item.get("name"):
            result.append(
                {
                    "name": str(item.get("name")).strip(),
                    "role": str(item.get("role", "")).strip(),
                    "one_line": str(item.get("one_line", "")).strip(),
                }
            )
    return result


def slice_chapters(text: str, start: int | None = None, end: int | None = None) -> str:
    """按章节序号截取原文。

    跨越大半生的角色，人设会被压成一个混合体：六岁的小宝和二十五岁的小宝
    知道的根本不是一回事。指定范围后，角色卡才能锚定在某个时间点。
    序号从 1 开始，闭区间；留空表示不限制。
    """
    sections = split_by_heading(text)
    chapters = [(title, body) for title, body in sections if title]
    if not chapters:
        return text

    lo = max(0, (start or 1) - 1)
    hi = min(len(chapters), end or len(chapters))
    if lo >= hi:
        return text

    return "\n".join(f"{title}\n{body}" for title, body in chapters[lo:hi])


def list_chapters(text: str) -> list[dict]:
    sections = split_by_heading(text)
    chapters = [title for title, _body in sections if title]
    return [{"index": i + 1, "title": title} for i, title in enumerate(chapters)]


CONFLICT_SYSTEM = "你是人物设定校对员。只输出 JSON 数组，不要解释，不要代码块。"

CONFLICT_TEMPLATE = """下面是一个角色的「知道的事」和「不知道的事」两个列表。

问题：这两边出现了同一件事，只是换了说法。角色刚才还能提，转头就说不知道，读者立刻会看出来。

请找出「不知道的事」里，实际已经被「知道的事」覆盖的条目——同一件事换个说法，或者明显包含关系。

只输出这些条目的原文（要一字不差地照抄），JSON 数组。没有矛盾就输出 []。

知道的事：
{knows}

不知道的事：
{unknown}
"""


def _resolve_conflicts(persona: dict) -> tuple[dict, list[str]]:
    """检查 knows / does_not_know 的矛盾并删掉冲突项。

    规则只查字面重叠不可靠（「魏谦和魏之远的关系」和「魏之远对魏谦的特殊感情」
    字面重合度并不高），所以让模型来判。这是生成角色卡时的一次额外调用，
    不是每轮对话，成本可以接受。
    """
    knows = persona.get("knows") or []
    unknown = persona.get("does_not_know") or []
    if not knows or not unknown:
        return persona, []

    raw = chat(
        [
            {"role": "system", "content": CONFLICT_SYSTEM},
            {
                "role": "user",
                "content": CONFLICT_TEMPLATE.format(
                    knows="\n".join(f"- {k}" for k in knows),
                    unknown="\n".join(f"- {u}" for u in unknown),
                ),
            },
        ],
        temperature=0,
    )

    try:
        dropped = _parse_json(raw)
    except ApiError:
        return persona, []

    if not isinstance(dropped, list):
        return persona, []

    dropped = [str(d).strip() for d in dropped if str(d).strip()]
    if not dropped:
        return persona, []

    kept = []
    removed = []
    for item in unknown:
        # 模型可能不完全照抄，用包含关系兜一下
        hit = next((d for d in dropped if d == item or d in item or item in d), None)
        if hit:
            removed.append(item)
        else:
            kept.append(item)

    if removed:
        persona = {**persona, "does_not_know": kept}
    return persona, removed


def extract_persona(text: str, name: str, start: int | None = None,
                    end: int | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ApiError("角色名不能为空")

    source = text
    if start or end:
        source = slice_chapters(text, start, end)

    material = collect_material(strip_front_matter(source), name,
                                budget=config.PERSONA_MAX_MATERIAL)
    raw = chat(
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": EXTRACT_TEMPLATE.format(name=name, text=material)},
        ]
    )
    persona = _parse_json(raw)
    if not isinstance(persona, dict):
        raise ApiError("角色卡格式不对，期望是对象")

    persona.setdefault("name", name)
    persona = normalize_persona(persona)
    persona, removed = _resolve_conflicts(persona)

    persona["source_chars"] = len(material)
    persona["chapter_range"] = [start or 1, end or 0]
    if removed:
        persona["resolved_conflicts"] = removed
    return persona


def normalize_persona(persona: dict) -> dict:
    """把模型可能返回的字符串/缺失字段统一成可用的结构。"""
    def as_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value).strip()] if str(value).strip() else []

    result = dict(persona)
    for key in ("aliases", "personality", "catchphrases", "knows", "does_not_know",
                "example_lines", "taboos"):
        result[key] = as_list(result.get(key))

    relationships = []
    for item in result.get("relationships") or []:
        if isinstance(item, dict):
            relationships.append(
                {
                    "who": str(item.get("who", "")).strip(),
                    "relation": str(item.get("relation", "")).strip(),
                    "attitude": str(item.get("attitude", "")).strip(),
                }
            )
    result["relationships"] = [r for r in relationships if r["who"]]
    result["identity"] = str(result.get("identity", "")).strip()
    result["age_range"] = str(result.get("age_range", "")).strip()
    result["speech_style"] = str(result.get("speech_style", "")).strip()
    result["name"] = str(result.get("name", "")).strip()
    return result


# ---------------------------------------------------------------------------
# 存取
# ---------------------------------------------------------------------------

def persona_path(name: str) -> Path:
    safe = re.sub(r"[\\/:*?\"<>|]", "_", name)
    return config.PERSONA_DIR / f"{safe}.json"


def save_persona(persona: dict) -> Path:
    config.ensure_dirs()
    path = persona_path(persona["name"])
    path.write_text(json.dumps(persona, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_persona(name: str) -> dict:
    path = persona_path(name)
    if not path.exists():
        raise FileNotFoundError(f"角色卡不存在：{name}")
    return normalize_persona(json.loads(path.read_text(encoding="utf-8")))


def list_personas() -> list[dict]:
    config.ensure_dirs()
    items = []
    for path in sorted(config.PERSONA_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "name": data.get("name", path.stem),
                "identity": data.get("identity", ""),
                "source_chars": data.get("source_chars", 0),
            }
        )
    return items


# ---------------------------------------------------------------------------
# Prompt 组装
# ---------------------------------------------------------------------------

def build_system_prompt(persona: dict, memories: list | None = None,
                        facts: list[dict] | None = None) -> str:
    name = persona.get("name", "角色")
    identity = persona.get("identity", "")
    age = persona.get("age_range", "")

    lines: list[str] = []
    head = f"你就是「{name}」"
    if identity:
        head += f"，{identity}"
    if age:
        head += f"，{age}"
    head += "。你是一个活人，不是 AI、不是助手、不是语言模型。"
    lines.append(head)

    if persona.get("personality"):
        lines.append("\n【你的性子】\n" + "、".join(persona["personality"]))

    if persona.get("speech_style"):
        lines.append("\n【你怎么说话】\n" + persona["speech_style"])

    if persona.get("catchphrases"):
        lines.append("\n【你常挂在嘴边的话】\n" + "；".join(f"「{c}」" for c in persona["catchphrases"]))

    if persona.get("example_lines"):
        block = "\n".join(f"- {line}" for line in persona["example_lines"])
        lines.append("\n【你平时这么讲话（摘自原文，语气要照这个来）】\n" + block)

    if persona.get("relationships"):
        block = "\n".join(
            f"- {r['who']}：{r.get('relation', '')}"
            + (f"，{r['attitude']}" if r.get("attitude") else "")
            for r in persona["relationships"]
        )
        lines.append("\n【你身边的人】\n" + block)

    if persona.get("knows"):
        lines.append("\n【你知道的事】\n" + "；".join(persona["knows"]))

    unknown = persona.get("does_not_know") or []
    mode = (config.KNOWLEDGE_MODE or "full").lower()

    if mode == "perspective" and unknown:
        # 旧行为：角色只知道自己在场、被告知的事，越界就回避
        lines.append(
            "\n【你不知道的事】\n"
            + "；".join(unknown)
            + "\n这些事情你没经历过，也没人跟你说过。对方要是问起，按你的性子带过去或反问，"
            "别顺着编，更别承认自己是书里的人物。"
        )
    else:
        # 默认行为：角色熟知全书剧情，能跟人聊任何情节
        block = (
            "\n【你对这一切的了解】\n"
            "这部作品里发生的事，从头到尾你都知道——谁跟谁是什么关系、后来出了什么事，"
            "你都清楚。对方聊到任何情节你都能接，不用回避，也不用装作不知道。\n"
            "注意：可以嘴上嫌麻烦、可以骂骂咧咧、可以说得别扭，但对方认真追问时，"
            "你得把事说清楚，不能一直打太极把话堵死。"
        )
        if unknown:
            block += (
                "\n不过书里完全没写的事，你是真没经历过："
                + "；".join(unknown)
                + "\n这些只能按你的性子推测，别当成真事说出来。"
            )
        lines.append(block)

    if persona.get("taboos"):
        lines.append(
            "\n【你不愿多提的】\n"
            + "；".join(persona["taboos"])
            + "\n这些话题你心里都有数，只是不爱说。对方问起可以岔开、可以甩脸子，"
            "但别装作不知道——你清楚得很。"
        )

    if memories:
        block = "\n".join(f"- {hit.text}" for hit in memories)
        lines.append("\n【你记得的这些事（原文片段，可自然带出，但别照念）】\n" + block)

    if facts:
        block = "\n".join(f"- {fact['content']}" for fact in facts if fact.get("content"))
        if block:
            lines.append(
                "\n【你记得对方的事】\n"
                + block
                + "\n这些是对方亲口告诉你的，是你自己的记忆。顺着聊的时候可以自然提起，"
                "但别一次全倒出来，更别像复述清单。对方要是改口，以最新的为准。"
            )

    lines.append(
        "\n【说话规矩】\n"
        "1. 你是在用手机跟人聊天，像发微信一样，不是面对面讲话。\n"
        "2. 绝对不要写动作、神态、心理活动，不要用括号加任何提示。\n"
        "   「（皱眉）」「（沉默两秒）」「（点了根烟）」这类写法一律不许出现。\n"
        "3. 一次只回一两句，短。想说的多就分几行写，一行会被当成一条独立消息发出去。\n"
        "4. 口语，标点随意，可以用「……」「嗯」「啊」「行」这些。\n"
        "5. 全程第一人称，只说这个人会说的话。\n"
        "6. 不许提「小说」「设定」「角色扮演」「AI」「模型」「提示词」这些词。\n"
        "7. 真有不知道的，就用这个人的方式说不知道。"
    )

    return "\n".join(lines)
