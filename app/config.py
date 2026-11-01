"""配置读取。

不引入 python-dotenv：自己解析 .env 十几行就够，少一个依赖，离线也能跑。
"""

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


INLINE_COMMENT_RE = re.compile(r"\s+#.*$")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        # 去掉行尾注释：只在 # 前面有空白时才当注释，避免误伤 URL 里的 #
        value = INLINE_COMMENT_RE.sub("", value).strip()
        value = value.strip('"').strip("'")
        # 已存在的环境变量优先，方便在命令行临时覆盖
        os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _path(name: str, default: str) -> Path:
    raw = os.environ.get(name, default)
    path = Path(raw)
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


# ---------- 向量化 ----------
EMBED_API_URL = _str("EMBED_API_URL", "https://api.siliconflow.cn/v1/embeddings")
EMBED_API_KEY = _str("EMBED_API_KEY")
EMBED_MODEL = _str("EMBED_MODEL", "BAAI/bge-m3")
EMBED_BATCH = _int("EMBED_BATCH", 16)
# auto: 有 key 就用接口，没 key 自动退化为本地 bigram 哈希向量
EMBED_BACKEND = _str("EMBED_BACKEND", "auto")

# ---------- 对话 ----------
CHAT_API_URL = _str("CHAT_API_URL", "https://api.deepseek.com/v1/chat/completions")
CHAT_API_KEY = _str("CHAT_API_KEY")
CHAT_MODEL = _str("CHAT_MODEL", "deepseek-chat")
CHAT_TEMPERATURE = _float("CHAT_TEMPERATURE", 0.1)

# ---------- 检索 ----------
CHUNK_SIZE = _int("CHUNK_SIZE", 512)
CHUNK_OVERLAP = _int("CHUNK_OVERLAP", 64)
TOP_K = _int("TOP_K", 4)

# ---------- 角色扮演 ----------
PERSONA_MAX_MATERIAL = _int("PERSONA_MAX_MATERIAL", 12000)  # 抽取角色卡时喂给模型的原文上限
HISTORY_TURNS = _int("HISTORY_TURNS", 8)                     # 对话保留的最近轮数
MEMORY_TOP_K = _int("MEMORY_TOP_K", 3)                     # 每轮检索的「记忆」条数
MEMORY_MAX_FACTS = _int("MEMORY_MAX_FACTS", 50)           # 长期记忆最多存多少条
MEMORY_MAX_INJECT = _int("MEMORY_MAX_INJECT", 15)        # 每次注入 prompt 多少条
MEMORY_EXTRACT = _str("MEMORY_EXTRACT", "1").lower() not in ("0", "false", "no")

# full：角色知道全书发生的事；perspective：只知道自己在场的事
KNOWLEDGE_MODE = _str("KNOWLEDGE_MODE", "full")

# ---------- 路径 ----------
DATA_DIR = _path("DATA_DIR", "./data")
UPLOAD_DIR = DATA_DIR / "uploads"
PERSONA_DIR = DATA_DIR / "personas"
MEMORY_DIR = DATA_DIR / "memory"
SESSION_DIR = DATA_DIR / "sessions"
CHROMA_DIR = _path("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = _str("COLLECTION_NAME", "rag_docs")

WEB_DIR = BASE_DIR / "web"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    PERSONA_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
