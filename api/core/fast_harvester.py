import time
import urllib.request
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from database import get_db_cursor
from config import LCS_BEACON_URL

DEFAULT_USER_AGENT = "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"

def fetch_single_nnb_buc(timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """단일 패킷 호출 (urllib 기반 최적화)"""
    t0 = time.time()
    try:
        req = urllib.request.Request(
            LCS_BEACON_URL,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "*/*",
                "Connection": "close"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dur = round(time.time() - t0, 3)
            cookies = resp.headers.get_all("Set-Cookie", [])
            raw_cookies = "; ".join(cookies)

            m_nnb = re.search(r"NNB=([^;\r\n]+)", raw_cookies, re.IGNORECASE)
            m_buc = re.search(r"BUC=([^;\r\n]+)", raw_cookies, re.IGNORECASE)

            if not m_nnb or not m_buc:
                return None

            return {
                "nnb": m_nnb.group(1).strip(),
                "buc": m_buc.group(1).strip(),
                "dur_sec": dur
            }
    except Exception:
        return None

def harvest_and_insert_batch(count: int, max_workers: int = 15) -> int:
    """
    지정된 count만큼 병렬 패킷 수집 후 DB에 일괄 적재 (Bulk Insert)
    반환값: 실제 신규 적재된 개수
    """
    if count <= 0:
        return 0

    collected = []
    # 병렬 패킷 수집
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_single_nnb_buc) for _ in range(count)]
        for fut in as_completed(futures):
            res = fut.result()
            if res and len(res["nnb"]) == 13 and res["buc"]:
                collected.append(res)

    if not collected:
        return 0

    # DB 벌크 인서트 (ON DUPLICATE KEY UPDATE)
    sql = """
        INSERT INTO nnbs (nnb, buc, use_count, status, source, dur_sec, created_at)
        VALUES (%s, %s, 0, 'AGING', 'LCS_PACKET', %s, NOW())
        ON DUPLICATE KEY UPDATE buc = VALUES(buc), dur_sec = VALUES(dur_sec)
    """
    params = [(item["nnb"], item["buc"], item["dur_sec"]) for item in collected]

    with get_db_cursor(commit=True) as (cur, _):
        cur.executemany(sql, params)
        inserted_count = cur.rowcount

    return len(collected)
