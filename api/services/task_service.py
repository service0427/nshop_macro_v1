from typing import Optional, Dict, Any
import json
from database import get_db_cursor
from config import MIN_AGING_SECONDS

class TaskService:
    @staticmethod
    def assign_tasks(
        device_ids: list,
        ip: Optional[str] = None,
        task_id: Optional[int] = None,
        specific_nv_mid: Optional[str] = None,
        min_age_seconds: int = MIN_AGING_SECONDS
    ) -> Dict[str, Any]:
        """
        [통합 작업 할당 API: 단일 및 1:N 배치 완전 일원화]
        - device_ids: ['DEV1'] 또는 ['DEV1', 'DEV2', ...]
        - ip: 외부 LTE 모뎀/공인 IP (단말기들이 공유하는 Egress IP)
        - 20분(1200초) 이상 숙성된 NNB/BUC 선점
        - nshop_list 에서 타겟 상품 랜덤 매칭
        - tasks 테이블에 기록 후 일관된 JSON 반환
        """
        if not device_ids:
            device_ids = ["default"]

        min_age_seconds = max(1200, int(min_age_seconds or 1200))
        requested_n = len(device_ids)

        with get_db_cursor(commit=True) as (cur, conn):
            # 0. 30분 이상 경과된 미완료(ASSIGNED) 작업 자동 타임아웃 처리
            cur.execute("""
                UPDATE tasks
                SET status = 'TIMEOUT', completed_at = NOW(), result_memo = 'Auto-expired: client did not report back within 30m'
                WHERE status = 'ASSIGNED' AND assigned_at < NOW() - INTERVAL 30 MINUTE
            """)

            # CASE A: 기존 task_id 재조회 모드
            if task_id is not None:
                cur.execute("""
                    SELECT task_id, nnb, buc, keyword, nv_mid, compare_id, store_name, device_id, ip, status
                    FROM tasks
                    WHERE task_id = %s
                """, (task_id,))
                existing = cur.fetchone()

                if existing:
                    t_obj = {
                        "task_id": int(existing["task_id"]),
                        "device_id": existing["device_id"],
                        "keyword": existing["keyword"],
                        "nv_mid": existing["nv_mid"],
                        "compare_id": existing["compare_id"],
                        "store_name": existing.get("store_name") or "",
                        "nnb": existing["nnb"],
                        "buc": existing["buc"],
                        "ip": existing["ip"]
                    }
                    res = {
                        "success": True,
                        "ip": existing["ip"],
                        "count": 1,
                        "tasks": [t_obj]
                    }
                    # 단일 작업 하위 호환 평탄화
                    for k, v in t_obj.items():
                        res[k] = v
                    return res
                else:
                    return {
                        "success": False,
                        "message": f"task_id({task_id})에 해당하는 작업 정보를 찾을 수 없습니다."
                    }

            # CASE B: 신규 할당 (최소 1200초 숙성 NNB N개 선점)
            query = """
                SELECT id, nnb, buc, use_count, status, created_at,
                       TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                FROM nnbs
                WHERE status IN ('AGING', 'READY', 'ACTIVE')
                  AND created_at <= NOW() - INTERVAL %s SECOND
                ORDER BY use_count ASC, created_at ASC, id ASC
                LIMIT %s
                FOR UPDATE
            """
            cur.execute(query, (min_age_seconds, requested_n))
            selected_nnbs = cur.fetchall()

            if not selected_nnbs:
                return {
                    "success": False,
                    "is_no_task": True,
                    "message": f"20분({min_age_seconds}초) 이상 숙성된 NNB 토큰이 부족하여 대기 중입니다."
                }

            alloc_count = min(len(selected_nnbs), requested_n)

            # nshop_list 테이블에서 상품 추출 (단말기별 100% 서로 다른 고유 상품 각각 1:1 할당)
            if specific_nv_mid:
                cur.execute("""
                    SELECT target_id, product_name, mall_product_id, mall_name
                    FROM nshop_list
                    WHERE target_id = %s
                    LIMIT 1
                """, (specific_nv_mid,))
                prod = cur.fetchone()
                products = [prod] * alloc_count if prod else []
            else:
                # 활성화(is_active = 1)된 50개 풀 중 요청 수량(alloc_count=20)만큼 고유 상품 무작위 추출 -> 20대 기기 모두 다른 상품 배정!
                cur.execute("""
                    SELECT target_id, product_name, mall_product_id, mall_name
                    FROM nshop_list
                    WHERE is_active = 1 AND product_name IS NOT NULL AND product_name != ''
                    ORDER BY RAND()
                    LIMIT %s
                """, (alloc_count,))
                products = cur.fetchall()

                if len(products) < alloc_count:
                    cur.execute("""
                        SELECT target_id, product_name, mall_product_id, mall_name
                        FROM nshop_list
                        WHERE product_name IS NOT NULL AND product_name != ''
                        ORDER BY RAND()
                        LIMIT %s
                    """, (alloc_count,))
                    products = cur.fetchall()

            if not products:
                return {
                    "success": False,
                    "is_no_task": True,
                    "message": "nshop_list 테이블에 작업 대상 상품 데이터가 없습니다."
                }

            actual_alloc = min(alloc_count, len(products))
            allocated_tasks = []

            for i in range(actual_alloc):
                dev_id = str(device_ids[i]).strip()
                nnb_row = selected_nnbs[i]
                prod = products[i]

                keyword = prod["product_name"]
                nv_mid = prod["target_id"]
                compare_id = prod["mall_product_id"] if prod["mall_product_id"] else None
                store_name = prod.get("mall_name") or ""
                nnb_val = nnb_row["nnb"]
                buc_val = nnb_row["buc"]

                cur.execute("""
                    INSERT INTO tasks (nnb, buc, keyword, nv_mid, compare_id, store_name, device_id, ip, status, assigned_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ASSIGNED', NOW())
                """, (nnb_val, buc_val, keyword, nv_mid, compare_id, store_name, dev_id, ip))
                new_task_id = cur.lastrowid

                cur.execute("""
                    UPDATE nnbs
                    SET use_count = use_count + 1,
                        last_used_at = NOW(),
                        used_target = %s,
                        device_id = COALESCE(%s, device_id)
                    WHERE id = %s
                """, (nv_mid, dev_id, nnb_row["id"]))

                allocated_tasks.append({
                    "task_id": int(new_task_id),
                    "device_id": dev_id,
                    "keyword": keyword,
                    "nv_mid": nv_mid,
                    "compare_id": compare_id,
                    "store_name": store_name,
                    "nnb": nnb_val,
                    "buc": buc_val,
                    "ip": ip
                })

            res = {
                "success": True,
                "ip": ip,
                "count": len(allocated_tasks),
                "tasks": allocated_tasks
            }
            # 단일 작업 하위 호환 평탄화
            if len(allocated_tasks) == 1:
                for k, v in allocated_tasks[0].items():
                    res[k] = v
            return res

    @staticmethod
    def assign_task(
        task_id: Optional[int] = None,
        min_age_seconds: int = MIN_AGING_SECONDS,
        device_id: Optional[str] = None,
        ip: Optional[str] = None,
        specific_nv_mid: Optional[str] = None
    ) -> Dict[str, Any]:
        """단일 단말기 할당 래퍼 (assign_tasks로 위임)"""
        return TaskService.assign_tasks(
            device_ids=[device_id] if device_id else ["default"],
            ip=ip,
            task_id=task_id,
            specific_nv_mid=specific_nv_mid,
            min_age_seconds=min_age_seconds
        )

    @staticmethod
    def assign_batch(
        device_ids: list,
        ip: Optional[str] = None,
        min_age_seconds: int = MIN_AGING_SECONDS
    ) -> Dict[str, Any]:
        """다중 단말기 할당 래퍼 (assign_tasks로 위임)"""
        return TaskService.assign_tasks(
            device_ids=device_ids,
            ip=ip,
            min_age_seconds=min_age_seconds
        )

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

        # error_code 정밀 추출 (중간실패 상세 코드 보존)
        error_code = payload.get("error_code")
        if not error_code and raw_status not in VALID_STATUSES:
            error_code = raw_status

        # status가 허용된 ENUM이 아닌 경우 (예: TARGET_NOT_FOUND 등) memo에 보존하고 FAILED 매핑
        if raw_status in VALID_STATUSES:
            status_val = raw_status
        else:
            prefix = f"[{raw_status}]"
            if prefix not in result_memo:
                result_memo = f"{prefix} {result_memo}".strip()
            status_val = "FAILED" if any(w in raw_status for w in ("FAIL", "ERR", "NOT_FOUND", "BLOCK", "DENIED", "REJECT", "NO_SHOPPING", "LOGIN")) else "SUCCESS"

        if len(result_memo) > 250:
            result_memo = result_memo[:247] + "..."
        if not result_memo:
            result_memo = None

        search_type = payload.get("search_type")
        rank_info = payload.get("rank_info") or {}

        serp_rank = payload.get("serp_rank") if payload.get("serp_rank") is not None else rank_info.get("serp_rank")
        if serp_rank is not None:
            try:
                serp_rank = int(serp_rank)
            except (ValueError, TypeError):
                serp_rank = None

        shopping_rank = payload.get("shopping_rank") if payload.get("shopping_rank") is not None else rank_info.get("shopping_rank")
        if shopping_rank is not None:
            try:
                shopping_rank = int(shopping_rank)
            except (ValueError, TypeError):
                shopping_rank = None

        shopping_page = payload.get("shopping_page") if payload.get("shopping_page") is not None else rank_info.get("shopping_page")
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
                        error_code = %s,
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
                    error_code,
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
                        task_id, nnb, keyword, nv_mid, store_name, status, error_code, search_type, serp_rank,
                        shopping_rank, shopping_page, match_type, login_detected,
                        duration_seconds, device_id, result_memo, raw_report, assigned_at, completed_at
                    ) VALUES (
                        %s, 'DIRECT_REPORT', 'DIRECT_REPORT', '0', %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, NOW(), NOW()
                    )
                """, (
                    int(task_id),
                    store_name,
                    status_val,
                    error_code,
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
                SELECT task_id, status, error_code, store_name, search_type, serp_rank, shopping_rank, shopping_page,
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
                    "error_code": saved.get("error_code"),
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
                       status, error_code, search_type, serp_rank, shopping_rank, shopping_page,
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
                       status, error_code, search_type, serp_rank, shopping_rank, shopping_page,
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
