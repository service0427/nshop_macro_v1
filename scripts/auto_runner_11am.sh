#!/usr/bin/env bash
# ==============================================================================
# scripts/auto_runner_11am.sh
# 
# [자동 예약 실행] 매일 오전 11:00 네이버 쇼핑 랭킹 갱신 시점 자동 기동 스크립트
# - 당일 상품당 100회 상한 캡 적용 (--max-hits-per-item 100)
# - 전일 대비 순위 변화량 자동 추적 및 리포트 보존
# ==============================================================================

set -e
PROJECT_DIR="/home/tech/nshop_macro_v1"
LOG_DIR="${PROJECT_DIR}/logs"
TODAY=$(date +%Y%m%d)

mkdir -p "${LOG_DIR}"
cd "${PROJECT_DIR}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚀 [오전 11시 자동 기동] 마스터 러너 시작..." >> "${LOG_DIR}/scheduler.log"

# 1. 기존 프로세스 점검 및 정리 (중복 기동 방지)
RUNNING_PID=$(pgrep -f "run.py --net-mode" || true)
if [ -n "$RUNNING_PID" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ 기존 실행 중인 run.py(PID: ${RUNNING_PID}) 감지 -> 정상 교체" >> "${LOG_DIR}/scheduler.log"
    pkill -f "run.py --net-mode" || true
    sleep 3
fi

# 2. 마스터 러너 백그라운드 기동 (100타 상한, 10대 축소 모드, LTE 동글 모드, 10회 주기 리포트)
nohup python3 -u run.py --net-mode lte --count 10 --eval-interval 10 --max-hits-per-item 100 >> "${LOG_DIR}/run_master_${TODAY}.log" 2>&1 &
NEW_PID=$!

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ [기동 완료] PID: ${NEW_PID} 로 run.py 기동 (로그: logs/run_master_${TODAY}.log)" >> "${LOG_DIR}/scheduler.log"
echo "$NEW_PID" > "${LOG_DIR}/runner.pid"
