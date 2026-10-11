#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daemon_pool_maintainer.py

네이버 정품 NNB + BUC 1200초 미만 신규 숙성 풀 유지 데몬
- 1200초(20분) 미만인 신규 토큰이 3,000개 미만이면 계속 생성하여 유지
- 매 초 단위로 MariaDB nnbs 테이블 감시
- 부족분 발생 시 lcs.naver.com/m 초고속 병렬 패킷 호출로 즉시 자동 충전
"""

import sys
import os
import time
import signal
from datetime import datetime

# 작업 디렉토리 경로 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import TARGET_FRESH_POOL, MIN_AGING_SECONDS, CHECK_INTERVAL_SECONDS
from database import get_db_cursor
from core.fast_harvester import harvest_and_insert_batch

RUNNING = True

def handle_exit(signum, frame):
    global RUNNING
    print(f"\n[!] 종료 시그널 수신 ({signum}). 데몬을 안전하게 종료합니다...")
    RUNNING = False

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

def get_fresh_nnb_count(max_age_seconds: int = MIN_AGING_SECONDS) -> int:
    """1200초 미만인 신규 숙성 NNB 수량 조회"""
    with get_db_cursor(commit=False) as (cur, _):
        cur.execute("""
            SELECT COUNT(*) AS fresh_count
            FROM nnbs
            WHERE status IN ('AGING', 'READY', 'ACTIVE')
              AND created_at > NOW() - INTERVAL %s SECOND
        """, (max_age_seconds,))
        row = cur.fetchone()
        return int(row["fresh_count"] or 0)

def run_maintainer():
    print("=" * 65)
    print("🚀 [NNB Pool Maintainer] 1200초 미만 3,000개 신규 상시 유지 데몬 시작")
    print(f"🎯 목표 수량 : 1200초({MIN_AGING_SECONDS}초) 미만 토큰 {TARGET_FRESH_POOL:,}개 항시 유지")
    print(f"⏱️ 감시 주기 : {CHECK_INTERVAL_SECONDS}초")
    print("=" * 65)

    last_log_time = 0

    while RUNNING:
        try:
            current_fresh = get_fresh_nnb_count()
            needed = TARGET_FRESH_POOL - current_fresh

            if needed > 0:
                # 부족분 발생 시 즉시 채굴 충전 (한 번에 최대 60개씩 병렬 채굴)
                batch_size = min(needed, 60)
                now_str = datetime.now().strftime("%H:%M:%S")
                print(f"[{now_str}] 🌾 신규 부족 감지: 1200초 미만 현재 {current_fresh:,}개 / 목표 {TARGET_FRESH_POOL:,}개 (부족: {needed:,}개) -> {batch_size}개 채굴 중...")

                t0 = time.time()
                inserted = harvest_and_insert_batch(count=batch_size, max_workers=15)
                dur = round(time.time() - t0, 2)

                after_count = get_fresh_nnb_count()
                print(f"[{now_str}] ✅ {inserted}개 적재 완료 ({dur}초) -> 1200초 미만 현재 {after_count:,} / {TARGET_FRESH_POOL:,}개")

                # 아직 부족분이 많이 남아있으면 대기 없이 즉시 다음 배치 실행
                if after_count < TARGET_FRESH_POOL:
                    time.sleep(0.05)
                    continue

            else:
                # 3,000개 충족 상태
                now = time.time()
                if now - last_log_time >= 10:  # 10초마다 상태 알림
                    now_str = datetime.now().strftime("%H:%M:%S")
                    print(f"[{now_str}] 🟢 [정상 유지] 1200초 미만 토큰: {current_fresh:,}개 (목표 {TARGET_FRESH_POOL:,}개 충족 중)")
                    last_log_time = now

            # 초 단위 주기 대기
            time.sleep(CHECK_INTERVAL_SECONDS)

        except Exception as e:
            print(f"❌ [에러] 데몬 루프 중 예외 발생: {e}")
            time.sleep(1.0)

    print("🛑 [NNB Pool Maintainer] 데몬이 정상 종료되었습니다.")

if __name__ == "__main__":
    run_maintainer()
