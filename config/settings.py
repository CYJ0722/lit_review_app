"""
项目配置：所有路径与开关均通过环境变量或配置文件设置，禁止硬编码绝对路径。

环境变量：
  LIT_PROJECT_ROOT     - 项目根目录（默认：当前文件向上两级）
  LIT_SOURCE_ROOTS     - 文献 PDF 根目录，多个用分号 ; 分隔（如 第二批文献收集;2023-2025_extracted）
  LIT_DB_PATH          - SQLite 数据库路径（默认：<PROJECT_ROOT>/data/papers.db）
  LIT_OUT_DIR          - 解析输出目录（默认：<PROJECT_ROOT>/data/out）
  LIT_EMBEDDINGS_DIR   - 向量存储目录（默认：<PROJECT_ROOT>/data/embeddings）
  HF_ENDPOINT          - Hugging Face 镜像（未设置时默认用国内镜像，避免连接超时）
"""
import os
from pathlib import Path

# 国内访问 Hugging Face 易超时，默认使用镜像（用户可通过环境变量覆盖）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 项目根：优先环境变量，否则为 lit_review_app 的上级目录
_def_root = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.environ.get("LIT_PROJECT_ROOT", _def_root))

def _roots_from_env():
    raw = os.environ.get("LIT_SOURCE_ROOTS", "").strip()
    if not raw:
        # 默认：第二批文献收集 + 2023-2025（解压后文件仍在该目录下）
        roots = [
            PROJECT_ROOT / "第二批文献收集",
            PROJECT_ROOT / "2023-2025",
        ]
        return [r for r in roots if r.exists()]
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    out = []
    for p in parts:
        path = Path(p)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            out.append(path)
    return out

# 文献来源根目录列表（可多级嵌套，脚本会 rglob *.pdf）
LIT_SOURCE_ROOTS = _roots_from_env()

# 数据库与输出目录（均相对于 PROJECT_ROOT 若为相对路径）
_def_db = PROJECT_ROOT / "data" / "papers.db"
LIT_DB_PATH = os.environ.get("LIT_DB_PATH", str(_def_db))
if not os.path.isabs(LIT_DB_PATH):
    LIT_DB_PATH = str(PROJECT_ROOT / LIT_DB_PATH)

_def_out = PROJECT_ROOT / "data" / "out"
LIT_OUT_DIR = os.environ.get("LIT_OUT_DIR", str(_def_out))
if not os.path.isabs(LIT_OUT_DIR):
    LIT_OUT_DIR = str(PROJECT_ROOT / LIT_OUT_DIR)

_def_emb = PROJECT_ROOT / "data" / "embeddings"
LIT_EMBEDDINGS_DIR = os.environ.get("LIT_EMBEDDINGS_DIR", str(_def_emb))
if not os.path.isabs(LIT_EMBEDDINGS_DIR):
    LIT_EMBEDDINGS_DIR = str(PROJECT_ROOT / LIT_EMBEDDINGS_DIR)

# Elasticsearch（BM25 关键词检索）
ES_HOST = os.environ.get("ES_HOST", "http://localhost:9200")
ES_INDEX = os.environ.get("ES_INDEX", "lit_review_papers")

# 向量检索（sentence-transformers + FAISS）
# EMBED_MODEL 可为：Hugging Face 模型名（如 sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2）
# 或本地目录绝对路径（如 E:/models/paraphrase-multilingual-MiniLM-L12-v2），详见 docs/本地模型部署说明.md
EMBED_MODEL = os.environ.get("EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

# 大模型：智谱 GLM-4-Flash（OpenAI 兼容）
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # 填智谱 API Key
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "glm-4.7-flash")


def get_device() -> str:
    """返回推理设备：有 NVIDIA GPU 时用 cuda，否则 cpu。可通过环境变量 LIT_DEVICE 覆盖（如强制 cpu）。"""
    override = os.environ.get("LIT_DEVICE", "").strip().lower()
    if override in ("cuda", "cpu"):
        return override
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"
