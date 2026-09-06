import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("CATALOG_DB_PATH", str(BASE_DIR / "interior_company_catalog.db"))

# Vercel AI Gateway — an OpenAI-Chat-Completions-compatible endpoint that
# proxies to hundreds of models (including non-Anthropic ones) behind one
# key. Model IDs are "provider/model-name", e.g. "zai/glm-5.3-flash".
AI_GATEWAY_API_KEY = os.getenv("AI_GATEWAY_API_KEY")
AI_GATEWAY_BASE_URL = os.getenv("AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1")
AGENT_MODEL = os.getenv("AGENT_MODEL", "zai/glm-5.3-flash")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "zai/glm-5.3-flash")

# Layout heuristic tunables (see tools/layout_fit_check.py)
MAX_FURNITURE_COVERAGE = float(os.getenv("MAX_FURNITURE_COVERAGE", "0.55"))
MIN_CLEARANCE_CM = int(os.getenv("MIN_CLEARANCE_CM", "75"))
MIN_CEILING_CLEARANCE_CM = int(os.getenv("MIN_CEILING_CLEARANCE_CM", "20"))
