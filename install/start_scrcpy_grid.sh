#!/usr/bin/env bash
# ==============================================================================
# 📱 Smart Grid scrcpy Launcher for All Connected Devices
# ==============================================================================
# Usage:
#   ./scripts/start_scrcpy_grid.sh               # 전체 연결 기기 자동 바둑판(Grid) 정렬 기동
#   ./scripts/start_scrcpy_grid.sh --kill        # 실행 중인 모든 scrcpy 종료
#   ./scripts/start_scrcpy_grid.sh R3CW5084CEW   # 특정 단말기 1대만 단독 실행
#   ./scripts/start_scrcpy_grid.sh --cols 5      # 1행당 5대씩 지정 정렬
# ==============================================================================

set -e

# DISPLAY 환경변수 보정 (xrdp / VNC 환경 대응)
if [ -z "$DISPLAY" ]; then
    if [ -S "/tmp/.X11-unix/X10" ]; then
        export DISPLAY=":10.0"
    elif [ -S "/tmp/.X11-unix/X0" ]; then
        export DISPLAY=":0.0"
    elif [ -S "/tmp/.X11-unix/X1" ]; then
        export DISPLAY=":1.0"
    else
        export DISPLAY=":0"
    fi
fi

# 1. 종료 옵션 (--kill / -k)
if [ "$1" == "--kill" ] || [ "$1" == "-k" ]; then
    echo "🛑 모든 scrcpy 프로세스를 종료합니다..."
    killall -q scrcpy 2>/dev/null || pkill -x scrcpy 2>/dev/null || true
    echo "✓ 종료 완료."
    exit 0
fi

# 2. 단일 기기 단독 실행
if [ -n "$1" ] && [[ "$1" != --* ]]; then
    DEV="$1"
    echo "🚀 단일 기기 scrcpy 실행: $DEV"
    MODEL=$(adb -s "$DEV" shell getprop ro.product.model 2>/dev/null | tr -d '\r\n' || echo "Android")
    scrcpy -s "$DEV" --window-title "$MODEL ($DEV)" --no-audio -m 1024 --max-fps 30 --video-bit-rate 4M
    exit 0
fi

# 3. 기존 scrcpy 프로세스 정리
RUNNING_COUNT=$(pgrep -x scrcpy 2>/dev/null | wc -l || echo "0")
if [ "$RUNNING_COUNT" -gt 0 ]; then
    echo "🔄 기존 실행 중인 scrcpy ($RUNNING_COUNT개) 프로세스를 먼저 정리합니다..."
    killall -q scrcpy 2>/dev/null || pkill -x scrcpy 2>/dev/null || true
    sleep 0.5
fi

# 4. 연결된 기기 목록 수집
DEVICES=($(adb devices | grep -w "device" | awk '{print $1}'))
TOTAL_DEVS=${#DEVICES[@]}

if [ "$TOTAL_DEVS" -eq 0 ]; then
    echo "❌ 연결된 adb 디바이스가 없습니다!"
    exit 1
fi

echo "======================================================================"
echo "📱 [Smart Grid scrcpy] 총 $TOTAL_DEVS대 단말기 감지 완료"
echo " • DISPLAY: $DISPLAY"
echo "======================================================================"

# 5. 화면 해상도 자동 감지 (xdpyinfo / xrandr)
SCREEN_W=1920
SCREEN_H=1080

if command -v xdpyinfo >/dev/null 2>&1; then
    DIMS=$(xdpyinfo 2>/dev/null | grep "dimensions:" | awk '{print $2}' || true)
    if [ -n "$DIMS" ]; then
        DETECTED_W=$(echo "$DIMS" | cut -d'x' -f1)
        DETECTED_H=$(echo "$DIMS" | cut -d'x' -f2)
        if [ -n "$DETECTED_W" ] && [ -n "$DETECTED_H" ]; then
            SCREEN_W=$DETECTED_W
            SCREEN_H=$DETECTED_H
        fi
    fi
fi

echo "🖥️ 감지된 화면 해상도: ${SCREEN_W}x${SCREEN_H}"

# 6. 그리드 레이아웃(열/행/크기/여백) 최적 계산
# 기본 열(Columns) 수 결정
COLS=5
if [ "$TOTAL_DEVS" -le 3 ]; then
    COLS=$TOTAL_DEVS
elif [ "$TOTAL_DEVS" -le 6 ]; then
    COLS=3
elif [ "$TOTAL_DEVS" -le 10 ]; then
    COLS=5
elif [ "$TOTAL_DEVS" -le 12 ]; then
    COLS=6
else
    COLS=6
fi

# 커스텀 --cols 옵션 처리
if [ "$1" == "--cols" ] && [ -n "$2" ]; then
    COLS=$2
fi

ROWS=$(( (TOTAL_DEVS + COLS - 1) / COLS ))

# 여백 및 창 크기 계산
MARGIN_X=10
MARGIN_Y=35
GAP_X=8
GAP_Y=8

AVAIL_W=$(( SCREEN_W - (MARGIN_X * 2) - (GAP_X * (COLS - 1)) ))
AVAIL_H=$(( SCREEN_H - (MARGIN_Y * 2) - (GAP_Y * (ROWS - 1)) ))

WIN_W=$(( AVAIL_W / COLS ))
WIN_H=$(( AVAIL_H / ROWS ))

# 스마트폰 화면비(약 1:2.1~2.2) 보정 및 최대 크기 제한
MAX_RATIO_H=$(( WIN_W * 21 / 10 ))
if [ "$WIN_H" -gt "$MAX_RATIO_H" ]; then
    WIN_H=$MAX_RATIO_H
fi

# 최소 크기 보장
if [ "$WIN_W" -lt 180 ]; then WIN_W=180; fi
if [ "$WIN_H" -lt 360 ]; then WIN_H=360; fi

echo "📐 배치 레이아웃: ${ROWS}행 x ${COLS}열 | 창 크기: ${WIN_W}x${WIN_H} (px)"
echo "----------------------------------------------------------------------"

# 7. scrcpy 스트리밍 최적화 옵션
OPTS="--no-audio -m 1024 --max-fps 30 --video-bit-rate 4M"

# 8. 각 디바이스 순차 배치 기동
IDX=0
for DEV in "${DEVICES[@]}"; do
    COL=$(( IDX % COLS ))
    ROW=$(( IDX / COLS ))

    POS_X=$(( MARGIN_X + COL * (WIN_W + GAP_X) ))
    POS_Y=$(( MARGIN_Y + ROW * (WIN_H + GAP_Y) ))

    MODEL=$(adb -s "$DEV" shell getprop ro.product.model 2>/dev/null | tr -d '\r\n' || echo "Unknown")
    
    # 순정폰 vs 루팅폰 타이틀 구분
    if [ "$DEV" == "R3CW5084CEW" ]; then
        TYPE_LABEL="순정"
    else
        TYPE_LABEL="루팅"
    fi

    NUM_STR=$(printf "%02d" $((IDX + 1)))
    TITLE="[${TYPE_LABEL} ${NUM_STR}] ${MODEL} (${DEV})"

    echo "🚀 [$NUM_STR/$TOTAL_DEVS] $TITLE -> X:$POS_X, Y:$POS_Y, Size:${WIN_W}x${WIN_H}"

    scrcpy -s "$DEV" \
        --window-title "$TITLE" \
        --window-x "$POS_X" \
        --window-y "$POS_Y" \
        --window-width "$WIN_W" \
        --window-height "$WIN_H" \
        $OPTS >/dev/null 2>&1 &

    IDX=$(( IDX + 1 ))
    sleep 0.15
done

echo "======================================================================"
echo "✨ 총 ${TOTAL_DEVS}대 단말기 scrcpy 그리드 뷰어가 모두 백그라운드로 기동되었습니다!"
echo "   (종료 시: $0 --kill)"
echo "======================================================================"
