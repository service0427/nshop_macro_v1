from typing import Optional, Dict, Any
import json
from database import get_db_cursor
from config import MIN_AGING_SECONDS

class TaskService:
    @staticmethod
    def assign_task(
        task_id: Optional[int] = None,
        min_age_seconds: int = MIN_AGING_SECONDS,
        device_id: Optional[str] = None,
        ip: Optional[str] = None,
        specific_nv_mid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        [작업 할당 및 기존 작업 조회 API]
        - tasks 테이블의 PK인 task_id (숫자)만 단독 사용
        1. task_id 파라미터가 주어진 경우:
           - 새로운 NNB를 소모하지 않고, 기존에 할당되었던 tasks 레코드 정보를 그대로 반환
        2. task_id 파라미터가 없는 경우 (신규 할당):
           - 20분(1200초) 이상 숙성된 NNB+BUC 선점 (공용 풀에서 선점)
           - nshop_list 에서 keyword(product_name), nv_mid(target_id), compare_id(mall_product_id), store_name(mall_name) 추출
           - tasks 테이블에 신규 INSERT (task_id 자동 발급)
           - 선점된 NNB use_count += 1
           - 생성된 task_id와 핵심 정보 반환
        """
        with get_db_cursor(commit=True) as (cur, conn):
            # ---------------------------------------------------------
            # 0. 30분 이상 경과된 미완료(ASSIGNED) 작업 자동 타임아웃 처리
            # ---------------------------------------------------------
            cur.execute("""
                UPDATE tasks
                SET status = 'TIMEOUT', completed_at = NOW(), result_memo = 'Auto-expired: client did not report back within 30m'
                WHERE status = 'ASSIGNED' AND assigned_at < NOW() - INTERVAL 30 MINUTE
            """)

            # ---------------------------------------------------------
            # CASE A: 기존 task_id 재조회 모드
            # ---------------------------------------------------------
            if task_id is not None:
                cur.execute("""
                    SELECT task_id, nnb, buc, keyword, nv_mid, compare_id, store_name, device_id, ip, status
                    FROM tasks
                    WHERE task_id = %s
                """, (task_id,))
                existing = cur.fetchone()

                if existing:
                    return {
                        "success": True,
                        "task_id": int(existing["task_id"]),
                        "nnb": existing["nnb"],
                        "buc": existing["buc"],
                        "keyword": existing["keyword"],
                        "nv_mid": existing["nv_mid"],
                        "compare_id": existing["compare_id"],
                        "store_name": existing.get("store_name") or "",
                        "device_id": existing["device_id"],
                        "ip": existing["ip"]
                    }
                else:
                    return {
                        "success": False,
                        "message": f"task_id({task_id})에 해당하는 작업 정보를 찾을 수 없습니다."
                    }

            # ---------------------------------------------------------
            # CASE B: 신규 작업 할당 모드 (최소 1200초 = 20분 엄격 강제)
            # ---------------------------------------------------------
            min_age_seconds = max(1200, int(min_age_seconds or 1200))

            # 1. 20분 초과된 NNB+BUC 선점 (공용 풀에서 선점)
            query = """
                SELECT id, nnb, buc, use_count, status, created_at,
                       TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                FROM nnbs
                WHERE status IN ('AGING', 'READY', 'ACTIVE')
                  AND created_at <= NOW() - INTERVAL %s SECOND
                ORDER BY use_count ASC, created_at ASC, id ASC
                LIMIT 1
                FOR UPDATE
            """
            cur.execute(query, (min_age_seconds,))
            selected_nnb = cur.fetchone()

            # 20분 초과 토큰이 없거나 1200초 미만인 경우 대기 안내 반환
            if not selected_nnb or int(selected_nnb.get("age_seconds") or 0) < 1200:
                cur.execute("""
                    SELECT MAX(TIMESTAMPDIFF(SECOND, created_at, NOW())) AS oldest_age
                    FROM nnbs
                    WHERE status IN ('AGING', 'READY', 'ACTIVE')
                """)
                oldest_row = cur.fetchone()
                oldest_age = int(oldest_row["oldest_age"] or 0) if oldest_row else 0
                remaining = max(0, min_age_seconds - oldest_age)

                return {
                    "success": False,
                    "message": f"20분({min_age_seconds}초) 이상 숙성된 NNB 토큰이 아직 없습니다. (남은 대기시간: 약 {remaining}초)",
                    "retry_after_seconds": remaining,
                    "oldest_age_seconds": oldest_age,
                    "min_age_seconds": min_age_seconds
                }

            # 2. nshop_list 테이블에서 keyword, nv_mid, compare_id, store_name 추출
            if specific_nv_mid:
                cur.execute("""
                    SELECT target_id, product_name, mall_product_id, mall_name
                    FROM nshop_list
                    WHERE target_id = %s
                    LIMIT 1
                """, (specific_nv_mid,))
                product = cur.fetchone()
            else:
                product = None

            if not product:
                cur.execute("""
                    SELECT target_id, product_name, mall_product_id, mall_name
                    FROM nshop_list
                    WHERE product_name IS NOT NULL AND product_name != ''
                    ORDER BY RAND()
                    LIMIT 1
                """)
                product = cur.fetchone()

            if not product:
                return {
                    "success": False,
                    "message": "nshop_list 테이블에 작업 대상 상품 데이터가 없습니다."
                }

            keyword = product["product_name"]
            nv_mid = product["target_id"]
            compare_id = product["mall_product_id"] if product["mall_product_id"] else None
            store_name = product.get("mall_name") or ""
            nnb_val = selected_nnb["nnb"]
            buc_val = selected_nnb["buc"]

            # 3. tasks 테이블에 신규 INSERT (task_id PK 자동 생성)
            cur.execute("""
                INSERT INTO tasks (nnb, buc, keyword, nv_mid, compare_id, store_name, device_id, ip, status, assigned_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ASSIGNED', NOW())
            """, (nnb_val, buc_val, keyword, nv_mid, compare_id, store_name, device_id, ip))
            new_task_id = cur.lastrowid

            # 4. NNB use_count 1 증가 및 작업 대상 기록
            cur.execute("""
                UPDATE nnbs
                SET use_count = use_count + 1,
                    last_used_at = NOW(),
                    used_target = %s,
                    device_id = COALESCE(%s, device_id)
                WHERE id = %s
            """, (nv_mid, device_id, selected_nnb["id"]))

            # 5. 핵심 데이터 반환 (store_name 포함)
            return {
                "success": True,
                "task_id": int(new_task_id),
                "nnb": nnb_val,
                "buc": buc_val,
                "keyword": keyword,
                "nv_mid": nv_mid,
                "compare_id": compare_id,
                "store_name": store_name,
                "device_id": device_id,
                "ip": ip
            }

    @staticmethod
    def complete_task(task_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        작업 완료/결과 보고 처리:
        search_type, serp_rank, shopping_rank, shopping_page, match_type, login_detected, duration_seconds 등을 DB에 기록
        """
        VALID_STATUSES = {"ASSIGNED", "SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"}

        raw_status = str(payload.get("status") or "").upper().strip()
        if not raw_status:
            raw_status = "SUCCESS" if payload.get("success", True) else "FAILED"

        result_memo = payload.get("memo") or payload.get("error_reason") or payload.get("message") or ""

        # status가 허용된 ENUM이 아닌 경우 (예: TARGET_NOT_FOUND 등) memo에 보존하고 FAILED 매핑
        if raw_status in VALID_STATUSES:
            status_val = raw_status
        else:
            prefix = f"[{raw_status}]"
            if prefix not in result_memo:
                result_memo = f"{prefix} {result_memo}".strip()
            status_val = "FAILED" if any(w in raw_status for w in ("FAIL", "ERR", "NOT_FOUND", "BLOCK", "DENIED", "REJECT")) else "SUCCESS"

        if len(result_memo) > 250:
            result_memo = result_memo[:247] + "..."
        if not result_memo:
            result_memo = None

        search_type = payload.get("search_type")
        serp_rank = payload.get("serp_rank")
        if serp_rank is not None:
            try:
                serp_rank = int(serp_rank)
            except (ValueError, TypeError):
                serp_rank = None

        shopping_rank = payload.get("shopping_rank")
        if shopping_rank is not None:
            try:
                shopping_rank = int(shopping_rank)
            except (ValueError, TypeError):
                shopping_rank = None

        shopping_page = payload.get("shopping_page")
        if shopping_page is not None:
            try:
                shopping_page = int(shopping_page)
            except (ValueError, TypeError):
                shopping_page = None

        match_type = payload.get("match_type")
        login_detected = 1 if payload.get("login_detected") else 0

        duration_seconds = payload.get("duration_seconds")
        if duration_seconds is not None:
            try:
                duration_seconds = float(duration_seconds)
            except (ValueError, TypeError):
                duration_seconds = None

        device_id = payload.get("device_id")
        store_name = payload.get("store_name")
        raw_report = json.dumps(payload, ensure_ascii=False)

        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("SELECT task_id, store_name FROM tasks WHERE task_id = %s", (int(task_id),))
            existing = cur.fetchone()

            if existing:
                cur.execute("""
                    UPDATE tasks
                    SET status = %s,
                        search_type = %s,
                        serp_rank = %s,
                        shopping_rank = %s,
                        shopping_page = %s,
                        match_type = %s,
                        login_detected = %s,
                        duration_seconds = %s,
                        device_id = COALESCE(%s, device_id),
                        store_name = COALESCE(%s, store_name),
                        result_memo = COALESCE(%s, result_memo),
                        raw_report = %s,
                        completed_at = NOW()
                    WHERE task_id = %s
                """, (
                    status_val,
                    search_type,
                    serp_rank,
                    shopping_rank,
                    shopping_page,
                    match_type,
                    login_detected,
                    duration_seconds,
                    device_id,
                    store_name,
                    result_memo,
                    raw_report,
                    int(task_id)
                ))
            else:
                # 할당 이력이 없는 경우에도 결과 보고를 보존하기 위해 신규 INSERT
                cur.execute("""
                    INSERT INTO tasks (
                        task_id, nnb, keyword, nv_mid, store_name, status, search_type, serp_rank,
                        shopping_rank, shopping_page, match_type, login_detected,
                        duration_seconds, device_id, result_memo, raw_report, assigned_at, completed_at
                    ) VALUES (
                        %s, 'DIRECT_REPORT', 'DIRECT_REPORT', '0', %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, NOW(), NOW()
                    )
                """, (
                    int(task_id),
                    store_name,
                    status_val,
                    search_type,
                    serp_rank,
                    shopping_rank,
                    shopping_page,
                    match_type,
                    login_detected,
                    duration_seconds,
                    device_id,
                    result_memo,
                    raw_report
                ))

            # 저장된 데이터 다시 조회
            cur.execute("""
                SELECT task_id, status, store_name, search_type, serp_rank, shopping_rank, shopping_page,
                       match_type, login_detected, duration_seconds, device_id, result_memo,
                       DATE_FORMAT(assigned_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS assigned_at,
                       DATE_FORMAT(completed_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS completed_at
                FROM tasks
                WHERE task_id = %s
            """, (int(task_id),))
            saved = cur.fetchone()

            return {
                "success": True,
                "task_id": int(saved["task_id"]),
                "message": f"task_id({task_id}) 결과 보고가 성공적으로 기록되었습니다.",
                "data": {
                    "task_id": int(saved["task_id"]),
                    "status": saved["status"],
                    "store_name": saved.get("store_name") or "",
                    "search_type": saved["search_type"],
                    "serp_rank": saved["serp_rank"],
                    "shopping_rank": saved["shopping_rank"],
                    "shopping_page": saved["shopping_page"],
                    "match_type": saved["match_type"],
                    "login_detected": bool(saved["login_detected"]),
                    "duration_seconds": saved["duration_seconds"],
                    "device_id": saved["device_id"],
                    "completed_at": saved["completed_at"]
                }
            }

    @staticmethod
    def get_task_report(task_id: int) -> Optional[Dict[str, Any]]:
        """특정 task_id의 상세 보고 조회"""
        with get_db_cursor(commit=False) as (cur, _):
            cur.execute("""
                SELECT task_id, nnb, buc, keyword, nv_mid, compare_id, store_name, device_id, ip,
                       status, search_type, serp_rank, shopping_rank, shopping_page,
                       match_type, login_detected, duration_seconds, result_memo,
                       DATE_FORMAT(assigned_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS assigned_at,
                       DATE_FORMAT(completed_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS completed_at
                FROM tasks
                WHERE task_id = %s
            """, (int(task_id),))
            row = cur.fetchone()
            if row:
                row["login_detected"] = bool(row["login_detected"])
            return row

    @staticmethod
    def get_task_history(limit: int = 50) -> list:
        """최근 할당된 작업 이력 조회"""
        with get_db_cursor(commit=False) as (cur, _):
            cur.execute("""
                SELECT task_id, nnb, buc, keyword, nv_mid, compare_id, store_name, device_id, ip,
                       status, search_type, serp_rank, shopping_rank, shopping_page,
                       match_type, login_detected, duration_seconds, result_memo,
                       DATE_FORMAT(assigned_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS assigned_at,
                       DATE_FORMAT(completed_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS completed_at
                FROM tasks
                ORDER BY task_id DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            for r in rows:
                r["login_detected"] = bool(r["login_detected"])
            return rows
