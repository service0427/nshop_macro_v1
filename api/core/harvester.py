import re
import time
import urllib.request
from typing import Optional, Dict, Any
from config import LCS_BEACON_URL, IP_CHECK_URL

DEFAULT_USER_AGENT = "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"

def get_public_ip(timeout: float = 3.0) -> str:
    """현재 공인 IP 확인"""
    try:
        req = urllib.request.Request(IP_CHECK_URL, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return "UNKNOWN"

def harvest_single_packet(
    proxy: Optional[str] = None,
    user_agent: Optional[str] = None,
    timeout: float = 5.0
) -> Optional[Dict[str, Any]]:
    """
    lcs.naver.com/m 초경량 패킷 호출 (0.05~0.2초)
    네이버 정품 13자리 NNB 및 BUC 쿠키를 실시간 추출
    """
    t0 = time.time()
    try:
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
        opener = urllib.request.build_opener(*handlers)

        req = urllib.request.Request(
            LCS_BEACON_URL,
            headers={
                "User-Agent": user_agent or DEFAULT_USER_AGENT,
                "Accept": "*/*",
                "Connection": "close"
            }
        )

        with opener.open(req, timeout=timeout) as resp:
            dur = round(time.time() - t0, 3)
            # Set-Cookie 헤더 파싱
            cookies = resp.headers.get_all("Set-Cookie", [])
            raw_cookies = "; ".join(cookies)

            m_nnb = re.search(r"NNB=([^;\r\n]+)", raw_cookies, re.IGNORECASE)
            m_buc = re.search(r"BUC=([^;\r\n]+)", raw_cookies, re.IGNORECASE)

            if not m_nnb:
                return None

            nnb = m_nnb.group(1).strip()
            buc = m_buc.group(1).strip() if m_buc else ""

            return {
                "nnb": nnb,
                "buc": buc,
                "dur_sec": dur,
                "source": "LCS_PACKET"
            }
    except Exception as e:
        return None
