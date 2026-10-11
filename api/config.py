import os
from pathlib import Path

# .env 파일 파싱
ENV_PATH = Path(__file__).resolve().parent / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

# 데이터베이스 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "nshop"),
    "password": os.getenv("DB_PASSWORD", "Tech1324"),
    "database": os.getenv("DB_NAME", "nshop_api_v1"),
    "charset": "utf8mb4",
    "autocommit": False
}

# 네이버 NNB 패킷 및 풀 정책 설정
LCS_BEACON_URL = os.getenv("LCS_BEACON_URL", "https://lcs.naver.com/m")
IP_CHECK_URL = os.getenv("IP_CHECK_URL", "https://api.ipify.org")
MIN_AGING_SECONDS = int(os.getenv("MIN_AGING_SECONDS", 1200)) # 기본 1200초 (20분) 숙성 기준
TARGET_FRESH_POOL = int(os.getenv("TARGET_FRESH_POOL", 3000)) # 1200초 미만 신규 숙성 토큰 항시 유지 목표치 (3000개)
TARGET_ZERO_USE_POOL = TARGET_FRESH_POOL # 하위 호환 별칭
TARGET_NNB_POOL_SIZE = TARGET_FRESH_POOL # 하위 호환 별칭
CHECK_INTERVAL_SECONDS = float(os.getenv("CHECK_INTERVAL_SECONDS", 1.0)) # 초 단위 감시 주기 (1초)
API_PORT = int(os.getenv("API_PORT", 8000))
