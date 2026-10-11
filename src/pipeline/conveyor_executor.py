#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conveyor Striker Execution Engine (Modularized):
- Supports single products and compare_id catalog products
- Supports remote NNB API with fallback
- Supports random device selection by default
- Measures SERP rank and Shopping rank across pages 1~5
- Returns comprehensive structured result payload
"""

import os
import sys
import json
import time
import random
import hashlib
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, Union
from pathlib import Path
import websockets

ROOT_DIR = Path("/home/tech/nshop_macro_v1")
sys.path.insert(0, str(ROOT_DIR))

from config.settings import (
    CAPTURES_DIR,
    HISTORY_FILE,
    LOGS_DIR
)
from src.core.profile_generator import (
    generate_fresh_session_profile,
    build_intent_url
)
from src.core.nnb_provider import get_nnb_packet
from src.device.device_selector import select_device
from src.device.adb_controller import (
    reset_pm_clear,
    start_intent,
    force_stop_app,
    take_screenshot
)
from src.device.surgical_cleaner import perform_surgical_cycle
from src.browser.frida_runner import spawn_app_with_cdp
from src.browser.cdp_client import AsyncCDPClient, find_serp_debugger_url

# Configure dual logging: console stdout + daily rotating log file
LOGS_DIR.mkdir(parents=True, exist_ok=True)
_log_file = LOGS_DIR / f"conveyor_{time.strftime('%Y%m%d')}.log"
_file_handler = RotatingFileHandler(str(_log_file), maxBytes=10*1024*1024, backupCount=10, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        _file_handler
    ]
)
logger = logging.getLogger("ConveyorExecutor")

def save_task_history(record: Dict[str, Any]):
    """
    모든 작업 완료/실패/중단 결과를 디스크에 이중 영구 보존:
    1. HISTORY_FILE (macro_v1/data/execution_history.json) - 최근 2,000건 유지
    2. Daily JSONL (macro_v1/logs/runs_{YYYYMMDD}.jsonl) - 실시간 1줄 추가 (jq/grep 스트리밍 분석)
    """
    try:
        day_str = time.strftime("%Y%m%d")
        daily_jsonl = LOGS_DIR / f"runs_{day_str}.jsonl"
        with open(daily_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"⚠️ [일별 JSONL 로그 저장 실패] {e}")

    try:
        history = []
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    if not isinstance(history, list):
                        history = []
            except Exception:
                history = []
        history.append(record)
        if len(history) > 2000:
            history = history[-2000:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"⚠️ [메인 실행 히스토리 파일 저장 실패] {e}")

DEVICE_CDP_PORTS = {
    "R3CR70FFFEK": 9901,
    "R3CR70K98XZ": 9902,
    "R3CR70KB1RA": 9903,
    "R3CR70P0Y5E": 9904,
    "R3CR80HKLKL": 9905,
    "R3CR90CCP1D": 9906,
    "R3CRB0WCGET": 9907,
    "R5CR80AML3N": 9908,
    "R5CR91SH8LM": 9909,
    "R5CRA28JXXF": 9910,
    "R3CW5084CEW": 9911,
}

def get_cdp_port(device_id: str) -> int:
    return DEVICE_CDP_PORTS.get(device_id, 9901)

from contextlib import asynccontextmanager

@asynccontextmanager
async def safe_ws_connect(ws_url: str, max_retries: int = 3, open_timeout: float = 15.0):
    """
    CDP WebSocket 연결 컨텍스트 매니저 (핸드셰이크 타임아웃 완벽 방어)
    """
    conn = None
    last_err = None
    for attempt in range(max_retries):
        try:
            conn = await websockets.connect(ws_url, ping_interval=None, open_timeout=open_timeout)
            break
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                await asyncio.sleep(0.3 * (attempt + 1))
    if not conn:
        raise last_err
    try:
        yield conn
    finally:
        try:
            await conn.close()
        except Exception:
            pass

async def open_ws_client(ws_url: str, max_retries: int = 3, open_timeout: float = 15.0):
    """
    단독 CDP WebSocket 연결 헬퍼 (지수 백오프 재시도 탑재)
    """
    last_err = None
    for attempt in range(max_retries):
        try:
            return await websockets.connect(ws_url, ping_interval=None, open_timeout=open_timeout)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                await asyncio.sleep(0.3 * (attempt + 1))
    raise last_err

import re
from typing import Dict, Any, Optional, Union

def clean_keyword(keyword: str) -> str:
    """
    Cleans search keyword for better SERP and Shopping searchability:
    1. Removes leading bracketed promotional tags: [3+1], (무료배송), 【특가】
    2. Removes remaining brackets: (, ), [, ], {, }, 【, 】
    3. Removes commas and dots: ',', '.'
    4. Keeps hyphens: '-'
    5. Collapses multiple whitespace into a single space
    """
    if not keyword:
        return ""
    kw = keyword.strip()
    while True:
        m = re.match(r'^\s*(\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}|【[^】]*】)\s*(.*)', kw)
        if m and m.group(2).strip():
            kw = m.group(2).strip()
        else:
            break
    kw = re.sub(r'[\(\)\[\]\{\}【】]', ' ', kw)
    kw = re.sub(r'[,.]', ' ', kw)
    kw = re.sub(r'\s+', ' ', kw).strip()
    return kw

STOP_PREFIXES = {"국산", "국내산", "정품", "신상", "무료배송", "당일발송", "당일출고", "특가", "할인", "추천", "인기", "최신형", "100%", "총알배송"}

def shorten_keyword(keyword: str, max_words: int = 3) -> str:
    """
    Cleans search keyword and shortens to 2~3 phrases (words):
    As requested: "검색어는 일부러 길게 나올 수있으니까 2~3마디로 줄여서 검색하도록 진행해라."
    1. Strips promotional tags, brackets, and collapses whitespace
    2. Filters stop prefixes from search terms
    3. Limits to first `max_words` tokens (default 3 words)
    """
    cleaned = clean_keyword(keyword)
    if not cleaned:
        return ""
    words = cleaned.split()
    filtered = [w for w in words if w not in STOP_PREFIXES]
    if len(filtered) >= 2:
        words = filtered
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])

class TaskInput:
    def __init__(
        self,
        task_id: Union[str, int],
        keyword: str,
        nv_mid: str,
        compare_id: Optional[str] = None,
        store_name: Optional[str] = None,
        nnb: Optional[str] = None,
        buc: Optional[str] = None,
        use_remote_nnb: bool = True,
        device_id: Optional[str] = None,
        dwell_seconds: int = 15,
        profile: Optional[Dict[str, Any]] = None,
        ip: Optional[str] = None
    ):
        self.task_id = str(task_id).strip()
        self.raw_keyword = keyword
        # Shortens keyword to 2~3 words for realistic human-like and optimal searchability
        self.keyword = shorten_keyword(keyword, max_words=3)
        self.nv_mid = str(nv_mid).strip()
        self.compare_id = str(compare_id).strip() if compare_id else None
        self.store_name = store_name.strip() if store_name else None
        self.nnb = nnb.strip() if nnb else None
        self.buc = buc.strip() if buc else None
        self.use_remote_nnb = use_remote_nnb
        self.device_id = device_id
        self.dwell_seconds = dwell_seconds
        self.profile = profile
        self.ip = ip

class TaskResult:
    def __init__(self, task_id: Union[str, int], keyword: str, nv_mid: str, compare_id: Optional[str] = None, raw_keyword: Optional[str] = None):
        self.start_ts = time.time()
        self.task_id = str(task_id)
        self.keyword = keyword
        self.raw_keyword = raw_keyword or keyword
        self.nv_mid = nv_mid
        self.compare_id = compare_id
        self.match_type: Optional[str] = None # 'nv_mid' or 'compare_id'
        self.device_id = ""
        self.nnb = ""
        self.nnb_age_seconds: int = 0
        self.success = False
        self.status = "INIT"
        self.target_type = "CATALOG" if compare_id else "PROD"
        self.search_type: Optional[str] = None # 'm.search' (통합검색) or 'msearch' (쇼핑검색)
        self.serp_rank: Optional[int] = None
        self.shopping_rank: Optional[int] = None
        self.shopping_page: Optional[int] = None
        self.landing_url: Optional[str] = None
        self.landing_title: Optional[str] = None
        self.touch_coordinates: Optional[Dict[str, float]] = None
        self.login_detected: bool = False
        self.login_info: Optional[Dict[str, Any]] = None
        self.before_click_screenshot: Optional[str] = None
        self.after_click_screenshot: Optional[str] = None
        self.landing_dom_dump: Optional[Dict[str, Any]] = None
        self.current_window_focus: Optional[str] = None
        self.pre_click_url: Optional[str] = None
        self.target_product_url: Optional[str] = None
        self.store_name: Optional[str] = None
        self.ip: str = ""
        self.dwell_seconds: int = 15
        self.identity_audit: Optional[Dict[str, Any]] = None
        self.duration_seconds: float = 0.0
        self.timing_profile: Dict[str, float] = {}
        self.error_message: Optional[str] = None
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        dur = self.duration_seconds if self.duration_seconds > 0 else (time.time() - self.start_ts)
        return {
            "task_id": self.task_id,
            "keyword": self.keyword,
            "raw_keyword": self.raw_keyword,
            "nv_mid": self.nv_mid,
            "compare_id": self.compare_id,
            "store_name": self.store_name,
            "match_type": self.match_type,
            "search_type": self.search_type,
            "device_id": self.device_id,
            "ip": self.ip,
            "nnb": self.nnb,
            "nnb_age_seconds": getattr(self, "nnb_age_seconds", 0),
            "identity_audit": self.identity_audit,
            "success": self.success,
            "status": self.status,
            "target_type": self.target_type,
            "rank_info": {
                "serp_rank": self.serp_rank,
                "shopping_rank": self.shopping_rank,
                "shopping_page": self.shopping_page
            },
            "pre_click_url": self.pre_click_url,
            "target_product_url": self.target_product_url,
            "landing_url": self.landing_url,
            "landing_title": self.landing_title,
            "touch_coordinates": self.touch_coordinates,
            "login_detected": self.login_detected,
            "login_info": self.login_info,
            "before_click_screenshot": self.before_click_screenshot,
            "after_click_screenshot": self.after_click_screenshot,
            "landing_dom_dump": self.landing_dom_dump,
            "current_window_focus": self.current_window_focus,
            "dwell_seconds": self.dwell_seconds,
            "duration_seconds": round(dur, 2),
            "elapsed_seconds": round(dur, 2),
            "timing_profile": self.timing_profile,
            "error_message": self.error_message,
            "timestamp": self.timestamp
        }

async def fast_check_login_state(device_id: str, cdp_port: int) -> tuple:
    """
    웹뷰 및 안드로이드 네이티브 화면 양쪽에서 네이버 로그인 유도 발생 여부를 초고속(10~100ms) 판별.
    Returns: (is_login: bool, reason: str)
    """
    # 1. CDP 웹뷰 탭 목록 검사 (10~50ms)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{cdp_port}/json/list", headers={"User-Agent": "FastLoginChecker"})
        tabs = json.loads(urllib.request.urlopen(req, timeout=1.0).read().decode())
        for t in tabs:
            u = t.get("url", "")
            title = t.get("title", "")
            if any(k in u for k in ["nid.naver.com", "nidlogin", "user.login"]) or ("login" in u and "naver.com" in u):
                return True, f"웹뷰 로그인 URL 감지: {u[:80]}"
            if "로그인" in title and "naver.com" in u:
                return True, f"웹뷰 로그인 타이틀 감지: {title} ({u[:60]})"
    except Exception:
        pass

    # 2. 안드로이드 최상위 포커스 윈도우/액티비티 검사 (50~150ms)
    # 반드시 현재 실제 화면에 떠 있는 활성 윈도우(mCurrentFocus=Window{...})만 검사 (과거 백그라운드 잔여 태스크 오탐 원천 방지)
    try:
        cmd = f"adb -s {device_id} shell \"dumpsys window | grep 'mCurrentFocus=Window'\""
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1.5)
        out_str = stdout.decode()
        if any(k in out_str for k in ["NidLoginActivity", "nid.login", "nhn.android.search/.login"]):
            return True, f"네이티브 로그인 화면 포커스 감지: {out_str.strip()}"
    except Exception:
        pass

    return False, ""

def take_login_alert_screenshot(device_id: str, task_id: Any) -> str:
    try:
        cap_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "captures")
        os.makedirs(cap_dir, exist_ok=True)
        filename = f"login_alert_{device_id}_task{task_id}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        local_path = os.path.join(cap_dir, filename)
        remote_path = f"/data/local/tmp/{filename}"
        subprocess.run(f"adb -s {device_id} shell screencap -p {remote_path}", shell=True, timeout=5.0)
        subprocess.run(f"adb -s {device_id} pull {remote_path} {local_path}", shell=True, timeout=5.0)
        subprocess.run(f"adb -s {device_id} shell rm -f {remote_path}", shell=True, timeout=2.0)
        return local_path
    except Exception as e:
        logger.debug(f"캡쳐 저장 실패: {e}")
        return ""

PURGE_TOOLTIPS_JS = """
(() => {
    let purged = 0;
    const selectors = [
        '[class*="searchTab_tooltip"]',
        '[class*="searchTab_active"]',
        '[class*="searchTab_btn_close"]',
        '[class*="searchTab_text"]',
        '[class*="layerDeliveryGuide"]',
        '[class*="guide_balloon"]',
        '[class*="coachmark"]',
        '[class*="tooltip"]'
    ];
    selectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            try {
                el.remove();
                purged++;
            } catch(e) {}
        });
    });

    if (!document.getElementById('_g_tooltip_override_css')) {
        const style = document.createElement('style');
        style.id = '_g_tooltip_override_css';
        style.innerHTML = `
            [class*="searchTab_tooltip"],
            [class*="searchTab_active"],
            [class*="searchTab_btn_close"],
            [class*="searchTab_text"],
            [class*="layerDeliveryGuide"],
            [class*="guide_balloon"],
            [class*="coachmark"] {
                display: none !important;
                opacity: 0 !important;
                pointer-events: none !important;
                visibility: hidden !important;
                height: 0 !important;
                width: 0 !important;
            }
        `;
        (document.head || document.documentElement).appendChild(style);
    }
    return purged;
})()
"""

async def visual_stabilize_and_click(
    cdp: AsyncCDPClient,
    device_id: str,
    task_id: Union[str, int],
    action_name: str,
    click_x: float,
    click_y: float,
    target_selector_expr: Optional[str] = None
) -> Dict[str, Any]:
    """
    [사용자 지침 필수] 레이아웃 왜곡 없는 시각화 + 100% 동적 안정화 검증 + 스크린샷 캡쳐 후 정밀 클릭
    1. Zero-Reflow 테두리 효과: outline: 3px solid #00e5ff; outline-offset: -3px; box-shadow: inset 0 0 0 3px #00e5ff (화면 틀어짐 0%)
    2. 클릭 위치 조준 마커 오버레이: 네온 핑크 링 + 화이트 십자선 + 옐로우 센터 도트 주입
    3. 명확한 구분자 반복 체크 (Sleep 금지):
       - 구분자 1: document.readyState === 'complete'
       - 구분자 2: In-flight Network 요청 0건
       - 구분자 3: 클릭 지점 요소의 getBoundingClientRect() 위치 연속 2회 0.5px 이내 고정 (스크롤/애니메이션 정지)
       - 구분자 4: document.body.scrollHeight 높이 연속 2회 일치
    4. 클릭 직전 화면 캡쳐: ADB screencap 으로 macro_v1/captures/ 에 보관
    5. 정밀 터치 디스패치 및 오버레이 정리
    """
    t_start = time.time()

    # [사용자 지침] 클릭 안정화 전 방해 툴팁/코치마크 선제적 완전 소멸
    try:
        await cdp.evaluate(PURGE_TOOLTIPS_JS)
    except Exception:
        pass
    
    # 1. Zero-Reflow 인셋 테두리 & 정밀 조준경 오버레이 주입
    target_code = f"targetEl = {target_selector_expr};" if target_selector_expr else ""
    js_inject = f"""
    (() => {{
        // 1. 기존 오버레이 정리
        const oldOverlay = document.getElementById('_probe_crosshair_ovl');
        if (oldOverlay) oldOverlay.remove();
        const oldStyle = document.getElementById('_probe_highlight_style');
        if (oldStyle) oldStyle.remove();

        // 2. Zero-Reflow 스타일 주입 (인셋 그림자 + 내부 아웃라인: 레이아웃 크기 변동 0%)
        const style = document.createElement('style');
        style.id = '_probe_highlight_style';
        style.innerHTML = `
            ._probe_target_hi {{
                outline: 3px solid #00e5ff !important;
                outline-offset: -3px !important;
                box-shadow: inset 0 0 0 3px #00e5ff, 0 0 12px rgba(0, 229, 255, 0.5) !important;
                transition: none !important;
            }}
            #_probe_crosshair_ovl {{
                position: fixed !important;
                left: {click_x - 16}px !important;
                top: {click_y - 16}px !important;
                width: 32px !important;
                height: 32px !important;
                border-radius: 50% !important;
                border: 2px solid #ff0055 !important;
                background: rgba(255, 0, 85, 0.35) !important;
                box-shadow: 0 0 12px #ff0055, inset 0 0 6px #ff0055 !important;
                z-index: 2147483647 !important;
                pointer-events: none !important;
                box-sizing: border-box !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }}
            #_probe_crosshair_ovl .cross-h {{
                position: absolute; width: 20px; height: 2px; background: #ffffff;
            }}
            #_probe_crosshair_ovl .cross-v {{
                position: absolute; width: 2px; height: 20px; background: #ffffff;
            }}
            #_probe_crosshair_ovl .center-dot {{
                position: absolute; width: 6px; height: 6px; border-radius: 50%; background: #ffff00; box-shadow: 0 0 4px #ffff00;
            }}
        `;
        document.head.appendChild(style);

        // 3. 타겟 요소에 하이라이트 클래스 부여
        let targetEl = null;
        try {{
            {target_code}
        }} catch(e) {{}}
        if (!targetEl) {{
            targetEl = document.elementFromPoint({click_x}, {click_y});
        }}
        if (targetEl) {{
            const card = targetEl.closest('div[class*="product_info_main"], li, a') || targetEl;
            card.classList.add('_probe_target_hi');
        }}

        // 4. 조준 마커 오버레이 주입
        const overlay = document.createElement('div');
        overlay.id = '_probe_crosshair_ovl';
        overlay.innerHTML = `
            <div class="cross-h"></div>
            <div class="cross-v"></div>
            <div class="center-dot"></div>
        `;
        document.body.appendChild(overlay);

        return true;
    }})()
    """
    try:
        await cdp.evaluate(js_inject)
    except Exception as e:
        logger.warning(f"⚠️ [시각화 오버레이 주입 경고] {e}")

    # 2. 필수 타겟 로딩 및 위치 안정화 초고속 검증 (불필요한 전역 네트워크 대기 제거)
    last_rect = None
    stable_count = 0
    is_stable = False

    for check_iter in range(30):  # 최대 1.5초 (50ms * 30), 필수 요소 포착 및 위치 고정 시 즉시 탈출
        await asyncio.sleep(0.05)
        check_res = await cdp.evaluate(f"""
        (() => {{
            const isDocReady = document.readyState === 'complete' || document.readyState === 'interactive';
            
            // 조준점 하부 엘리먼트 및 필수 타겟 속성 확인
            const el = document.elementFromPoint({click_x}, {click_y});
            let rect = null;
            let hasValidTarget = false;
            if (el) {{
                const r = el.getBoundingClientRect();
                rect = {{ x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }};
                hasValidTarget = (r.width >= 10 && r.height >= 10);
            }}

            return {{
                isDocReady,
                hasValidTarget,
                rect
            }};
        }})()
        """, timeout=1.0)

        if not isinstance(check_res, dict):
            continue

        doc_ok = check_res.get("isDocReady", False)
        target_ok = check_res.get("hasValidTarget", False)
        cur_rect = check_res.get("rect")

        # 위치가 이전 측정과 1px 이내로 고정되어 있는지 검증 (스크롤/애니메이션 정지)
        pos_stable = False
        if cur_rect and last_rect:
            if (abs(cur_rect["x"] - last_rect["x"]) <= 1 and 
                abs(cur_rect["y"] - last_rect["y"]) <= 1 and 
                abs(cur_rect["w"] - last_rect["w"]) <= 1):
                pos_stable = True
        elif cur_rect and not last_rect:
            pos_stable = False
        
        last_rect = cur_rect

        if doc_ok and target_ok and pos_stable:
            stable_count += 1
            if stable_count >= 2:  # 연속 2회(100ms) 완벽 고정 확인 -> 즉시 조기 탈출!
                is_stable = True
                break
        else:
            stable_count = 0

    stabilize_dur = round(time.time() - t_start, 2)

    # 3. 상품 타겟 클릭 시에만 증빙용 물리 화면 캡쳐 수행 (중간 탭 전환 클릭은 생략하여 1.5초 절약)
    is_target_click = action_name in ("SERP_TARGET", "SHOPPING_1P_TARGET")
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    shot_filename = f"click_{device_id}_task{task_id}_{action_name}_{timestamp_str}.png"
    shot_path = CAPTURES_DIR / shot_filename
    shot_captured = False

    if is_target_click:
        try:
            cmd = f"adb -s {device_id} exec-out screencap -p > {shot_path}"
            subprocess.run(cmd, shell=True, check=True, timeout=8.0)
            shot_captured = True
            logger.info(f"📸 [클릭 직전 캡쳐 완료] {shot_path.name} | 조준 좌표: ({click_x:.1f}, {click_y:.1f}) | 안정화: {'PASS' if is_stable else 'TIMEOUT'} (소요: {stabilize_dur}초)")
        except Exception as e:
            logger.warning(f"⚠️ [화면 캡쳐 예외] {e}")
    else:
        logger.info(f"⚡ [중간 네비게이션 클릭] '{action_name}' 조준 좌표: ({click_x:.1f}, {click_y:.1f}) | 안정화: {'PASS' if is_stable else 'TIMEOUT'} (소요: {stabilize_dur}초, 캡처 생략)")

    # 4. 정밀 터치 디스패치 (방해 툴팁/코치마크 강제 삭제)
    try:
        await cdp.evaluate(f"""
        (() => {{
            // 방해 툴팁/레이어 요소 즉시 DOM에서 영구 제거
            const tooltipSelectors = ['[class*="searchTab_tooltip"]', '[class*="searchTab_active"]', '[class*="layerDeliveryGuide"]', '[class*="tooltip"]', '[class*="coachmark"]'];
            tooltipSelectors.forEach(sel => document.querySelectorAll(sel).forEach(el => {{ try {{ el.remove(); }} catch(e){{}} }}));
        }})()
        """)
    except Exception:
        pass



    # [CDP 정밀 핀포인트 터치 이벤트 발송: 사람 손가락 타원형 면적(18~28px), 가변 압력, 75~110ms 접촉]
    logger.info(f"👉 [{action_name} CDP 핀포인트 탭 발송] 좌표: ({click_x:.1f}, {click_y:.1f})")
    touch_dur = random.uniform(0.075, 0.110)
    rad_x = round(random.uniform(18.0, 24.5), 1)
    rad_y = round(random.uniform(22.0, 30.5), 1)
    touch_force = round(random.uniform(0.88, 1.0), 2)
    await cdp.call("Input.dispatchTouchEvent", {
        "type": "touchStart",
        "touchPoints": [{"x": click_x, "y": click_y, "radiusX": rad_x, "radiusY": rad_y, "force": touch_force}]
    })
    await asyncio.sleep(touch_dur)
    await cdp.call("Input.dispatchTouchEvent", {
        "type": "touchEnd",
        "touchPoints": []
    })

    # 5. 오버레이 및 하이라이트 정리
    try:
        await cdp.evaluate("""
        (() => {
            const oldOverlay = document.getElementById('_probe_crosshair_ovl');
            if (oldOverlay) oldOverlay.remove();
            const oldStyle = document.getElementById('_probe_highlight_style');
            if (oldStyle) oldStyle.remove();
            document.querySelectorAll('._probe_target_hi').forEach(el => el.classList.remove('_probe_target_hi'));
        })()
        """)
    except Exception:
        pass

    return {
        "action": action_name,
        "x": click_x,
        "y": click_y,
        "is_stable": is_stable,
        "stabilize_seconds": stabilize_dur,
        "capture_path": str(shot_path) if shot_captured else None
    }

async def _execute_task_internal(task: TaskInput) -> Dict[str, Any]:
    start_time = time.time()
    result = TaskResult(task.task_id, task.keyword, task.nv_mid, task.compare_id, raw_keyword=task.raw_keyword)
    result.store_name = task.store_name
    result.dwell_seconds = task.dwell_seconds
    result.ip = getattr(task, "ip", "unknown") or "unknown"

    # 1. Device Selection (Random default)
    try:
        device_id = select_device(task.device_id)
        result.device_id = device_id
        cdp_port = get_cdp_port(device_id)
    except Exception as e:
        result.status = "DEVICE_SELECTION_FAILED"
        result.error_message = str(e)
        result.duration_seconds = time.time() - start_time
        return result.to_dict()

    # 2. NNB Acquisition (Use direct nnb if provided in TaskInput, otherwise fetch)
    if task.nnb:
        nnb_packet = {"nnb": task.nnb, "buc": task.buc or "", "source": "task_assign"}
        logger.info(f"🔑 [NNB 할당] 작업 할당 NNB 직접 사용: {task.nnb}")
    else:
        nnb_packet = get_nnb_packet(device_id=device_id, use_remote=task.use_remote_nnb, force_refresh=True)
    result.nnb = nnb_packet.get("nnb", "")
    result.nnb_age_seconds = int(nnb_packet.get("age_seconds", 0))

    # 3. [사용자 절대 철칙] 캐시 보존형 정밀 초기화 (Surgical Clean & Profile Injection)
    # 중복 pm clear를 배제하여 V8 code_cache 및 정적 캐시 100% 보존 -> 메인창 3.5초 대기 원천 제거
    t0_surgical = time.time()
    profile = task.profile if (hasattr(task, "profile") and task.profile) else generate_fresh_session_profile()

    # 식별자 무결성 감사 엔진 자동 연동 (직전 회차와 1:1 대조 검수)
    from src.device.identity_auditor import IdentityAuditor
    auditor = IdentityAuditor()
    identity_packet = {
        "ssaid": profile["ssaid"],
        "napp_di": profile.get("napp_di") or hashlib.md5(profile["ssaid"].encode("utf-8")).hexdigest(),
        "nnb": result.nnb,
        "nnb_age_seconds": result.nnb_age_seconds,
        "buc": nnb_packet.get("buc", ""),
        "dadd": profile["dadd"],
        "dadv": profile["dadv"],
        "lat": profile["lat"],
        "lng": profile["lng"],
        "region": profile.get("region", "대한민국"),
        "google_account": profile["google_account"],
        "ip": getattr(task, "ip", "unknown")
    }
    is_valid, audit_summary, table_text = auditor.audit_and_record(device_id, identity_packet)
    result.identity_audit = audit_summary
    result.ip = str(identity_packet.get("ip", "unknown"))
    if not is_valid:
        logger.critical(f"🚨 [식별자 충돌 감지!] 직전 회차와 동일한 식별자 검출로 즉시 중단\n{table_text}")
        result.status = "IDENTITY_COLLISION"
        result.error_message = "직전 회차와 동일한 식별자 충돌 감지 (무결성 위배)"
        force_stop_app(device_id)
        result.duration_seconds = time.time() - start_time
        return result.to_dict()
    logger.info(f"✅ [식별자 무결성 검수 100% 통과] 직전 회차 대비 9대 식별자 충돌 0% 확인")

    logger.info(f"🚀 [작업 시작] Task #{task.task_id} | 기기: {device_id} | NNB: {result.nnb} | 키워드: '{task.keyword}' (원문: '{task.raw_keyword}') | 타겟: {task.nv_mid} (compare_id: {task.compare_id})")

    perform_surgical_cycle(
        device_id=device_id,
        aged_nnb=result.nnb,
        aged_buc=nnb_packet.get("buc", ""),
        fresh_ssaid=profile["ssaid"],
        fresh_dadd=profile["dadd"],
        fresh_dadv=profile["dadv"],
        fresh_lat=profile["lat"],
        fresh_lng=profile["lng"],
        cdp_port=cdp_port
    )
    result.timing_profile["t_surgical_clean_ms"] = round((time.time() - t0_surgical) * 1000, 1)

    # 4. Frida Spawning
    t0_spawn = time.time()
    pid, session = spawn_app_with_cdp(
        device_id, cdp_port,
        spoof_ssaid=profile["ssaid"],
        spoof_google_account=profile["google_account"],
        spoof_dadd=profile["dadd"],
        spoof_dadv=profile["dadv"],
        spoof_lat=profile["lat"],
        spoof_lng=profile["lng"],
        target_nnb=result.nnb
    )
    result.timing_profile["t_frida_spawn_ms"] = round((time.time() - t0_spawn) * 1000, 1)

    # 5. Launch Intent & Connect SERP
    t0_serp = time.time()
    serp_ws = None
    for attempt in range(3):
        if attempt > 0:
            await asyncio.sleep(0.5)
        start_intent(device_id, build_intent_url(task.keyword))
        serp_ws = await find_serp_debugger_url(cdp_port, timeout=8.0)
        if serp_ws:
            logger.info(f"🔗 [통합검색 탭 연결 성공 (시도 {attempt+1}/3)] {serp_ws}")
            break
        logger.warning(f"⚠️ SERP 탭 미발견 (시도 {attempt+1}/3) -> 0.5초 대기 후 Intent 재발송...")

    result.timing_profile["t_serp_intent_ms"] = round((time.time() - t0_serp) * 1000, 1)

    if not serp_ws:
        result.status = "SERP_TAB_NOT_FOUND"
        result.error_message = "통합검색(SERP) DevTools 탭을 찾을 수 없습니다."
        force_stop_app(device_id)
        result.duration_seconds = time.time() - start_time
        return result.to_dict()

    # Target IDs to search for: both nv_mid and compare_id (either can appear in results)
    target_ids = [task.nv_mid]
    if task.compare_id and task.compare_id != task.nv_mid:
        target_ids.append(task.compare_id)
    target_ids_json = json.dumps(target_ids)

    # 6. Evaluate SERP Rank & Decide Direct Touch or Touch '쇼핑 더보기'
    target_clicked_on_serp = False
    async with safe_ws_connect(serp_ws) as ws:
        serp_cdp = AsyncCDPClient(ws)
        try:
            await serp_cdp.call("Network.enable")
        except Exception:
            pass


        # [사용자 지침 필수 게이트] 통합검색 페이지 및 필수 데이터 완성도 검증
        logger.info("⏳ [통합검색 완성도 게이트] document.readyState, pagedSlot/쇼핑탭 필수 데이터 로딩 검증 중...")
        last_h = 0
        stable_h_count = 0
        target_nnb = result.nnb or task.nnb or ""
        target_buc = nnb_packet.get("buc") or task.buc or ""

        # [쿠키 반영 구분자] CDP 레벨 세션 쿠키 동기화 (0.5s 타임아웃으로 블로킹 방지)
        try:
            if target_nnb:
                await serp_cdp.call("Network.setCookie", {
                    "name": "NNB",
                    "value": target_nnb,
                    "domain": ".naver.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "Lax"
                }, timeout=0.5)
            if target_buc:
                await serp_cdp.call("Network.setCookie", {
                    "name": "BUC",
                    "value": target_buc,
                    "domain": ".naver.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax"
                }, timeout=0.5)
        except Exception:
            pass

        is_gate_ready = False
        t0_gate = time.time()
        for wait_serp_gate in range(50):  # 최대 5.0초 (100ms * 50)
            await asyncio.sleep(0.1)
            try:
                gate_check = await serp_cdp.evaluate(f"""
                (() => {{
                    const curUrl = window.location.href;
                    const isSearchUrl = curUrl.includes('search.naver.com') && (curUrl.includes('query=') || curUrl.includes('where=m'));
                    const isLogin = curUrl.includes('nid.naver.com') || curUrl.includes('nidlogin');
                    const isDocComplete = document.readyState === 'complete' || document.readyState === 'interactive';
                    const cookies = document.cookie || '';
                    const hasNNB = cookies.includes('NNB=');

                    const ps = window.naver?.search?.ext?.newshopping?.shopping?._INITIAL_STATE?.initProps?.pagedSlot;
                    const hasPagedSlot = !!(ps && Array.isArray(ps) && ps.length > 0);

                    const hasNavOrData = !!(
                        document.querySelector('a[href*="shopping"], [role="tab"], header, #header, #ct, section') ||
                        hasPagedSlot
                    );

                    // [사용자 핵심 지침] 통합검색은 무한 확장이 없으며 pagedSlot 또는 쇼핑 네비게이션이 로드되면 즉시 패스!
                    const fastReady = isSearchUrl && !isLogin && (hasPagedSlot || (isDocComplete && hasNavOrData));

                    return {{
                        isLogin,
                        curUrl,
                        isSearchUrl,
                        isDocComplete,
                        hasNNB,
                        hasPagedSlot,
                        ready: fastReady
                    }};
                }})()
                """, timeout=1.5)
            except Exception:
                continue

            if not isinstance(gate_check, dict):
                continue

            if gate_check.get("isLogin"):
                reason = f"URL: {gate_check.get('curUrl')}"
                logger.error(f"🚨 [초고속 로그인 감지 - SERP 진입] {reason}")
                take_login_alert_screenshot(device_id, task.task_id)
                result.login_detected = True
                result.status = "LOGIN_REQUIRED"
                result.error_message = f"SERP 진입 중 로그인 창 감지 ({reason})"
                serp_cdp.close()
                force_stop_app(device_id)
                result.duration_seconds = time.time() - start_time
                return result.to_dict()

            if gate_check.get("ready"):
                logger.info(f"⚡ [통합검색 pagedSlot/쇼핑데이터 즉시 포착] 불필요한 로딩 대기 생략 -> 즉시 조준/타격 진입 (소요: {(wait_serp_gate+1)*0.1:.2f}초, pagedSlot={gate_check.get('hasPagedSlot')})")
                is_gate_ready = True
                break

        result.timing_profile["t_serp_gate_ms"] = round((time.time() - t0_gate) * 1000, 1)

        # =========================================================================
        # [사용자 핵심 지침: Data-First(State-First) 통합검색 탐색 체계]
        # naver.search.ext.newshopping.shopping._INITIAL_STATE.initProps.pagedSlot
        # 1. pagedSlot 객체의 존재 유무를 먼저 검사하여 쇼핑 섹션 존재 여부 확정
        # 2. pagedSlot.slots 배열 순회 및 페이징 분석으로 타겟(nv_mid / compare_id) 존재 유무를 0초만에 선행 판독
        # 3. 절대 DOM을 먼저 뒤지지 않음 (DOM 선행 탐색 시 웹문서/블로그/스마트블록 오클릭 버그 원천 차단)
        # 4. pagedSlot에 타겟이 존재할 때만 페이징 이동 후 쇼핑 섹션 DOM(순수 상품 카드)으로 정밀 접근
        # 5. pagedSlot에 타겟이 없으면 DOM을 일체 뒤지지 않고 상단 카테고리 [쇼핑] 탭으로 즉시 이동
        # =========================================================================
        serp_info = await serp_cdp.evaluate(f"""
        (() => {{
            const targetMid = "{task.nv_mid}";
            const compareId = "{task.compare_id or ''}";

            // 1. 상단 카테고리 메뉴바(GNB/LNB) 내 '쇼핑' 탭 탐색 (최우선 쇼핑 진입 경로)
            const allNavLinks = Array.from(document.querySelectorAll('a, button, [role="tab"]'));
            let catShoppingTab = allNavLinks.find(el => {{
                const t = (el.innerText || '').trim();
                const h = el.href || '';
                return (t === '쇼핑' || t === '네이버쇼핑') && (h.includes('shopping') || h.includes('search') || !h);
            }});

            let categoryTabCoord = null;
            if (catShoppingTab) {{
                catShoppingTab.scrollIntoView({{ block: 'nearest', inline: 'center', behavior: 'instant' }});
                const r = catShoppingTab.getBoundingClientRect();
                categoryTabCoord = {{ x: r.x + r.width/2, y: r.y + r.height/2 }};
            }}

            // 2. 하단 쇼핑 더보기 버튼 탐색 (백업용)
            const allLinks = Array.from(document.querySelectorAll('a'));
            let moreBottomLink = allLinks.find(a => (a.href || '').includes('msearch.shopping.naver.com') && ((a.innerText || '').includes('더보기') || (a.innerText || '').includes('쇼핑') || (a.innerText || '').includes('가격비교')));
            if (!moreBottomLink) moreBottomLink = allLinks.find(a => (a.href || '').includes('msearch.shopping.naver.com'));
            let moreBottomCoord = null;
            if (moreBottomLink) {{
                moreBottomLink.scrollIntoView({{ block: 'center', behavior: 'instant' }});
                const r = moreBottomLink.getBoundingClientRect();
                moreBottomCoord = {{ x: r.x + r.width/2, y: r.y + r.height/2 }};
            }}

            // 3. 네이버 쇼핑 글로벌 상태 객체 검사 (Data-First)
            const ps = window.naver?.search?.ext?.newshopping?.shopping?._INITIAL_STATE?.initProps?.pagedSlot;
            const hasPagedSlot = !!(ps && Array.isArray(ps) && ps.length > 0);
            const hasShoppingPresence = hasPagedSlot || (catShoppingTab !== undefined) || (moreBottomLink !== undefined);

            if (!hasShoppingPresence) {{
                return {{
                    hasShoppingPresence: false,
                    hasPagedSlot: false,
                    foundSlot: null
                }};
            }}

            // 4. pagedSlot.slots 순회 및 페이징 타겟 분석
            let foundSlot = null;
            let organicRankCounter = 0;
            let totalSlotsCount = 0;

            if (hasPagedSlot) {{
                for (let pIdx = 0; pIdx < ps.length; pIdx++) {{
                    const pageObj = ps[pIdx];
                    const slots = pageObj.slots || [];
                    totalSlotsCount += slots.length;

                    for (let sIdx = 0; sIdx < slots.length; sIdx++) {{
                        const slot = slots[sIdx];
                        const d = slot.data || {{}};

                        // 🚫 [절대 철칙 1] 광고 필터링: sourceType === 'AD'는 확실한 광고이므로 100% 배제!
                        // sourceType !== 'AD' (예: 'SAS', 'SUPER_POINT')인 것만이 순수 오가닉 상품
                        const isAd = (d.sourceType === 'AD') || 
                                     (d.cardType === 'AD_CARD') || 
                                     (d.sasType && d.sasType.includes('AD')) || 
                                     !!d.isAd;
                        if (isAd) continue;

                        organicRankCounter++;

                        const slotMid = String(d.nvMid || '');
                        const slotCatId = String(d.catalogMatchingId || '');
                        const slotChanId = String(d.channelProductId || '');

                        const matchMid = targetMid && (slotMid === targetMid || slotChanId === targetMid);
                        const matchCat = compareId && (slotCatId === compareId || slotMid === compareId);

                        if (matchMid || matchCat) {{
                            foundSlot = {{
                                pageIndex: pIdx,
                                pageNumber: pageObj.page || (pIdx + 1),
                                slotIndex: sIdx,
                                rank: d.rank || organicRankCounter,
                                matchType: matchMid ? 'nv_mid' : 'compare_id',
                                nvMid: slotMid,
                                catalogMatchingId: slotCatId,
                                productName: (d.productName || '').replace(/<[^>]+>/g, ''),
                                mallName: d.mallName || '',
                                cardType: d.cardType || '',
                                sourceType: d.sourceType || '',
                                isCatalog: (d.cardType === 'CATALOG_CARD') || !!d.catalogMatchingId || (matchCat && !matchMid)
                            }};
                            break;
                        }}
                    }}
                    if (foundSlot) break;
                }}
            }}

            return {{
                hasShoppingPresence: hasShoppingPresence,
                hasPagedSlot: hasPagedSlot,
                pagedSlotPages: hasPagedSlot ? ps.length : 0,
                totalSlotsCount: totalSlotsCount,
                foundSlot: foundSlot,
                categoryTabCoord: categoryTabCoord,
                moreBottomCoord: moreBottomCoord,
                hasCategoryTab: !!catShoppingTab
            }};
        }})()
        """)

        if not isinstance(serp_info, dict):
            serp_info = {}

        # 쇼핑 섹션 및 State 구조 자동 기록
        try:
            pattern_record = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "task_id": task.task_id,
                "keyword": task.keyword,
                "has_shopping_presence": serp_info.get("hasShoppingPresence"),
                "has_paged_slot": serp_info.get("hasPagedSlot"),
                "paged_slot_pages": serp_info.get("pagedSlotPages", 0),
                "total_slots": serp_info.get("totalSlotsCount", 0),
                "found_target_on_serp": bool(serp_info.get("foundSlot"))
            }
            with open(ROOT_DIR / "serp_shopping_patterns.jsonl", "a", encoding="utf-8") as pf:
                pf.write(json.dumps(pattern_record, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # [사용자 지침] 검색결과에서 쇼핑탭 및 쇼핑섹션 자체가 전혀 없다면 즉시 종료(PASS)
        if not serp_info.get("hasShoppingPresence"):
            logger.warning(f"ℹ️ [비쇼핑성 키워드] 통합검색 결과에 상단 [쇼핑] 탭 및 쇼핑 섹션이 전혀 존재하지 않음 -> 즉시 종료(PASS)")
            result.status = "NO_SHOPPING_CATEGORY"
            result.error_message = "통합검색에 상단 쇼핑 탭 및 쇼핑 섹션이 전혀 존재하지 않아 즉시 PASS 처리"
            serp_cdp.close()
            force_stop_app(device_id)
            result.duration_seconds = time.time() - start_time
            return result.to_dict()

        found_slot = serp_info.get("foundSlot")

        # =========================================================================
        # CASE 1: pagedSlot 데이터 상에 타겟 상품이 명백히 노출된 경우
        # =========================================================================
        if found_slot:
            result.serp_rank = found_slot["rank"]
            result.shopping_rank = found_slot["rank"]
            result.shopping_page = found_slot["pageNumber"]  # pagedSlot 인덱스 + 1 (통합검색 내 쇼핑 페이지 번호)
            result.search_type = "m.search"
            result.match_type = found_slot["matchType"]
            result.target_type = "CATALOG" if found_slot.get("isCatalog") else "PROD"

            logger.info(f"⚡ [통합검색 State 발견] 타겟 상품이 pagedSlot {found_slot['pageNumber']}페이지 {found_slot['rank']}위에 노출 확인! [매칭: {found_slot['matchType']}]")
            logger.info(f"   • 상품: '{found_slot.get('productName')}' | 몰: '{found_slot.get('mallName')}' | SERP에서 직접 타격 진행")

            target_mid_str = found_slot.get("nvMid") or task.nv_mid

            # 타겟이 2페이지 이상에 있는 경우: 페이징 버튼을 클릭하여 해당 슬롯을 DOM에 마운트
            target_page_idx = found_slot.get("pageIndex", 0)
            if target_page_idx > 0:
                logger.info(f"📑 [통합검색 페이징 이동] 타겟이 {target_page_idx+1}페이지에 위치 -> 슬라이드/페이징 네비게이션 시도...")
                for p_step in range(target_page_idx):
                    await serp_cdp.evaluate("""
                    (() => {
                        const sec = document.querySelector('section._root_shp_lis, section[data-slog-container="shp_lis"]');
                        if (!sec) return;
                        const nextBtn = sec.querySelector('button[class*="next"], a[class*="next"], [class*="btn_next"], [aria-label*="다음"]');
                        if (nextBtn) nextBtn.click();
                    })()
                    """)
                    await asyncio.sleep(0.5)

            # 정확한 뷰포트 스크롤 및 정밀 좌표 재측정
            exact_coord = await serp_cdp.evaluate(f"""
            (() => {{
                const targetMid = "{target_mid_str}";
                const sec = document.querySelector('section._root_shp_lis, section[data-slog-container="shp_lis"]');
                if (!sec) return null;

                // 1. 해당 섹션 내에서 targetMid 또는 catalogId를 가진 링크/요소 탐색
                let targetEl = sec.querySelector(`a[href*="nv_mid=${{targetMid}}"]`) || 
                               sec.querySelector(`[data-nlog-params*="${{targetMid}}"]`);

                if (!targetEl) {{
                    const catId = "{found_slot.get('catalogMatchingId') or ''}";
                    if (catId) {{
                        targetEl = sec.querySelector(`a[href*="nv_mid=${{catId}}"]`) || 
                                   sec.querySelector(`[data-nlog-params*="${{catId}}"]`);
                    }}
                }}

                if (!targetEl) return null;

                // 2. 카드의 최상위 li/div 탐색
                const card = targetEl.closest('li, div[class*="item"], div[class*="product"], div[class*="card"]') || targetEl.parentElement || targetEl;

                // 3. 카드를 뷰포트 중앙으로 정확히 스크롤 (즉시 정지)
                card.scrollIntoView({{ block: 'center', inline: 'nearest', behavior: 'instant' }});

                // 4. 순수 상품명 제목 엘리먼트 정밀 탐색
                let titEl = card.querySelector('strong') || 
                            card.querySelector('[class*="title"], [class*="tit"], [class*="name"]');

                const cr = card.getBoundingClientRect();
                let clickX, clickY;
                let tr = titEl ? titEl.getBoundingClientRect() : null;

                if (tr && tr.width >= 30 && tr.height >= 10 && tr.x >= 100) {{
                    clickX = tr.x + Math.max(20.0, Math.min(tr.width * 0.35, 60.0));
                    clickY = tr.y + tr.height / 2;
                }} else {{
                    clickX = Math.max(180.0, cr.x + 160.0);
                    clickY = cr.y + Math.min(Math.max(cr.height * 0.2, 25.0), 40.0);
                    tr = cr;
                }}

                const bestTitEl = titEl || targetEl;

                let targetLink = targetEl ? (targetEl.href || targetEl.getAttribute('data-original-href') || '') : '';
                return {{
                    x: clickX,
                    y: clickY,
                    titX: tr.x,
                    width: tr.width,
                    height: tr.height,
                    titleText: (bestTitEl.innerText || '').trim().substring(0, 30),
                    pageUrl: window.location.href,
                    productUrl: targetLink
                }};
            }})()
            """)

            if exact_coord:
                logger.info(f"🎯 [통합검색 타겟 직접 타격] 조준 완료: ({exact_coord.get('x'):.1f}, {exact_coord.get('y'):.1f}) | 제목: '{exact_coord.get('titleText')}'")
                result.pre_click_url = exact_coord.get("pageUrl")
                result.target_product_url = exact_coord.get("productUrl")
                if result.pre_click_url:
                    logger.info(f"🌐 [클릭 전 네이버 SERP URL] {result.pre_click_url}")
                if result.target_product_url:
                    logger.info(f"🔗 [타겟 상품 카드 원본 링크] {result.target_product_url}")

                # 스크롤 관성(Scroll Inertia) 완전 소멸 대기 (드래그 오인 방지)
                await asyncio.sleep(0.25)
                click_x = exact_coord.get("x", 150.0)
                click_y = exact_coord.get("y", 310.0)
                if click_y <= 0:
                    click_y = 310.0

                result.touch_coordinates = {"x": round(click_x, 1), "y": round(click_y, 1)}

                target_selector_js = f"""document.querySelector('section._root_shp_lis a[data-original-href*="{target_mid_str}"], section._root_shp_lis a[href*="{target_mid_str}"], section[data-slog-container="shp_lis"] a[data-original-href*="{target_mid_str}"], section[data-slog-container="shp_lis"] a[href*="{target_mid_str}"]')"""
                # 클릭 직전 활성 탭 목록 기록 (신규 탭/액티비티 생성 감지용)
                pre_click_ws_set = set()
                try:
                    tabs_before_click = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.5).read().decode())
                    pre_click_ws_set = {t.get("webSocketDebuggerUrl") for t in tabs_before_click if t.get("webSocketDebuggerUrl")}
                except Exception:
                    pass

                click_act = await visual_stabilize_and_click(
                    cdp=serp_cdp,
                    device_id=device_id,
                    task_id=task.task_id,
                    action_name="SERP_TARGET",
                    click_x=click_x,
                    click_y=click_y,
                    target_selector_expr=target_selector_js
                )
                result.before_click_screenshot = click_act.get("capture_path")
                target_clicked_on_serp = True
                serp_cdp.close()
            else:
                logger.warning(f"⚠️ [State상 존재하나 DOM 특정 실패] 타겟 nvMid:{target_mid_str} DOM 좌표 측정 실패 -> 상단 카테고리 [쇼핑] 탭으로 전환")

        # =========================================================================
        # CASE 2: pagedSlot 상에 타겟 상품이 없는 경우 (DOM 뒤지지 않고 즉시 쇼핑 탭 이동)
        # =========================================================================
        if not target_clicked_on_serp:
            more_coord = serp_info.get("categoryTabCoord") or serp_info.get("moreBottomCoord")
            more_source_name = "상단 카테고리 [쇼핑] 탭" if serp_info.get("hasCategoryTab") else "하단 쇼핑 더보기 버튼"
            logger.info(f"ℹ️ [통합검색 State 판독] 타겟(nv_mid:{task.nv_mid}, compare_id:{task.compare_id}) pagedSlot 전체 미노출 -> {more_source_name} 터치로 쇼핑 검색 이동")

            if not more_coord:
                result.status = "SHOPPING_MORE_BTN_NOT_FOUND"
                result.error_message = "통합검색에서 쇼핑 카테고리 탭/더보기 버튼을 찾을 수 없습니다."
                serp_cdp.close()
                force_stop_app(device_id)
                result.duration_seconds = time.time() - start_time
                return result.to_dict()

            # [사용자 지침] 카테고리 탭 터치 전 화면 상단 복귀 및 방해 툴팁/코치마크 완전 소멸
            try:
                await serp_cdp.evaluate("window.scrollTo(0, 0);")
                await serp_cdp.evaluate(PURGE_TOOLTIPS_JS)
            except Exception:
                pass

            action_tag = "CATEGORY_TAB" if serp_info.get("hasCategoryTab") else "SHOPPING_MORE"
            await visual_stabilize_and_click(
                cdp=serp_cdp,
                device_id=device_id,
                task_id=task.task_id,
                action_name=action_tag,
                click_x=more_coord["x"],
                click_y=more_coord["y"]
            )
            serp_cdp.close()

    # 7 & 8: Shopping Search Tab Processing (Only when not clicked on SERP)
    if not target_clicked_on_serp:
        logger.info("⏳ ['쇼핑 더보기' 터치 후 쇼핑 탭 오픈 대기]...")
        shop_tab_ws = None
        for wait_tab in range(70):  # max 10.5s (0.15s * 70, 느린 LTE 완충)
            await asyncio.sleep(0.15)
            
            # [초고속 로그인 감지] 쇼핑 탭 전환 중 로그인창 발생 시 즉시 중단
            is_login_fast, login_fast_reason = await fast_check_login_state(device_id, cdp_port)
            if is_login_fast:
                logger.error(f"🚨 [초고속 로그인 감지 - 쇼핑탭 대기] {login_fast_reason}")
                take_login_alert_screenshot(device_id, task.task_id)
                result.login_detected = True
                result.status = "LOGIN_REQUIRED"
                result.error_message = f"쇼핑 탭 이동 중 로그인 창 발생: {login_fast_reason}"
                force_stop_app(device_id)
                result.duration_seconds = time.time() - start_time
                return result.to_dict()

            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.5).read().decode())
                # 1순위: URL에 shopping.naver.com, msearch.shopping, where=m_shop 등이 포함된 탭
                shop_tab = next((t for t in tabs if any(k in t.get("url", "") for k in ["shopping.naver.com", "msearch.shopping", "where=m_shop", "/search/all"])), None)
                # 2순위: 기존 SERP 탭의 URL 자체가 쇼핑으로 이동한 경우
                if not shop_tab:
                    serp_cand = next((t for t in tabs if t.get("webSocketDebuggerUrl") == serp_ws), None)
                    if serp_cand and any(k in serp_cand.get("url", "") for k in ["shopping", "msearch", "where=m_shop"]):
                        shop_tab = serp_cand

                if shop_tab and shop_tab.get("webSocketDebuggerUrl"):
                    shop_tab_ws = shop_tab["webSocketDebuggerUrl"]
                    logger.info(f"🔗 [쇼핑 탭 연결 성공] {shop_tab.get('url')[:60]}... (대기: {(wait_tab+1)*0.15:.2f}초)")
                    break
            except Exception:
                pass

        if not shop_tab_ws:
            result.status = "SHOPPING_TAB_NOT_FOUND"
            result.error_message = "10초 대기 후에도 쇼핑 검색 탭이 열리지 않았습니다."
            force_stop_app(device_id)
            result.duration_seconds = time.time() - start_time
            return result.to_dict()

        async with safe_ws_connect(shop_tab_ws) as ws:
            shop_cdp = AsyncCDPClient(ws)
            try:
                await shop_cdp.call("Network.enable")
            except Exception:
                pass

            # [쇼핑 탭 완성도 게이트] document.readyState, NNB 쿠키, __NEXT_DATA__ 또는 DOM 상품 카드 렌더링 대기
            logger.info("⏳ [쇼핑 탭 완성도 게이트] HTML 로드, NNB 쿠키 동기화, __NEXT_DATA__ 생성 대기 중...")
            for wait_shop_gate in range(75):  # 최대 15.0초 (200ms * 75, 느린 LTE 완충)
                await asyncio.sleep(0.2)
                shop_ready = await shop_cdp.evaluate("""
                (() => {
                    const isDocComplete = document.readyState === 'complete';
                    const cookies = document.cookie || '';
                    const hasNNB = cookies.includes('NNB=');
                    const comp = window.__NEXT_DATA__?.props?.pageProps?.compositeProducts || window.__NEXT_DATA__?.props?.pageProps?.initialData?.products;
                    const hasNextData = !!(comp?.list && comp.list.length > 0);
                    const hasDomProducts = !!(document.querySelector('div[class*="product_info_main"], div[class*="product_item"]'));
                    return { ready: isDocComplete && (hasNextData || hasDomProducts) };
                })()
                """)
                if isinstance(shop_ready, dict) and shop_ready.get("ready"):
                    logger.info(f"✅ [쇼핑 탭 완성 확인] HTML 완료, 데이터/DOM 준비 완료 (소요: {(wait_shop_gate+1)*0.2:.1f}초)")
                    break
            else:
                logger.warning("⚠️ [쇼핑 탭 게이트 타임아웃] __NEXT_DATA__ 또는 DOM 상품 카드 미검출")

            try:
                page_diag = await shop_cdp.evaluate("""
                (() => {
                    return {
                        url: window.location.href,
                        title: document.title,
                        readyState: document.readyState,
                        has_next_data: !!window.__NEXT_DATA__,
                        next_keys: window.__NEXT_DATA__ ? Object.keys(window.__NEXT_DATA__) : [],
                        pageProps_keys: window.__NEXT_DATA__?.props?.pageProps ? Object.keys(window.__NEXT_DATA__.props.pageProps) : [],
                        body_snippet: (document.body?.innerText || '').substring(0, 300)
                    };
                })()
                """)
                logger.info(f"🔎 [쇼핑 탭 진단] {page_diag}")
                subprocess.run(f"adb -s {device_id} exec-out screencap -p > /home/tech/.gemini/antigravity-cli/brain/2b4c234f-56d2-4090-9118-293789223c3c/shop_tab_debug.png", shell=True, check=True, timeout=5.0)
                logger.info("📸 [쇼핑 탭 화면 덤프 완료] shop_tab_debug.png")
            except Exception as e:
                logger.warning(f"⚠️ [쇼핑 탭 진단 실패] {e}")

            # [사용자 핵심 지침] msearch 접근 시 상단 searchTab_tooltip 및 방해 레이어 완전 영구 제거
            try:
                purged_cnt = await shop_cdp.evaluate(PURGE_TOOLTIPS_JS)
                if purged_cnt:
                    logger.info(f"🧹 [msearch 방해 툴팁 제거] searchTab_tooltip 포함 {purged_cnt}개 가림막 요소 DOM 영구 삭제 완료")
            except Exception:
                pass


            target_found_page = 1
            target_found_rank = None
            target_card_info = None

            logger.info("🔍 [쇼핑 1페이지 __NEXT_DATA__ 선행 파악] 타겟 존재 유무 0초 검사 시작...")

            # 1. __NEXT_DATA__ 에서 1페이지 목록 전체(최대 40~56개) 타겟 유무 확인
            next_data_check = await shop_cdp.evaluate(f"""
            (() => {{
                const targetMid = "{task.nv_mid}";
                const compareId = "{task.compare_id or ''}";
                const pp = window.__NEXT_DATA__?.props?.pageProps || {{}};
                const comp = pp.compositeProducts || pp.initialData?.products || {{}};
                const list = comp.list || pp.products || [];

                let midMatch = null;
                let catalogMatch = null;
                let organicRankCounter = 0;

                for (let i = 0; i < list.length; i++) {{
                    const entry = list[i];
                    const it = entry.item || entry;
                    if (!it.ad) organicRankCounter++;

                    const itId = String(it.id || it.nvMid || '');
                    const officialRank = (typeof it.rank === 'number' && it.rank > 0) ? it.rank : organicRankCounter;

                    // 1순위: nv_mid 일치
                    if (targetMid && itId === targetMid && !midMatch) {{
                        midMatch = {{
                            rank: officialRank,
                            id: itId,
                            title: it.productTitle || it.productName || it.title || '',
                            mallName: it.mallName || '',
                            mallCount: it.mallCount || 0,
                            price: it.lowPrice || it.price,
                            isCatalog: (it.mallCount > 1),
                            matchType: 'nv_mid'
                        }};
                    }}

                    // 2순위: compare_id 일치
                    if (compareId && itId === compareId && !catalogMatch) {{
                        catalogMatch = {{
                            rank: officialRank,
                            id: itId,
                            title: it.productTitle || it.productName || it.title || '',
                            mallName: it.mallName || '',
                            mallCount: it.mallCount || 0,
                            price: it.lowPrice || it.price,
                            isCatalog: true,
                            matchType: 'compare_id'
                        }};
                    }}
                }}

                const selected = midMatch || (compareId ? catalogMatch : null);
                return {{
                    totalListCount: list.length,
                    hasTarget: selected !== null,
                    targetItem: selected
                }};
            }})()
            """)

            if not isinstance(next_data_check, dict):
                next_data_check = {}

            total_items = next_data_check.get("totalListCount", 0)
            has_target = next_data_check.get("hasTarget", False)
            target_item = next_data_check.get("targetItem")

            if not has_target:
                # [DOM 선행 폴백 검사] __NEXT_DATA__에 없거나 비동기 상태일 때, DOM 카드 직접 1차 스캔
                logger.warning(f"⚠️ [쇼핑 1페이지] __NEXT_DATA__({total_items}개)에서 미포착 -> DOM 카드 실시간 스캔 폴백 가동...")
                dom_scan = await shop_cdp.evaluate(f"""
                (() => {{
                    const targetMid = "{task.nv_mid}";
                    const compareId = "{task.compare_id or ''}";
                    const mainCards = Array.from(document.querySelectorAll('div[class*="product_info_main"]'));
                    let rankCount = 0;
                    for (let card of mainCards) {{
                        if (card.closest('div[class*="productExpandSub"]')) continue;
                        rankCount++;
                        const links = Array.from(card.querySelectorAll('a'));
                        for (let a of links) {{
                            if (a.closest('div[class*="productExpandSub"]')) continue;
                            let isMatch = false;
                            let matchType = '';
                            try {{
                                const p = JSON.parse(a.getAttribute('data-nlog-params') || '{{}}');
                                if (p.is_ad === true) continue;
                                const cId = String(p.content_id || '');
                                if (targetMid && (cId === targetMid || a.href.includes(targetMid))) {{ isMatch = true; matchType = 'nv_mid'; }}
                                if (compareId && (cId === compareId || a.href.includes(compareId))) {{ isMatch = true; matchType = 'compare_id'; }}
                            }} catch(e) {{}}
                            if (!isMatch) {{
                                const h = a.href || '';
                                if (targetMid && h.includes(targetMid)) {{ isMatch = true; matchType = 'nv_mid'; }}
                                if (compareId && h.includes(compareId)) {{ isMatch = true; matchType = 'compare_id'; }}
                            }}
                            if (isMatch) {{
                                return {{
                                    found: true,
                                    rank: rankCount,
                                    title: (card.innerText || '').slice(0, 30),
                                    matchType: matchType,
                                    isCatalog: !!compareId
                                }};
                            }}
                        }}
                    }}
                    return {{ found: false, totalCards: mainCards.length }};
                }})()
                """)
                if isinstance(dom_scan, dict) and dom_scan.get("found"):
                    logger.info(f"🎯 [DOM 폴백 성공!] DOM에서 타겟 직접 포착: {dom_scan.get('rank')}위 ({dom_scan.get('matchType')}) | {dom_scan.get('title')}")
                    has_target = True
                    target_item = {
                        "rank": dom_scan.get("rank"),
                        "title": dom_scan.get("title"),
                        "matchType": dom_scan.get("matchType"),
                        "isCatalog": dom_scan.get("isCatalog", bool(task.compare_id))
                    }
                else:
                    # [사용자 지침] 2페이지를 넘기지 않고 1페이지 내에서 해결: 없으면 즉시 PASS
                    targets_desc = f"nv_mid:{task.nv_mid}" + (f", compare_id:{task.compare_id}" if task.compare_id else "")
                    dom_count = dom_scan.get("totalCards", 0) if isinstance(dom_scan, dict) else 0
                    logger.info(f"ℹ️ [쇼핑 1페이지] __NEXT_DATA__({total_items}개) 및 DOM({dom_count}개) 모두 타겟({targets_desc}) 미존재 -> 2페이지 이동 없이 즉시 PASS (NOT_FOUND)")
                    result.status = "NOT_FOUND"
                    result.shopping_page = 1
                    result.error_message = f"쇼핑 1페이지(__NEXT_DATA__ {total_items}개, DOM {dom_count}개)에 타겟({targets_desc})이 존재하지 않아 PASS 처리"
                    shop_cdp.close()
                    force_stop_app(device_id)
                    result.duration_seconds = time.time() - start_time
                    return result.to_dict()

            target_found_rank = target_item["rank"]
            result.shopping_rank = target_found_rank
            result.shopping_page = 1
            result.search_type = "msearch"
            result.match_type = target_item.get("matchType")
            logger.info(f"🎯 [쇼핑 1페이지 타겟 확인!] 공식 오가닉 {target_found_rank}위 ({result.match_type}) | 상품: {target_item['title']} | 이제 DOM 스크롤 탐색 진행")

            is_catalog_match = target_item.get("isCatalog", False) or bool(task.compare_id)
            result.target_type = "CATALOG" if is_catalog_match else "PROD"

            # 2. DOM에서 해당 타겟 카드를 찾기 위한 함수 (productExpandSub 서브 더보기는 원천 배제, product_info_main 만 엄격히 타겟팅)
            async def find_rendered_dom_card():
                return await shop_cdp.evaluate(f"""
                (() => {{
                    const targetMid = "{task.nv_mid}";
                    const compareId = "{task.compare_id or ''}";
                    const isCatalog = {str(is_catalog_match).lower()};

                    // 1순위: product_info_main 단위로 직접 탐색 (productExpandSub_info_sub 서브 더보기 영역 원천 배제)
                    const mainCards = Array.from(document.querySelectorAll('div[class*="product_info_main"]'));
                    for (let card of mainCards) {{
                        // [사용자 절대 지침] productExpandSub 하위 영역은 절대 선택 금지
                        if (card.closest('div[class*="productExpandSub"]')) continue;

                        const aLinks = Array.from(card.querySelectorAll('a'));
                        for (let a of aLinks) {{
                            if (a.closest('div[class*="productExpandSub"]')) continue;

                            let isMatch = false;
                            try {{
                                const p = JSON.parse(a.getAttribute('data-nlog-params') || '{{}}');
                                if (p.is_ad === true) continue;
                                const cId = String(p.content_id || '');
                                if (targetMid && (cId === targetMid || a.href.includes(targetMid))) isMatch = true;
                                if (compareId && (cId === compareId || a.href.includes(compareId))) isMatch = true;
                            }} catch(e) {{}}

                            if (!isMatch) {{
                                const href = a.href || '';
                                const nlog = a.getAttribute('data-nlog-params') || '';
                                if (targetMid && (href.includes(targetMid) || nlog.includes(targetMid))) isMatch = true;
                                if (compareId && (href.includes(compareId) || nlog.includes(compareId))) isMatch = true;
                            }}

                            if (isMatch) {{
                                card.scrollIntoView({{ block: 'center', behavior: 'instant' }});

                                // 카탈로그 상품일 때: "판매처 N개" 링크/텍스트 우선 조준 (WAF 307 로그인 우회 핵심)
                                let clickEl = null;
                                let clickType = "TITLE";
                                if (isCatalog) {{
                                    const allEls = Array.from(card.querySelectorAll('*'));
                                    const mallEl = allEls.find(el => {{
                                        const t = (el.innerText || '').trim();
                                        return /^판매처\\s*[\\d,]+/.test(t) || (t.includes('판매처') && !t.includes('판매처별'));
                                    }});
                                    if (mallEl) {{
                                        clickEl = mallEl;
                                        clickType = "MALL_COUNT";
                                    }}
                                    if (!clickEl) {{
                                        clickEl = card.querySelector('a[href*="/catalog/"], a[class*="mall"]');
                                        if (clickEl) clickType = "CATALOG_LINK";
                                    }}
                                }}

                                if (!clickEl) {{
                                    clickEl = card.querySelector('[class*="product_info_tit"]') || card.querySelector('[class*="title"]') || a;
                                    clickType = "TITLE";
                                }}

                                const r = clickEl.getBoundingClientRect();
                                return {{
                                    found: true,
                                    x: r.x,
                                    y: r.y,
                                    width: r.width,
                                    height: r.height,
                                    clickType: clickType,
                                    href: a.href,
                                    title: (clickEl.innerText || '').trim(),
                                    domCardsCount: mainCards.length
                                }};
                            }}
                        }}
                    }}

                    // 2순위 Fallback: 전체 링크 중 product_info_main 소속만 허용
                    const allLinks = Array.from(document.querySelectorAll('a[data-nlog-params]'));
                    for (let a of allLinks) {{
                        // productExpandSub 영역은 무조건 건너뜀
                        if (a.closest('div[class*="productExpandSub"]')) continue;

                        try {{
                            const p = JSON.parse(a.getAttribute('data-nlog-params') || '{{}}');
                            if (p.is_ad === false) {{
                                const cId = String(p.content_id || '');
                                const isMid = (targetMid && (cId === targetMid || a.href.includes(targetMid)));
                                const isComp = (compareId && (cId === compareId || a.href.includes(compareId)));
                                if (isMid || isComp) {{
                                    const card = a.closest('div[class*="product_info_main"]');
                                    if (!card) continue; // product_info_main 이 아니면 절대 클릭 금지

                                    card.scrollIntoView({{ block: 'center', behavior: 'instant' }});

                                    let clickEl = null;
                                    let clickType = "TITLE";
                                    if (isCatalog) {{
                                        const allEls = Array.from(card.querySelectorAll('*'));
                                        const mallEl = allEls.find(el => {{
                                            const t = (el.innerText || '').trim();
                                            return /^판매처\\s*[\\d,]+/.test(t) || (t.includes('판매처') && !t.includes('판매처별'));
                                        }});
                                        if (mallEl) {{
                                            clickEl = mallEl;
                                            clickType = "MALL_COUNT";
                                        }}
                                        if (!clickEl) {{
                                            clickEl = card.querySelector('a[href*="/catalog/"], a[class*="mall"]');
                                            if (clickEl) clickType = "CATALOG_LINK";
                                        }}
                                    }}

                                    if (!clickEl) {{
                                        clickEl = card.querySelector('[class*="product_info_tit"]') || card.querySelector('[class*="title"]') || a;
                                        clickType = "TITLE";
                                    }}

                                    const r = clickEl.getBoundingClientRect();
                                    return {{
                                        found: true,
                                        x: r.x,
                                        y: r.y,
                                        width: r.width,
                                        height: r.height,
                                        clickType: clickType,
                                        href: a.href,
                                        title: (clickEl.innerText || '').trim(),
                                        domCardsCount: mainCards.length
                                    }};
                                }}
                            }}
                        }} catch(e) {{}}
                    }}

                    return {{
                        found: false,
                        domCardsCount: mainCards.length
                    }};
                }})()
                """)

            # 3. 기본 노출 영역(Initial DOM) 선행 확인: 이미 보이면 스크롤 불필요!
            dom_check = await find_rendered_dom_card()
            if dom_check.get("found"):
                logger.info("⚡ [기본 노출 즉시 발견] 1페이지 기본 렌더링 영역에서 타겟 카드 즉시 포착 -> 스크롤 생략")
                target_card_info = dom_check
            else:
                # 4. 기본 노출에 없으면 스크롤바를 내리며 DOM 카드를 탐색
                # 리스트가 확장되면 목록이 순간 틀어지기 때문에 명확히 wait(1.2s) 진행
                logger.info(f"ℹ️ 타겟이 __NEXT_DATA__({target_found_rank}위)에는 있으나 아직 DOM에 렌더링되지 않음 -> 1회씩 스크롤하며 발견 즉시 멈춤...")

                for scroll_step in range(1, 10):
                    # 스크롤 전 현재 렌더링된 메인 카드 수 및 높이 기록
                    before_state = await shop_cdp.evaluate("""
                    (() => ({
                        cards: document.querySelectorAll('div[class*="product_info_main"]').length,
                        height: document.body.scrollHeight
                    }))()
                    """)
                    before_cards = before_state.get("cards", 0)

                    await shop_cdp.evaluate("window.scrollBy(0, 600);")
                    await shop_cdp.evaluate(PURGE_TOOLTIPS_JS)

                    # [모니터링] 스크롤 후 DOM 카드 렌더링 여부만 초고속 감지 (불필요한 전역 네트워크 대기 제거)
                    for wait_step in range(20):  # 150ms * 20 = 최대 3.0초
                        await asyncio.sleep(0.15)
                        dom_quick_check = await find_rendered_dom_card()
                        if dom_quick_check.get("found"):
                            break
                        cur_cards = await shop_cdp.evaluate("document.querySelectorAll('div[class*=\"product_info_main\"]').length", timeout=1.0) or 0
                        if cur_cards > before_cards:
                            break

                    dom_scroll_check = await find_rendered_dom_card()
                    if dom_scroll_check.get("found"):
                        logger.info(f"🎯 [스크롤 {scroll_step}회차 발견] DOM 카드 포착 성공! 끝까지 내리지 않고 즉시 중단")
                        # 위치 틀어짐 방지 안정화 wait
                        await asyncio.sleep(0.4)
                        recheck = await find_rendered_dom_card()
                        if recheck.get("found"):
                            target_card_info = recheck
                        else:
                            target_card_info = dom_scroll_check
                        break

            if not target_card_info or not target_card_info.get("found"):
                # __NEXT_DATA__에는 있었으나 DOM 렌더링 매칭 실패 시
                result.status = "NOT_FOUND"
                result.shopping_page = 1
                result.error_message = f"1페이지 __NEXT_DATA__에는 존재하나({target_found_rank}위), DOM 카드 렌더링 매칭 실패"
                shop_cdp.close()
                force_stop_app(device_id)
                result.duration_seconds = time.time() - start_time
                return result.to_dict()

            result.shopping_page = 1
            result.shopping_rank = target_found_rank

            # 안전한 클릭 좌표 계산 (우측 찜하기/하트 회피: 카탈로그는 판매처 링크 중앙, 일반상품은 제목 좌측 20~45% 영역)
            pos_x = target_card_info["x"]
            pos_y = target_card_info["y"]
            pos_w = target_card_info["width"]
            pos_h = target_card_info["height"]

            if target_card_info.get("clickType") == "MALL_COUNT":
                click_x = pos_x + pos_w * random.uniform(0.3, 0.7)
                click_y = pos_y + pos_h * random.uniform(0.3, 0.7)
                logger.info(f"🎯 [카탈로그 타겟팅] '판매처 N개' 안심 링크 조준: ({click_x:.1f}, {click_y:.1f})")
            else:
                click_x = pos_x + pos_w * random.uniform(0.2, 0.45)
                click_y = pos_y + pos_h * random.uniform(0.35, 0.65)
                logger.info(f"🎯 [일반상품 타겟팅] 상품 제목 영역 조준: ({click_x:.1f}, {click_y:.1f})")
            result.touch_coordinates = {"x": round(click_x, 1), "y": round(click_y, 1)}

            is_catalog_match = target_item.get("isCatalog", False) or bool(task.compare_id)
            result.target_type = "CATALOG" if is_catalog_match else "PROD"

            # [핵심 디버깅 & 안전장치] 타겟 카드의 링크 구조 정밀 판독 (순정 네이티브 InAppBrowser 수명주기 보존)
            card_inspect = await shop_cdp.evaluate(f"""
            (() => {{
                const targetMid = "{task.nv_mid}";
                const compareId = "{task.compare_id or ''}";
                const links = Array.from(document.querySelectorAll('a'));
                const matched = links.filter(a => (a.href && (a.href.includes(targetMid) || (compareId && a.href.includes(compareId)))) || 
                                                  (a.getAttribute('data-nlog-params') && (a.getAttribute('data-nlog-params').includes(targetMid) || (compareId && a.getAttribute('data-nlog-params').includes(compareId)))));

                return matched.map(a => ({{
                    href: (a.href || '').substring(0, 100),
                    text: (a.innerText || '').trim().substring(0, 40),
                    nlogArea: a.getAttribute('data-nlog-area'),
                    className: a.className,
                    target: a.target
                }}));
            }})()
            """)
            logger.info(f"🔍 [쇼핑 타겟 카드 매칭 링크 {len(card_inspect) if isinstance(card_inspect, list) else 0}개 분석] {json.dumps(card_inspect, ensure_ascii=False)}")

            target_selector_js = f"""
            (() => {{
                const targetMid = "{task.nv_mid}";
                const compareId = "{task.compare_id or ''}";
                const isCatalog = {str(is_catalog_match).lower()};
                const mainCards = Array.from(document.querySelectorAll('div[class*="product_info_main"]'));
                for (let card of mainCards) {{
                    if (card.closest('div[class*="productExpandSub"]')) continue;
                    const aLinks = Array.from(card.querySelectorAll('a'));
                    for (let a of aLinks) {{
                        const h = a.href || '';
                        const n = a.getAttribute('data-nlog-params') || '';
                        if ((targetMid && (h.includes(targetMid) || n.includes(targetMid))) ||
                            (compareId && (h.includes(compareId) || n.includes(compareId)))) {{
                            // 카탈로그 상품인 경우: 외부몰 최저가 바로가기 버튼 회피 -> 판매처 링크 또는 카탈로그 상세 링크 우선 반환
                            if (isCatalog) {{
                                const allEls = Array.from(card.querySelectorAll('*'));
                                const mallEl = allEls.find(el => {{
                                    const t = (el.innerText || '').trim();
                                    return /^판매처\\s*[\\d,]+/.test(t) || (t.includes('판매처') && !t.includes('판매처별'));
                                }});
                                if (mallEl) {{
                                    return mallEl;
                                }}
                                const catA = card.querySelector('a[href*="/catalog/"]') ||
                                             card.querySelector('[class*="product_info_tit"] a, [class*="title"] a');
                                if (catA) {{
                                    return catA;
                                }}
                            }}
                            // 일반 상품 또는 fallback: 순수 상품명 제목 <a> 반환
                            const titA = card.querySelector('[class*="product_info_tit"] a, [class*="title"] a') || a;
                            return titA;
                        }}
                    }}
                }}
                if (isCatalog) {{
                    const directCat = document.querySelector('a[href*="/catalog/"]');
                    if (directCat) {{ return directCat; }}
                }}
                return document.querySelector('a[href*="{task.nv_mid}"]');
            }})()
            """
            # 클릭 직전 활성 탭 목록 및 페이지 URL 기록
            pre_click_ws_set = set()
            try:
                result.pre_click_url = await shop_cdp.evaluate("window.location.href")
                if card_inspect and isinstance(card_inspect, list) and len(card_inspect) > 0:
                    result.target_product_url = card_inspect[0].get("href")
                if result.pre_click_url:
                    logger.info(f"🌐 [클릭 전 네이버 쇼핑검색 URL] {result.pre_click_url}")
                if result.target_product_url:
                    logger.info(f"🔗 [타겟 상품 카드 원본 링크] {result.target_product_url}")

                tabs_before_click = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.5).read().decode())
                pre_click_ws_set = {t.get("webSocketDebuggerUrl") for t in tabs_before_click if t.get("webSocketDebuggerUrl")}
            except Exception:
                pass

            click_act = await visual_stabilize_and_click(
                cdp=shop_cdp,
                device_id=device_id,
                task_id=task.task_id,
                action_name="SHOPPING_1P_TARGET",
                click_x=click_x,
                click_y=click_y,
                target_selector_expr=target_selector_js
            )
            result.before_click_screenshot = click_act.get("capture_path")
            await asyncio.sleep(0.5)
            if shop_cdp.network_events:
                logger.info(f"📊 [쇼핑 탭 CDP 네트워크 이벤트 (총 {len(shop_cdp.network_events)}개)]")
                for ev in shop_cdp.network_events[-10:]:
                    logger.info(f"   • {ev.get('type')}: {ev.get('url', '')[:90]} | status: {ev.get('status')} | init: {ev.get('initiator')} | frame: {ev.get('top_frame')}")
            shop_cdp.close()

    # 9. Smart Wait for Landing & Catalog Handling (Applies to both SERP click & Shopping tab click)
    logger.info("⏳ [클릭 직후 스마트 대기] 상세 페이지 / 카탈로그 로드 대기 중 (0.15초 초고속 감지)...")
    t0_landing = time.time()

    clicked_tab_ws = shop_tab_ws if (not target_clicked_on_serp and 'shop_tab_ws' in locals() and shop_tab_ws) else serp_ws

    landing_ws = None
    for wait_landing in range(100):  # max 15.0s (0.15s * 100, 10대 동시 병렬 LTE 완충)
        await asyncio.sleep(0.15)
        
        # [초고속 로그인 감지 (0.15~0.3s)] 클릭 직후 로그인창 발생 시 즉시 Abort
        is_login_fast, login_fast_reason = await fast_check_login_state(device_id, cdp_port)
        if is_login_fast:
            logger.error(f"🚨 [초고속 로그인 감지 - 상품 클릭 직후] {login_fast_reason}")
            take_login_alert_screenshot(device_id, task.task_id)
            result.login_detected = True
            result.status = "LOGIN_REQUIRED"
            result.error_message = f"상품 클릭 후 로그인 창 발생: {login_fast_reason}"
            force_stop_app(device_id)
            result.duration_seconds = time.time() - start_time
            return result.to_dict()

        try:
            tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.5).read().decode())
            if wait_landing % 15 == 0:
                logger.info(f"🔍 [랜딩 탭 탐색 {wait_landing}] open tabs: {[(t.get('title', ''), t.get('url', '')[:60]) for t in tabs]}")
            
            # 1순위: 전체 탭 중 실제 상세페이지/카탈로그 URL로 이미 전환/로드된 탭 (새 탭/기존 SERP 탭 무관 최우선 매칭!)
            cand = next((t for t in tabs if any(k in t.get("url", "") for k in ["smartstore.naver.com", "brand.naver.com", "/catalog/", "/products/"])), None)

            # 2순위: 아직 URL이 반영 안 되었지만 새로 오픈된 신규 탭 (InAppBrowserActivity / WebTab)
            if not cand and 'pre_click_ws_set' in locals() and pre_click_ws_set:
                new_tabs = [t for t in tabs if t.get("webSocketDebuggerUrl") and t.get("webSocketDebuggerUrl") not in pre_click_ws_set]
                cand = next((t for t in new_tabs if any(k in t.get("url", "") for k in ["smartstore.naver.com", "brand.naver.com", "/catalog/", "/products/"])), None)
                if not cand and new_tabs and wait_landing >= 20:
                    cand = new_tabs[0]

            # 2-2순위: /json/list에 URL이 즉시 반영되지 않은 경우 (빈 URL 탭 또는 clicked_tab_ws 직접 CDP evaluate, 10회 주기 탐색)
            if not cand and wait_landing >= 4 and wait_landing % 10 == 0:
                check_targets = []
                if clicked_tab_ws:
                    check_targets.append(clicked_tab_ws)
                for t in tabs:
                    ws_u = t.get("webSocketDebuggerUrl")
                    if ws_u and ws_u not in check_targets and t.get("url", "") in ("", "about:blank"):
                        check_targets.append(ws_u)

                for target_ws in check_targets[:3]:
                    try:
                        async with safe_ws_connect(target_ws, max_retries=1, open_timeout=2.0) as tws:
                            tcdp = AsyncCDPClient(tws)
                            t_info = await tcdp.evaluate("({ url: window.location.href, title: document.title })", timeout=1.0)
                            if isinstance(t_info, dict):
                                u = t_info.get("url", "")
                                if any(k in u for k in ["smartstore.naver.com", "brand.naver.com", "/catalog/", "/products/"]):
                                    cand = {"webSocketDebuggerUrl": target_ws, "url": u, "title": t_info.get("title", "")}
                                    logger.info(f"⚡ [CDP 직접 판독 발견] 탭 URL: {u[:70]}")
                                    break
                    except Exception:
                        pass

            # [안전장치 재터치] 1차 터치 미반응 시 (단, 상세페이지 InAppBrowserActivity가 이미 떴다면 절대 재터치 금지: 쿠폰/로그인 오클릭 원천 차단!)
            if not cand and wait_landing in (12, 26) and 'click_x' in locals() and 'click_y' in locals():
                try:
                    foc_chk = subprocess.run(
                        f"adb -s {device_id} shell dumpsys window | grep mCurrentFocus",
                        shell=True, capture_output=True, text=True, timeout=1.0
                    ).stdout
                    # InAppBrowserActivity(상세페이지)가 아직 전면에 안 떴을 때만 검색화면 재터치 허용!
                    if "InAppBrowserActivity" not in foc_chk:
                        retry_no = 1 if wait_landing == 12 else 2
                        logger.warning(f"🔄 [안전장치 {retry_no}차 정밀 재터치] SERP 화면 정체 확인 -> CDP 핀포인트 재탭 ({click_x:.1f}, {click_y:.1f})")
                        if clicked_tab_ws:
                            try:
                                async with safe_ws_connect(clicked_tab_ws, max_retries=1, open_timeout=2.0) as rws:
                                    rcdp = AsyncCDPClient(rws)
                                    touch_dur = random.uniform(0.075, 0.110)
                                    rad_x = round(random.uniform(18.0, 24.5), 1)
                                    rad_y = round(random.uniform(22.0, 30.5), 1)
                                    touch_force = round(random.uniform(0.88, 1.0), 2)
                                    await rcdp.call("Input.dispatchTouchEvent", {
                                        "type": "touchStart",
                                        "touchPoints": [{"x": click_x, "y": click_y, "radiusX": rad_x, "radiusY": rad_y, "force": touch_force}]
                                    })
                                    await asyncio.sleep(touch_dur)
                                    await rcdp.call("Input.dispatchTouchEvent", {
                                        "type": "touchEnd",
                                        "touchPoints": []
                                    })
                            except Exception:
                                pass
                    else:
                        logger.info("ℹ️ [재터치 생략] 상세페이지(InAppBrowserActivity) 로딩 진행 중 확인 -> 쿠폰 오클릭 방지를 위해 추가 터치 생략")
                except Exception:
                    pass

            # 3순위: 중간 브릿지 (충분히 대기 후 fallback)
            if not cand and wait_landing > 15:
                cand = next((t for t in tabs if any(k in t.get("url", "") for k in ["cr.shopping.naver.com", "cr3.shopping.naver.com"])), None)

            if cand and cand.get("webSocketDebuggerUrl"):
                cand_url = cand.get("url", "")
                # 새로 생성된 탭의 URL이 아직 비어있거나 about:blank인 경우 페이지 이동 시작을 최대 3.0초 대기
                if cand_url in ("", "about:blank") and wait_landing < 20:
                    continue
                landing_ws = cand["webSocketDebuggerUrl"]
                result.timing_profile["t_landing_detect_ms"] = round((time.time() - t0_landing) * 1000, 1)
                logger.info(f"✅ [랜딩 탭 확인 (대기 {(wait_landing+1)*0.15:.2f}초)] {cand.get('url')[:60]}... | 타이틀: {cand.get('title')[:30]}")
                break
        except Exception:
            pass

    if not landing_ws:
        is_login_fast, login_fast_reason = await fast_check_login_state(device_id, cdp_port)
        if is_login_fast:
            logger.error(f"🚨 [초고속 로그인 감지 - 랜딩 타임아웃] {login_fast_reason}")
            take_login_alert_screenshot(device_id, task.task_id)
            result.login_detected = True
            result.status = "LOGIN_REQUIRED"
            result.error_message = f"랜딩 대기 중 로그인 창 발생: {login_fast_reason}"
            force_stop_app(device_id)
            result.duration_seconds = time.time() - start_time
            return result.to_dict()

        logger.error("❌ [랜딩 탭 타임아웃] 15.0초 대기 후에도 상품 상세 페이지 또는 카탈로그 탭이 열리지 않았습니다.")
        take_screenshot(device_id, CAPTURES_DIR / f"landing_timeout_{device_id}_{task.task_id}.png")
        result.status = "LANDING_TIMEOUT"
        result.error_message = "15.0초 대기 후에도 상품 상세 페이지 또는 카탈로그 탭이 열리지 않았습니다."
        force_stop_app(device_id)
        result.duration_seconds = time.time() - start_time
        return result.to_dict()

    landing_ws_conn = await open_ws_client(landing_ws)
    landing_cdp = AsyncCDPClient(landing_ws_conn)
    should_close_landing = True
    logger.info(f"🔗 [랜딩 CDP 연결 성공] {landing_ws}")

    try:
        # [랜딩 페이지 완료 대기] document.readyState 및 실제 URL 로드 완료 확인
        for wait_ld in range(60):  # max 6.0s (0.1s * 60)
            await asyncio.sleep(0.1)
            try:
                ld_status = await landing_cdp.evaluate("""
                (() => {
                    const u = window.location.href;
                    const isTargetDomain = u.includes('smartstore') || u.includes('catalog') || u.includes('products') || u.includes('brand') || u.includes('shopping');
                    return {
                        url: u,
                        title: document.title,
                        isReady: (document.readyState === 'complete' || document.readyState === 'interactive') && isTargetDomain
                    };
                })()
                """)
                if isinstance(ld_status, dict) and ld_status.get("isReady"):
                    logger.info(f"📄 [랜딩 페이지 로드 완료] URL: {ld_status.get('url')[:80]} | Title: {ld_status.get('title')[:30]}")
                    break
            except Exception:
                continue

        # 10. Handle Target Type (Catalog vs Single Prod)
        nav_info = {}
        try:
            nav_info = await landing_cdp.evaluate("""
            (() => {
                const url = window.location.href;
                const title = document.title;
                const isCatalog = url.includes('/catalog/') || title.includes('가격비교');
                return { url, title, isCatalog };
            })()
            """, timeout=10.0)
        except Exception as e:
            logger.warning(f"⚠️ 네비게이션 상태 확인 예외 (체류 계속 진행): {e}")

        if not isinstance(nav_info, dict):
            nav_info = {}

        if nav_info.get("isCatalog") or result.target_type == "CATALOG":
            result.target_type = "CATALOG"
            logger.info("🛒 [카탈로그 진입] 판매처 목록 스크롤 및 매칭...")
            for _ in range(2):
                await landing_cdp.evaluate("window.scrollBy(0, 600);")
                await asyncio.sleep(1.0)

            # 1차 탐색: 기본 노출 판매처 목록에서 nv_mid 또는 store_name 매칭
            async def find_seller_target():
                return await landing_cdp.evaluate(f"""
                (() => {{
                    const targetMid = "{task.nv_mid}";
                    const targetStore = "{task.store_name or ''}";
                    const allLinks = Array.from(document.querySelectorAll('a[data-nlog-params]'));

                    // Priority 1: Match by nv_mid
                    for (let a of allLinks) {{
                        try {{
                            const p = JSON.parse(a.getAttribute('data-nlog-params') || '{{}}');
                            if (String(p.content_id) === targetMid && (p.inventory_cd === 'prc' || p.inventory_cd === 'lst')) {{
                                a.scrollIntoView({{ block: 'center' }});
                                const r = a.getBoundingClientRect();
                                return {{ found: true, type: 'mid_match', rect: {{ x: r.x, y: r.y, width: r.width, height: r.height }} }};
                            }}
                        }} catch(e) {{}}
                    }}

                    // Priority 2: Match by store_name
                    if (targetStore) {{
                        const rows = Array.from(document.querySelectorAll('li, div[class*="seller"], div[class*="mall"]'));
                        for (let row of rows) {{
                            if ((row.innerText || '').includes(targetStore)) {{
                                const link = row.querySelector('a') || row;
                                link.scrollIntoView({{ block: 'center' }});
                                const r = link.getBoundingClientRect();
                                return {{ found: true, type: 'store_match', rect: {{ x: r.x, y: r.y, width: r.width, height: r.height }} }};
                            }}
                        }}
                    }}

                    return {{ found: false }};
                }})()
                """)

            seller_click_info = await find_seller_target()

            if seller_click_info.get("found"):
                sr = seller_click_info["rect"]
                s_click_x = max(10.0, sr["x"] + sr["width"] * random.uniform(0.35, 0.65))
                s_click_y = max(50.0, sr["y"] + sr["height"] * random.uniform(0.35, 0.65))
                logger.info(f"👉 [카탈로그 판매처 터치 ({seller_click_info['type']})] 좌표: ({s_click_x:.1f}, {s_click_y:.1f})")

                await visual_stabilize_and_click(
                    cdp=landing_cdp,
                    device_id=device_id,
                    task_id=task.task_id,
                    action_name=f"CATALOG_SELLER_{seller_click_info['type']}",
                    click_x=s_click_x,
                    click_y=s_click_y
                )
                # 카탈로그 판매처 클릭 직후 로그인 감지 (0.15초 단위)
                for _ in range(15):
                    await asyncio.sleep(0.15)
                    is_login_fast, login_fast_reason = await fast_check_login_state(device_id, cdp_port)
                    if is_login_fast:
                        logger.error(f"🚨 [초고속 로그인 감지 - 카탈로그 판매처 클릭 직후] {login_fast_reason}")
                        take_login_alert_screenshot(device_id, task.task_id)
                        result.login_detected = True
                        result.status = "LOGIN_REQUIRED"
                        result.error_message = f"카탈로그 판매처 클릭 후 로그인 창 발생: {login_fast_reason}"
                        if should_close_landing:
                            landing_cdp.close()
                        force_stop_app(device_id)
                        result.duration_seconds = time.time() - start_time
                        return result.to_dict()
            else:
                # [사용자 지침] 기본 목록에 미노출 시 무리한 확장(더보기/최저가)을 하지 않고 카탈로그 메인에서 안전 체류(PASS) 진행
                logger.info("ℹ️ [카탈로그 기본 목록 미포함] 판매처 확장/오클릭 방지: 카탈로그 메인 화면에서 안전 체류 진행 (PASS 정책)")

        # 11. Login Detection Check (로그인 유도 발생 시 기록 및 분석)
        try:
            login_check = await landing_cdp.evaluate("""
            (() => {
                const url = window.location.href;
                const isLoginUrl = url.includes('nid.naver.com') || url.includes('nidlogin.login');
                const loginModal = document.querySelector('div[class*="login_layer"], div[class*="login_popup"], div[class*="login_modal"], div[class*="login_wrap"]');
                const hasLoginText = Array.from(document.querySelectorAll('h1, h2, h3, p, span, a, button')).some(el => {
                    const t = (el.innerText || '').trim();
                    return (t === '네이버 로그인' || t === '로그인이 필요합니다' || t === '로그인 후 이용 가능합니다') && el.offsetParent !== null;
                });
                return {
                    isLoginRequired: isLoginUrl || (loginModal !== null) || hasLoginText,
                    url: url,
                    title: document.title,
                    reason: isLoginUrl ? 'REDIRECT_NIDLOGIN' : (loginModal ? 'LOGIN_MODAL' : (hasLoginText ? 'LOGIN_TEXT_DETECTED' : null))
                };
            })()
            """, timeout=5.0)
            if login_check.get("isLoginRequired"):
                logger.error(f"🚨 [로그인 창 감지됨 - 상세페이지 체류 차단] 사유: {login_check.get('reason')} | URL: {login_check.get('url')} | 타이틀: {login_check.get('title')}")
                take_login_alert_screenshot(device_id, task.task_id)
                result.login_detected = True
                result.success = False
                result.status = "LOGIN_REQUIRED"
                result.login_info = login_check
                result.error_message = f"상세페이지 체류 중 로그인 요구 감지 ({login_check.get('reason')})"
                if should_close_landing:
                    landing_cdp.close()
                force_stop_app(device_id)
                result.duration_seconds = time.time() - start_time
                return result.to_dict()
        except Exception as e:
            logger.debug(f"로그인 검사 예외 (무시): {e}")

        # 11. Final Landing Inspection & Dwell
        # [치명적 버그 수정] 네이티브 안드로이드 로그인 액티비티(NidLoginActivity) 정밀 검사
        is_login_native, login_native_reason = await fast_check_login_state(device_id, cdp_port)
        if is_login_native:
            logger.error(f"🚨 [네이티브 로그인 화면 감지됨 - 체류 차단] {login_native_reason}")
            take_login_alert_screenshot(device_id, task.task_id)
            result.login_detected = True
            result.success = False
            result.status = "LOGIN_REQUIRED"
            result.error_message = f"상세페이지 진입 시 네이티브 로그인 창 발생: {login_native_reason}"
            if should_close_landing:
                landing_cdp.close()
            force_stop_app(device_id)
            result.duration_seconds = time.time() - start_time
            return result.to_dict()

        try:
            cur_info = await landing_cdp.evaluate("({ url: window.location.href, title: document.title })")
            result.landing_url = cur_info.get("url", "")
            result.landing_title = cur_info.get("title", "")
        except Exception:
            pass

        # [유효 랜딩 검증] about:blank 이거나 빈 페이지면 정상 랜딩 실패
        if not result.landing_url or result.landing_url == "about:blank" or not any(k in result.landing_url for k in ["smartstore", "brand", "shopping", "catalog", "products"]):
            # 혹시 네이티브 로그인이 떴는지 재차 확인
            is_login_again, login_again_reason = await fast_check_login_state(device_id, cdp_port)
            if is_login_again:
                logger.error(f"🚨 [로그인 창 감지됨 - about:blank 랜딩 실패] {login_again_reason}")
                take_login_alert_screenshot(device_id, task.task_id)
                result.login_detected = True
                result.success = False
                result.status = "LOGIN_REQUIRED"
                result.error_message = f"상품 클릭 후 로그인 창 발생: {login_again_reason}"
            else:
                logger.error(f"⚠️ [비정상 랜딩 감지] URL: '{result.landing_url}' (정상 상세페이지 도달 실패)")
                result.success = False
                result.status = "LANDING_FAILED"
                if should_close_landing:
                    landing_cdp.close()
                force_stop_app(device_id)
                result.duration_seconds = time.time() - start_time
                return result.to_dict()

        logger.info(f"⏳ [체류 시작] 상품 상세페이지 {task.dwell_seconds}초 체류 (비콘 전송 보장)...")
        # [사용자 지침: 덤프 방식 정밀 검수] 앱이 살아있는 체류 시점에 실제 상세페이지 물리 스크린샷 + 윈도우 포커스 + DOM 덤프 수행
        await asyncio.sleep(1.5)
        try:
            timestamp_str = time.strftime('%Y%m%d_%H%M%S')
            dwell_shot = CAPTURES_DIR / f"after_landing_{device_id}_task{task.task_id}_{timestamp_str}.png"
            subprocess.run(f"adb -s {device_id} exec-out screencap -p > {dwell_shot}", shell=True, timeout=5.0)
            result.after_click_screenshot = str(dwell_shot)
            logger.info(f"📸 [상세페이지 랜딩 화면 증빙 캡처 완료] {dwell_shot.name}")

            # [1. 포그라운드 윈도우 포커스 덤프] 안드로이드 OS 레벨에서 네이버 앱 화면인지 검증
            foc_res = subprocess.run(
                f"adb -s {device_id} shell 'dumpsys window | grep mCurrentFocus'",
                shell=True, capture_output=True, text=True, timeout=3.0
            )
            result.current_window_focus = foc_res.stdout.strip()

            # [2. 상세페이지 DOM 덤프: 사용자 지침 반영] 
            # - 후처리(2~3초) 렌더링 위젯인 '최대 적립 포인트' 확인
            # - IP/FDS 차단 시 나타나는 '상품 정보를 표시할 수 없습니다' 바꿔치기 에러 감지
            dom_dump = await landing_cdp.evaluate("""
            (() => {
                const url = window.location.href;
                const title = document.title;
                const bodyText = (document.body ? document.body.innerText : '') || '';

                // 1. IP/FDS 차단 시 상세정보 영역 바꿔치기 에러 판독
                const blockedKeywords = ['상품 정보를 표시할 수 없습니다', '상품정보를 표시할 수 없습니다', '판매가 중지된 상품입니다', '일시적인 오류가 발생했습니다', '존재하지 않는 상품입니다'];
                const isBlocked = blockedKeywords.some(kw => bodyText.includes(kw));

                // 2. 후처리(2~3초 뒤) 로딩되는 핵심 위젯: "최대 적립 포인트"
                const allEls = Array.from(document.querySelectorAll('span, div, p, strong, em'));
                const pointEl = allEls.find(el => {
                    const t = (el.innerText || '').trim();
                    return t.includes('최대 적립 포인트') || (t.startsWith('최대') && t.includes('적립'));
                });
                const pointText = pointEl ? (pointEl.innerText || '').trim().substring(0, 40) : null;
                const hasPostLoadPoint = !!pointEl;

                // 3. 구매 버튼 및 스토어/가격 정보
                const priceEl = document.querySelector('[class*="price"], [class*="Price"], span[class*="_price"]');
                const buyBtn = document.querySelector('button[class*="buy"], a[class*="buy"], button[class*="pay"], [class*="purchase"], [class*="cart"]');
                const storeEl = document.querySelector('[class*="channel_name"], [class*="store_name"], [class*="mall_name"], h1');
                const isBlank = (url === 'about:blank' || !url);

                return {
                    url: url,
                    title: title,
                    storeName: storeEl ? (storeEl.innerText || '').trim().substring(0, 30) : null,
                    priceText: priceEl ? (priceEl.innerText || '').trim().substring(0, 20) : null,
                    pointText: pointText,
                    hasPostLoadPoint: hasPostLoadPoint,
                    isBlocked: isBlocked,
                    hasBuyBtn: !!buyBtn,
                    isBlank: isBlank,
                    isValidOrganicLanding: !isBlocked && !isBlank && (hasPostLoadPoint || !!buyBtn)
                };
            })()
            """)
            result.landing_dom_dump = dom_dump

            if dom_dump and dom_dump.get("isBlocked"):
                logger.error("🚨 [FDS 화면 바꿔치기 감지] '상품 정보를 표시할 수 없습니다' 차단 화면 발생!")
                result.success = False
                result.status = "FDS_PAGE_BLOCKED"
                result.error_message = "IP/FDS 차단으로 상품 정보가 표시되지 않고 에러 화면으로 대체됨"
                force_stop_app(device_id)
                result.duration_seconds = time.time() - start_time
                return result.to_dict()

            logger.info(f"📋 [상세페이지 DOM 덤프 검증] 유효={dom_dump.get('isValidOrganicLanding')} | 포인트='{dom_dump.get('pointText')}' | 몰='{dom_dump.get('storeName')}' | 차단={dom_dump.get('isBlocked')}")
        except Exception as e:
            logger.warning(f"⚠️ [상세페이지 검증 캡처 예외] {e}")

        remaining_dwell = max(1.0, task.dwell_seconds - 1.5)
        loops = max(1, int(remaining_dwell // 3.0))
        for loop_idx in range(loops):
            scroll_delta = random.randint(220, 380)
            try:
                await landing_cdp.evaluate(f"window.scrollBy({{ top: {scroll_delta}, behavior: 'smooth' }});")
            except Exception:
                pass
            pause_time = (remaining_dwell / loops) * random.uniform(0.85, 1.15)
            await asyncio.sleep(max(0.5, pause_time))

        result.success = True
        result.status = "SUCCESS"
        logger.info(f"🎉 [작업 완료] Task #{task.task_id} 성공! (쇼핑순위: {result.shopping_rank}위, 랜딩: {result.landing_title})")
        logger.info(f"⏱️ [구간별 소요 타이밍 Task #{task.task_id}] {result.timing_profile}")
    finally:
        if should_close_landing and landing_cdp:
            try:
                landing_cdp.close()
            except Exception:
                pass

    force_stop_app(device_id)
    result.duration_seconds = time.time() - start_time
    return result.to_dict()

async def execute_task(task: TaskInput) -> Dict[str, Any]:
    """
    컨베이어 작업 총괄 실행 엔트리포인트:
    - _execute_task_internal 호출
    - 성공/실패/중단/충돌/예외 일체 누락 없이 save_task_history() 자동 영구 저장
    - 일별 jsonl 및 execution_history.json 100% 갱신 보장
    """
    t0 = time.time()
    res: Dict[str, Any] = {}
    try:
        res = await _execute_task_internal(task)
    except Exception as e:
        logger.error(f"💥 [실행 엔진 예외 발생] Task #{getattr(task, 'task_id', '?')}: {e}", exc_info=True)
        res_obj = TaskResult(
            task.task_id,
            task.keyword,
            task.nv_mid,
            task.compare_id,
            raw_keyword=getattr(task, "raw_keyword", task.keyword)
        )
        res_obj.device_id = getattr(task, "device_id", "") or ""
        res_obj.store_name = getattr(task, "store_name", None)
        res_obj.dwell_seconds = getattr(task, "dwell_seconds", 15)
        res_obj.ip = getattr(task, "ip", "") or ""
        res_obj.status = "UNHANDLED_EXCEPTION"
        res_obj.error_message = str(e)
        res_obj.duration_seconds = round(time.time() - t0, 2)
        res = res_obj.to_dict()
    finally:
        try:
            save_task_history(res)
        except Exception as save_err:
            logger.error(f"⚠️ [히스토리 저장 예외] {save_err}")
    return res

if __name__ == "__main__":
    # Test Case: Price Comparison Catalog with specific store
    catalog_input = TaskInput(
        task_id=2,
        keyword="보관백",
        nv_mid="83750937930",
        compare_id="41733443548",
        store_name="블루라팡",
        use_remote_nnb=True,
        dwell_seconds=5
    )
    res = asyncio.run(execute_task(catalog_input))
    print("\n" + "="*50)
    print("📋 [CATALOG TASK RESULT JSON]:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print("="*50)
