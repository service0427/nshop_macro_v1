#!/bin/bash
# utils/log_monitor.sh: Minimal Polling Framework
#
# all_packets.jsonl에서 nlogapp 패킷만 감시.
# SCH.all.entry screenview 감지 시 종료.
# 2초 간격 폴링, 마지막 체크 위치부터 새 라인만 읽음.

DEV_ID=$1
LOG_DIR=$2
TARGET_ID=$3

if [ -z "$DEV_ID" ] || [ -z "$LOG_DIR" ]; then
    echo "Usage: ./log_monitor.sh <DEVICE_ID> <LOG_DIR> [TARGET_ID]"
    exit 1
fi

TARGET_NAME=""
TARGET_ADDRESS=""
if [ -n "$TARGET_ID" ]; then
    TARGET_NAME=$(jq -r ".saved_destinations[] | select(.id == \"$TARGET_ID\") | .name" api/route_config.json 2>/dev/null)
    TARGET_ADDRESS=$(jq -r ".saved_destinations[] | select(.id == \"$TARGET_ID\") | .address" api/route_config.json 2>/dev/null)
fi

PACKET_LOG="$LOG_DIR/all_packets.jsonl"
MACRO_EXEC="python3 utils/macro_executor.py"
LAST_LINE=0

# --- State Flags ---
APP_OPEN=false
CONSENT_NEEDED=false
CONSENT_DONE=false
MAIN_LOADED=false
BANNER_DETECTED=false
BANNER_DONE=false
SEARCH_CLICKED=false
SEARCH_ENTERED=false
CLICKER_STARTED=false
SUGGEST_CLICKED=false
POI_LOADED=false
DESTINATION_CLICKED=false
ROUTE_LIST_LOADED=false
CAR_TAB_CLICKED=false
HIPASS_DETECTED=false
HIPASS_DONE=false
SW_ROUTE_CARDS_DETECTED=false
CAR_ROUTE_LOADED=false
SEEN_MAIN=false
SEEN_DISC=false
CAR_TAP_RETRY=0
LAST_CAR_TAP_TIME=0
TARGET_ADDRESS_TAP_RETRY=0
GUIDANCE_CLICKED=false
GUIDANCE_DONE=false
LAST_GUIDANCE_TAP_TIME=0
GUIDANCE_TAP_RETRY=0
BUSINESS_MODAL_DETECTED=false
BUSINESS_MODAL_DETECTED=false
BUSINESS_MODAL_CLICKED=false
BUSINESS_MODAL_DONE=false
DRIVING_STARTED=false
DRIVING_START_TIME=0
CLOVA_TERMS_DETECTED=false
CLOVA_TERMS_DONE=false
SEEN_NAVI_SCREEN_END=false
ROUTE_END_DETECTED=false
GUIDANCE_QUIT_DONE=false
LAST_STALL_CHECK_TIME=0
PREV_REMAINING_DIST="-1.0"
BANNER_WAIT_START=""

GREEN="\e[1;32m"
CYAN="\e[1;36m"
YELLOW="\e[1;33m"
NC="\e[0m"

if [ -n "$TARGET_NAME" ]; then
    echo -e "${CYAN}[Macro:$DEV_ID]${NC} Started. Target: $TARGET_NAME. Waiting for SCH.all.entry..."
else
    echo -e "${CYAN}[Macro:$DEV_ID]${NC} Started. Waiting for SCH.all.entry..."
fi

# Wait for log file
while [ ! -f "$PACKET_LOG" ]; do sleep 0.5; done

NOW() { date +"%H:%M:%S"; }

# === Main Loop ===
while true; do
    sleep 2

    if [ ! -f "$PACKET_LOG" ]; then
        if [ "$APP_OPEN" = true ]; then
            echo -e "${YELLOW}[$(NOW)] [$DEV_ID] waiting for all_packets.jsonl...${NC}"
        fi
        continue
    fi

    TOTAL_LINES=$(wc -l < "$PACKET_LOG")
    if (( LAST_LINE >= TOTAL_LINES + 1 )); then
        if [ "$APP_OPEN" = true ]; then
            echo -e "${YELLOW}[$(NOW)] [$DEV_ID] 새 패킷 없음 (L:$LAST_LINE)${NC}"
        fi
        continue
    fi

    # 전체 패킷을 먼저 읽고, NLOG 전용 필드를 나눔 (heartbeat 무시)
    NEW_PACKETS=$(tail -n +$LAST_LINE "$PACKET_LOG" || true)
    NEW_NLOG=$(echo "$NEW_PACKETS" | grep "nlogapp" | grep -v "heartbeat" || true)
    NLOG_COUNT=0
    if [ -n "$NEW_NLOG" ]; then
        NLOG_COUNT=$(echo "$NEW_NLOG" | wc -l)
    fi

    
    if [ "$APP_OPEN" = true ] && [ -n "$NEW_PACKETS" ]; then
        echo -e "${CYAN}[$(NOW)] [$DEV_ID] +$((TOTAL_LINES - LAST_LINE + 1))줄 (nlogapp: ${NLOG_COUNT}건, L:$TOTAL_LINES)${NC}"
    elif [ "$APP_OPEN" = true ]; then
        echo -e "${YELLOW}[$(NOW)] [$DEV_ID] 새 패킷 없음 (L:$LAST_LINE)${NC}"
    fi

    LAST_LINE=$((TOTAL_LINES + 1))

    if [ -n "$NEW_NLOG" ]; then
        if echo "$NEW_NLOG" | grep -q '"screen_end"' && echo "$NEW_NLOG" | grep -q '"NaviRouteGuidanceFragment"\|"NaviDriveFragment"'; then
            SEEN_NAVI_SCREEN_END=true
        fi
    fi

    if [ -z "$NEW_PACKETS" ]; then
        continue
    fi

    # Step 1: 앱 실행 확인 (launch.app)
    if [ "$APP_OPEN" = false ]; then
        if echo "$NEW_NLOG" | grep -q "launch.app"; then
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 앱 실행 완료${NC}"
            APP_OPEN=true
        fi
    fi

    # Step 2: 약관동의 확인 + 액션
    if [ "$APP_OPEN" = true ] && [ "$CONSENT_DONE" = false ]; then
        # ConsentRequestFragment screen_start 감지 = 약관 화면 떴음
        if [ "$CONSENT_NEEDED" = false ]; then
            if echo "$NEW_NLOG" | grep -q '"screen_start"[^}]*"ConsentRequestFragment"'; then
                echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 약관 동의 필요${NC}"
                CONSENT_NEEDED=true

                # 약관 클릭 액션: 백그라운드(subshell)로 실행하여 폴링 블로킹 방지 및 충분한 로딩 대기
                (
                    DELAY=$(awk "BEGIN{printf \"%.1f\", 4.0 + rand() * 2.0}"  )
                    echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] 로딩 대기... ${DELAY}초 후 약관 체크박스 클릭...${NC}"
                    sleep "$DELAY"
                    $MACRO_EXEC "$DEV_ID" "agree_essential_service_1"

                    DELAY2=$(awk "BEGIN{printf \"%.1f\", 1.5 + rand() * 1.5}")
                    echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ${DELAY2}초 후 동의 버튼 클릭...${NC}"
                    sleep "$DELAY2"
                    $MACRO_EXEC "$DEV_ID" "btn_final_confirm"
                ) &
            fi
        fi

        # ConsentActivity screen_end 감지 = 약관 동의 완료
        if [ "$CONSENT_NEEDED" = true ]; then
            if echo "$NEW_NLOG" | grep -q '"screen_end"[^}]*"ConsentActivity"'; then
                echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 약관 동의 완료${NC}"
                CONSENT_DONE=true
            fi
        fi
    fi

    # 약관 없이 메인으로 직행한 경우 (이미 동의됨)
    if [ "$APP_OPEN" = true ] && [ "$CONSENT_NEEDED" = false ] && [ "$CONSENT_DONE" = false ]; then
        if echo "$NEW_NLOG" | grep -q '"screen_start"[^}]*"DiscoveryFragment"'; then
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 약관 불필요 (이미 동의됨)${NC}"
            CONSENT_DONE=true
        fi
    fi

    # Step 3: 메인 화면 로딩 대기
    if [ "$APP_OPEN" = true ] && [ "$CONSENT_DONE" = true ] && [ "$MAIN_LOADED" = false ]; then
        if echo "$NEW_NLOG" | grep -q '"MainFragment"'; then SEEN_MAIN=true; fi
        if echo "$NEW_NLOG" | grep -q '"DiscoveryFragment"'; then SEEN_DISC=true; fi
        
        # MainFragment 또는 DiscoveryFragment 둘 중 하나라도 로드되었다면 사실상 메인 페이지 진입 완료로 간주
        if [ "$SEEN_MAIN" = true ] || [ "$SEEN_DISC" = true ]; then
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 메인 화면 로딩 완료${NC}"
            MAIN_LOADED=true
        fi
    fi

    # Step 4: 배너 처리
    if [ "$MAIN_LOADED" = true ] && [ "$BANNER_DONE" = false ]; then
        # 배너 감지
        if [ "$BANNER_DETECTED" = false ]; then
            if echo "$NEW_NLOG" | grep -q '"screen_start"[^}]*"EventModalDialogFragment"'; then
                echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 배너 감지! 뒤로가기로 닫기...${NC}"
                BANNER_DETECTED=true
                sleep 1
                adb -s "$DEV_ID" shell input keyevent BACK
            fi
        fi

        # 배너 닫힘 확인
        if [ "$BANNER_DETECTED" = true ]; then
            if echo "$NEW_NLOG" | grep -q '"screen_end"[^}]*"EventModalDialogFragment"'; then
                echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 배너 닫기 완료${NC}"
                BANNER_DONE=true
            fi
        fi
    fi

    # Step 5: 검색창 클릭
    # 메인 로딩 완료 + 배너 처리 완료 (또는 배너 없음 확인) 후 클릭
    if [ "$MAIN_LOADED" = true ] && [ "$SEARCH_CLICKED" = false ]; then
        # 배너가 이미 처리된 경우
        if [ "$BANNER_DONE" = true ]; then
            DELAY=$(awk "BEGIN{printf \"%.1f\", 1.0 + rand() * 2.0}")
            echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ${DELAY}초 후 검색창 클릭...${NC}"
            sleep "$DELAY"
            $MACRO_EXEC "$DEV_ID" "home_search_field"
            SEARCH_CLICKED=true
        fi

        # 배너가 아직 감지 안 된 경우: 8초 대기 후 배너 없음으로 판단
        if [ "$BANNER_DETECTED" = false ] && [ "$BANNER_DONE" = false ]; then
            if [ -z "$BANNER_WAIT_START" ]; then
                BANNER_WAIT_START=$(date +%s)
                echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] 배너 대기 중 (8초)...${NC}"
            else
                NOW_TS=$(date +%s)
                ELAPSED=$((NOW_TS - BANNER_WAIT_START))
                if [ $ELAPSED -ge 8 ]; then
                    echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 배너 없음 확인 (${ELAPSED}초 대기)${NC}"
                    BANNER_DONE=true
                fi
            fi
        fi
    fi

    # Step 6: 검색창 진입 (SCH.all.entry) 대기 후 검색어 입력
    if [ "$SEARCH_CLICKED" = true ] && [ "$SEARCH_ENTERED" = false ]; then
        if echo "$NEW_NLOG" | grep -q "SCH.all.entry"; then
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 검색 화면 (SCH.all.entry) 진입 완료${NC}"
            
            if [ -n "$TARGET_NAME" ]; then
                echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ADB 키보드 활성화 및 텍스트 입력 시작: $TARGET_NAME${NC}"
                
                # 기존 사용 중인 키보드 백업
                DEFAULT_IME=$(adb -s "$DEV_ID" shell settings get secure default_input_method | tr -d '\r')
                
                # ADBKeyboard로 변경
                adb -s "$DEV_ID" shell ime set com.android.adbkeyboard/.AdbIME
                sleep 2
                
                # 한글자씩 입력
                for (( i=0; i<${#TARGET_NAME}; i++ )); do
                    CHAR="${TARGET_NAME:$i:1}"
                    # 공백 처리 (AdbKeyboard는 띄어쓰기를 %s 등 URL 인코딩 또는 띄어쓰기 그대로도 잘 받을 수 있음)
                    # 스페이스바 broadcast: 62 (KEYCODE_SPACE)
                    if [ "$CHAR" = " " ]; then
                        adb -s "$DEV_ID" shell input keyevent 62
                    else
                        adb -s "$DEV_ID" shell am broadcast -a ADB_INPUT_TEXT --es msg "$CHAR" >/dev/null 2>&1
                    fi
                    sleep 0.2
                done
                
                echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 검색어 입력 완료${NC}"
                
                # 원래 키보드(삼성키보드 등)로 원복
                echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] 기존 키보드($DEFAULT_IME)로 복원 중...${NC}"
                adb -s "$DEV_ID" shell ime set "$DEFAULT_IME"
                
                SEARCH_ENTERED=true
            fi
            
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 검색창 진입 및 타이핑 완료.${NC}"
            # exit 0 (기존: 여기서 종료, 변경: search 단계로 이어짐)
        fi
    fi

    # Step 7: UI 덤프로 주소 클릭 & CK_suggest-place-list 대기
    if [ "$SEARCH_ENTERED" = true ] && [ "$SUGGEST_CLICKED" = false ]; then
        if [ "$CLICKER_STARTED" = false ] && [ -n "$TARGET_ADDRESS" ]; then
            echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] 타겟 주소 클릭 스크립트 실행 ($TARGET_ADDRESS)...${NC}"
            python3 utils/ui_clicker.py "$DEV_ID" "$TARGET_ADDRESS" &
            CLICKER_STARTED=true
        fi
        
        if echo "$NEW_NLOG" | grep -q '"CK_suggest-place-list"'; then
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 자동완성 주소 클릭 성공 (CK_suggest-place-list)${NC}"
            SUGGEST_CLICKED=true
        fi
    fi

    # Step 8: 검색결과(POI) 로드 확인 (poi.end)
    if [ "$SUGGEST_CLICKED" = true ] && [ "$POI_LOADED" = false ]; then
        if echo "$NEW_NLOG" | grep -q '"poi.end"'; then
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 검색결과 페이지 로딩 감지 (poi.end)${NC}"
            POI_LOADED=true
        fi
    fi

    # Step 9: 도착 버튼 클릭 (poi.end 이후 3.0 ~ 5.0초 대기)
    if [ "$POI_LOADED" = true ] && [ "$DESTINATION_CLICKED" = false ]; then
        DELAY=$(awk "BEGIN{printf \"%.1f\", 3.0 + rand() * 2.0}")
        echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ${DELAY}초 대기 후 '도착' 버튼 클릭 (UI 동적 스캔)...${NC}"
        
        # 비동기로 대기 후 클릭 명령어를 전송 (패킷 스캔이 밀리지 않도록 처리)
        (
            sleep "$DELAY"
            python3 utils/ui_clicker.py "$DEV_ID" "exact:도착"
        ) &
        
        DESTINATION_CLICKED=true
    fi

    # Step 10: 길찾기(경로) 리스트 화면 진입 대기 (pubtrans.list)
    if [ "$DESTINATION_CLICKED" = true ] && [ "$ROUTE_LIST_LOADED" = false ]; then
        if echo "$NEW_NLOG" | grep -q '"pubtrans.list"'; then
            echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 길찾기 리스트 화면 진입 완료 (pubtrans.list)${NC}"
            ROUTE_LIST_LOADED=true
        fi
    fi

    # Step 11: 자동차 탭 클릭 및 재시도 로직 (pubtrans.list 이후)
    if [ "$ROUTE_LIST_LOADED" = true ] && [ "$CAR_ROUTE_LOADED" = false ]; then
        NOW_SEC=$(date +%s)
        
        if [ "$CAR_TAB_CLICKED" = false ]; then
            DELAY=$(awk "BEGIN{printf \"%.0f\", 3.0 + rand() * 2.0}")
            echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ${DELAY}초 대기 후 '자동차' 탭 최초 클릭 (UI 동적 스캔)...${NC}"
            sleep "$DELAY"
            python3 utils/ui_clicker.py "$DEV_ID" "id:com.nhn.android.nmap:id/tab_car"
            LAST_CAR_TAP_TIME=$(date +%s)
            CAR_TAB_CLICKED=true
        fi
        
        if [ "$CAR_TAB_CLICKED" = true ]; then
            # 클릭 후 일정 시간 경과 후에도 CAR_ROUTE_LOADED가 안되었다면 재시도
            ELAPSED=$((NOW_SEC - LAST_CAR_TAP_TIME))
            if [ "$ELAPSED" -ge 6 ] && [ "$CAR_TAP_RETRY" -lt 5 ]; then
                echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 자동차 탭 전환 지연 확인. 재도전 클릭 ($((CAR_TAP_RETRY+1))/5)...${NC}"
                python3 utils/ui_clicker.py "$DEV_ID" "id:com.nhn.android.nmap:id/tab_car"
                LAST_CAR_TAP_TIME=$(date +%s)
                CAR_TAP_RETRY=$((CAR_TAP_RETRY + 1))
            fi
        fi
    fi

    # Step 12: 하이패스 팝업 감지 및 처리
    if [ "$CAR_TAB_CLICKED" = true ] && [ "$HIPASS_DONE" = false ]; then
        if [ "$HIPASS_DETECTED" = false ]; then
            if echo "$NEW_NLOG" | grep -q '"PV_hipass-popup"'; then
                echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 하이패스 설정 팝업 감지 (PV_hipass-popup). '있어요' 클릭...${NC}"
                HIPASS_DETECTED=true
                DELAY=$(awk "BEGIN{printf \"%.1f\", 1.0 + rand() * 1.5}")
                (
                    sleep "$DELAY"
                    $MACRO_EXEC "$DEV_ID" "btn_hipass_yes"
                ) &
            fi
        fi

        # 하이패스가 떴고 아직 처리가 안 끝났다면 닫힘 모달 대기
        if [ "$HIPASS_DETECTED" = true ] && [ "$HIPASS_DONE" = false ]; then
            # screen_name: HipassUseModalFragment 및 type: screen_end
            if echo "$NEW_NLOG" | grep -q '"HipassUseModalFragment"' && echo "$NEW_NLOG" | grep -q '"screen_end"'; then
                echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 하이패스 체크 완료 (HipassUseModalFragment 종료)${NC}"
                HIPASS_DONE=true
            fi
        fi
    fi

    # Step 13: 자동차 탭 완전 로딩 확인
    if [ "$CAR_TAB_CLICKED" = true ] && [ "$CAR_ROUTE_LOADED" = false ]; then
        if [ "$SW_ROUTE_CARDS_DETECTED" = false ]; then
            if echo "$NEW_NLOG" | grep -q '"SW_route-cards"'; then
                SW_ROUTE_CARDS_DETECTED=true
            fi
        fi
        
        # SW_route-cards 감지된 상태에서, 하이패스가 없었거나 이미 완료되었다면
        if [ "$SW_ROUTE_CARDS_DETECTED" = true ]; then
            if [ "$HIPASS_DETECTED" = false ] || [ "$HIPASS_DONE" = true ]; then
                echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 자동차 경로 화면 완벽 로딩 감지 (DRT.route.car + SW_route-cards)${NC}"
                CAR_ROUTE_LOADED=true
            fi
        fi
    fi

    # Step 14: 안내시작 버튼 클릭 및 재시도 로직
    if [ "$CAR_ROUTE_LOADED" = true ] && [ "$GUIDANCE_DONE" = false ]; then
        NOW_SEC=$(date +%s)
        
        if [ "$GUIDANCE_CLICKED" = false ]; then
            DELAY=$(awk "BEGIN{printf \"%.0f\", 3.0 + rand() * 2.0}")
            echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ${DELAY}초 대기 후 '안내시작' 버튼 최초 클릭...${NC}"
            sleep "$DELAY"
            $MACRO_EXEC "$DEV_ID" "btn_start_guidance"
            LAST_GUIDANCE_TAP_TIME=$(date +%s)
            GUIDANCE_CLICKED=true
        fi
        
        # 클릭 후 "CK_navi-bttn" 패킷 확인
        if [ "$GUIDANCE_CLICKED" = true ]; then
            if echo "$NEW_NLOG" | grep -q '"CK_navi-bttn"'; then
                echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 안내시작 버튼 클릭 성공 (CK_navi-bttn)${NC}"
                GUIDANCE_DONE=true
                LAST_GUIDANCE_TAP_TIME=$(date +%s) # 모달 타임아웃 측정을 위해 초기화
            else
                ELAPSED=$((NOW_SEC - LAST_GUIDANCE_TAP_TIME))
                if [ "$ELAPSED" -ge 4 ] && [ "$GUIDANCE_TAP_RETRY" -lt 5 ]; then
                    echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 안내시작 반응 없음. 재도전 클릭 ($((GUIDANCE_TAP_RETRY+1))/5)...${NC}"
                    $MACRO_EXEC "$DEV_ID" "btn_start_guidance"
                    LAST_GUIDANCE_TAP_TIME=$(date +%s)
                    GUIDANCE_TAP_RETRY=$((GUIDANCE_TAP_RETRY + 1))
                fi
            fi
        fi
    fi

    # Step 15: 영업시간 알림 모달 확인 및 처리
    if [ "$GUIDANCE_DONE" = true ] && [ "$BUSINESS_MODAL_DONE" = false ]; then
        NOW_SEC=$(date +%s)
        
        if [ "$BUSINESS_MODAL_DETECTED" = false ]; then
            if echo "$NEW_NLOG" | grep -q '"BusinessHourWarningModalFragment"'; then
                echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 영업시간 알림 모달 감지 (BusinessHourWarningModalFragment)...${NC}"
                BUSINESS_MODAL_DETECTED=true
            else
                ELAPSED=$((NOW_SEC - LAST_GUIDANCE_TAP_TIME))
                if [ "$ELAPSED" -ge 7 ]; then
                    # 안내시작 성공 후 7초 동안 모달이 안뜨면 모달 없는 것으로 간주
                    BUSINESS_MODAL_DONE=true
                fi
            fi
        fi
        
        if [ "$BUSINESS_MODAL_DETECTED" = true ]; then
            if [ "$BUSINESS_MODAL_CLICKED" = false ]; then
                DELAY=$(awk "BEGIN{printf \"%.0f\", 1.0 + rand() * 1.5}")
                echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ${DELAY}초 대기 후 모달 내 '안내시작' 버튼 클릭...${NC}"
                (
                    sleep "$DELAY"
                    $MACRO_EXEC "$DEV_ID" "btn_start_guidance_modal"
                ) &
                BUSINESS_MODAL_CLICKED=true
            fi
            
            if [ "$BUSINESS_MODAL_CLICKED" = true ]; then
                if echo "$NEW_NLOG" | grep -q '"CK_warn-closetime-start"'; then
                    echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 모달 내 안내시작 클릭 완료 (CK_warn-closetime-start)${NC}"
                    BUSINESS_MODAL_DONE=true
                fi
            fi
        fi
    fi

    # Step 16: 주행 화면(안내 시작 완료) 진입 확인 (screen_end)
    if [ "$DRIVING_STARTED" = false ] && [ "$SEEN_NAVI_SCREEN_END" = true ] && [ "$GUIDANCE_DONE" = true ]; then
        echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 실주행 화면 진입 성공 (DRIVING_STARTED)${NC}"
        BUSINESS_MODAL_DONE=true # 혹시 CK_warn-closetime-start 누락됐더라도 주행 떴으면 통과
        DRIVING_STARTED=true
        DRIVING_START_TIME=$(date +%s)
        LAST_STALL_CHECK_TIME=$(date +%s)
    fi

    # Step 17: 주행 모니터링 (최대 20분 루프) 및 기타 주행 중 예외 처리
    if [ "$DRIVING_STARTED" = true ]; then
        
        # 클로바 약관 동의 팝업 감지 (단 1회)
        if [ "$CLOVA_TERMS_DONE" = false ]; then
            if [ "$CLOVA_TERMS_DETECTED" = false ]; then
                if echo "$NEW_NLOG" | grep -q '"screen_start"' && echo "$NEW_NLOG" | grep -q '"ClovaGuestTermsActivity"'; then
                    echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 클로바 AI 약관 동의 화면 감지. 자동 동의 진행...${NC}"
                    CLOVA_TERMS_DETECTED=true
                    
                    # 체크 누르고 2초 뒤 동의 누름
                    (
                        sleep 1
                        $MACRO_EXEC "$DEV_ID" "btn_clova_check"
                        sleep 2
                        $MACRO_EXEC "$DEV_ID" "btn_clova_agree"
                    ) &
                fi
            fi
            
            # 이미 감지되어 클릭 매크로가 도는 중이라면 종료 패킷 대기
            if [ "$CLOVA_TERMS_DETECTED" = true ]; then
                if echo "$NEW_NLOG" | grep -q '"screen_end"' && echo "$NEW_NLOG" | grep -q '"ClovaGuestTermsActivity"'; then
                    echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 클로바 AI 약관 자동 동의 완료!${NC}"
                    CLOVA_TERMS_DONE=true
                fi
            fi
        fi

        # global routeend는 nlogapp 이벤트가 아니므로 NEW_PACKETS에서 감지
        if [ "$ROUTE_END_DETECTED" = false ]; then
            if echo "$NEW_PACKETS" | grep -E -q '"url"[^}]*routeend|v3/global/routeend'; then
                echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 목적지 도착 (routeend) 로드 감지! 안내종료 진행...${NC}"
                ROUTE_END_DETECTED=true
                
                # 목적지 도착 화면의 '안내종료' 탭 클릭 (2초 딜레이)
                (
                    sleep 2
                    $MACRO_EXEC "$DEV_ID" "btn_end_guidance"
                ) &
            fi
        else
            if [ "$GUIDANCE_QUIT_DONE" = false ]; then
                if echo "$NEW_NLOG" | grep -q '"CK_end-bttn"'; then
                    echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 안내종료 클릭 성공 (CK_end-bttn)${NC}"
                    GUIDANCE_QUIT_DONE=true
                    
                    DELAY=$(awk "BEGIN{printf \"%.0f\", 10.0 + rand() * 5.0}")
                    echo -e "${CYAN}[$(NOW)] [*] [$DEV_ID] ${DELAY}초 대기 후 홈(Home) 진입으로 앱 숨기기...${NC}"
                    sleep "$DELAY"
                    adb -s "$DEV_ID" shell input keyevent 3
                    
                    echo -e "${GREEN}============================================================${NC}"
                    echo -e "${GREEN}[$(NOW)] [✓] [$DEV_ID] 🎈 매크로 전 과정 글로벌 완벽 종료! 🎈${NC}"
                    echo -e "${GREEN}============================================================${NC}"
                    exit 0
                fi
            fi
        fi
        
        # 3. GPS 정체(Stall) 및 경로 이탈 체크 (cmd/reload.sh 연동)
        ELAPSED_DRIVE=$((NOW_SEC - DRIVING_START_TIME))
        if [ "$ELAPSED_DRIVE" -ge 180 ] && [ "$ROUTE_END_DETECTED" = false ]; then
            ELAPSED_SINCE_CHECK=$((NOW_SEC - LAST_STALL_CHECK_TIME))
            if [ "$ELAPSED_SINCE_CHECK" -ge 45 ]; then
                ROUTE_INFO=$(python3 utils/parse_remaining_route.py "$DEV_ID" 2>/dev/null || true)
                REMAINING_DIST=$(echo "$ROUTE_INFO" | grep "TOTAL_DISTANCE" | awk '{print $2}')
                
                if [ -n "$REMAINING_DIST" ]; then
                    if [ "$PREV_REMAINING_DIST" != "-1.0" ]; then
                        # awk를 사용하여 부동소수점 거리 연산 (거리가 0.05km 미만으로 줄었으면 고착됨)
                        IS_STUCK=$(awk -v pd="$PREV_REMAINING_DIST" -v cd="$REMAINING_DIST" 'BEGIN{ if(pd - cd < 0.05) print 1; else print 0 }')
                        
                        if [ "$IS_STUCK" -eq 1 ]; then
                            echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 🐢 차량 정체 감지! (이전: ${PREV_REMAINING_DIST}km -> 현재: ${REMAINING_DIST}km)${NC}"
                            echo -e "${YELLOW}[$(NOW)] [!] [$DEV_ID] 🚑 cmd/reload.sh 가동하여 경로 심폐소생술 진행...${NC}"
                            
                            # CWD가 test_nmap_v1 이므로 상대 루트 경로 지정
                            bash ../cmd/reload.sh "$DEV_ID" > /dev/null 2>&1 &
                            
                            PREV_REMAINING_DIST="-1.0"
                            LAST_STALL_CHECK_TIME=$((NOW_SEC + 60)) # 리로드 직후 1분간 체크 회피 (유예)
                        else
                            PREV_REMAINING_DIST=$REMAINING_DIST
                            LAST_STALL_CHECK_TIME=$NOW_SEC
                        fi
                    else
                        PREV_REMAINING_DIST=$REMAINING_DIST
                        LAST_STALL_CHECK_TIME=$NOW_SEC
                    fi
                else
                    # 파싱 실패 (로그 없음 등) 시 타이머 리셋
                    LAST_STALL_CHECK_TIME=$NOW_SEC
                fi
            fi
        fi
        
        # 최대 주행 시간 체크 (20분)
        if [ "$ELAPSED_DRIVE" -ge 1200 ]; then
            echo -e "${RED}[$(NOW)] [!] [$DEV_ID] 주행 20분 초과! 안전 종료.${NC}"
            exit 1
        fi
    fi

done
