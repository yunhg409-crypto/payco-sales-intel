import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
# Render 배포 시 /data 마운트 경로 사용, 로컬은 기존 경로
_default_db = "/data/payco.db" if os.path.isdir("/data") else str(BASE_DIR / "data" / "payco.db")
DB_PATH = os.getenv("DB_PATH", _default_db)

# Naver API
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "").strip()
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "").strip()

# LLM
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "claude")  # "claude" | "openai"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Feature flags
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

def has_llm() -> bool:
    if GEMINI_API_KEY:
        return True
    if LLM_PROVIDER == "claude":
        return bool(ANTHROPIC_API_KEY)
    return bool(OPENAI_API_KEY)

def has_naver() -> bool:
    return bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)

# Excel parsing constants
EXCEL_SHEET_NAME = "리스트(20260127)"
MERCHANT_COL = "가맹점명"
CATEGORY_COL = "카테고리"
INDUSTRY_COL = "업종"
MANAGER_COL = "담당자"
CHANNEL_COL = "채널"
PROMO_COL = "프로모션 진행"
TYPE_COL = "기존/신규"

# 가맹점 통합 매핑: {원본명: 통합명}
# 동일 가맹점이 여러 이름으로 등록된 경우 하나로 묶음
MERCHANT_ALIASES: dict[str, str] = {
    "예스24(문화비)": "예스24(통합)",
    "예스24":         "예스24(통합)",
}

# Dashboard
DEFAULT_MONTHS = 12
MOM_THRESHOLD = 0.10  # 10% — AI 가설 트리거
MIN_BENCHMARK_COUNT = 3  # 카테고리 내 최소 가맹점 수
NEWS_CACHE_HOURS = 24
NEWS_DISPLAY_COUNT = 5
