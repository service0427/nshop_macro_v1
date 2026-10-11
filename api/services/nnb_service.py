import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from database import get_db_cursor
from utils.generator import validate_nnb
from core.harvester import harvest_single_packet, get_public_ip
from config import MIN_AGING_SECONDS, TARGET_NNB_POOL_SIZE

class NNBService:
    @staticmethod
    def bank_nnb(
        nnb: str,
        buc: str = "",
        source: str = "APP_WARMUP",
        device_id: Optional[str] = None,
        ip: Optional[str] = None,
        memo: Optional[str] = None,
        increment_if_exists: bool = True
    ) -> Dict[str, Any]:
        """
        [토큰 저금] 앱 웜업이나 단말기에서 수집된 순정 NNB/BUC를 DB 풀에 저금
        - 기존에 이미 존재하면 use_count 증가 또는 갱신
        - 신규인 경우 status='AGING'으로 등록하여 숙성 대기 시작
        """
        nnb = nnb.strip().upper()
        if not validate_nnb(nnb):
            raise ValueError(f"유효하지 않은 NNB 형식입니다: {nnb} (13자리 대문자/숫자 필요)")

        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                SELECT id, nnb, buc, use_count, status, memo, ip, device_id, source, created_at,
                       TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                FROM nnbs WHERE nnb = %s
            """, (nnb,))
            existing = cur.fetchone()

            if existing:
                if increment_if_exists:
                    cur.execute("""
                        UPDATE nnbs
                        SET use_count = use_count + 1,
                            buc = COALESCE(NULLIF(%s, ''), buc),
                            device_id = COALESCE(%s, device_id),
                            ip = COALESCE(%s, ip),
                            memo = COALESCE(%s, memo),
                            last_used_at = NOW()
                        WHERE id = %s
                    """, (buc, device_id, ip, memo, existing["id"]))

                cur.execute("""
                    SELECT id, nnb, buc, use_count, status, memo, ip, device_id, source, created_at, last_used_at,
                           TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                    FROM nnbs WHERE id = %s
                """, (existing["id"],))
                item = cur.fetchone()
                return {
                    "action": "UPDATED",
                    "nnb": item["nnb"],
                    "buc": item["buc"],
                    "use_count": item["use_count"],
                    "status": item["status"],
                    "source": item["source"],
                    "device_id": item["device_id"],
                    "created_at": item["created_at"].strftime("%Y-%m-%d %H:%M:%S") if item["created_at"] else None,
                    "age_seconds": item["age_seconds"]
                }
            else:
                cur.execute("""
                    INSERT INTO nnbs (nnb, buc, use_count, status, memo, ip, device_id, source, created_at)
                    VALUES (%s, %s, 0, 'AGING', %s, %s, %s, %s, NOW())
                """, (nnb, buc, memo, ip, device_id, source))
                new_id = cur.lastrowid

                cur.execute("""
                    SELECT id, nnb, buc, use_count, status, memo, ip, device_id, source, created_at,
                           TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                    FROM nnbs WHERE id = %s
                """, (new_id,))
                item = cur.fetchone()
                return {
                    "action": "BANKED",
                    "nnb": item["nnb"],
                    "buc": item["buc"],
                    "use_count": item["use_count"],
                    "status": item["status"],
                    "source": item["source"],
                    "device_id": item["device_id"],
                    "created_at": item["created_at"].strftime("%Y-%m-%d %H:%M:%S") if item["created_at"] else None,
                    "age_seconds": item["age_seconds"]
                }

    @staticmethod
    def harvest_and_save(
        count: int = 1,
        proxy: Optional[str] = None,
        device_id: Optional[str] = None,
        memo: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        lcs.naver.com/m 패킷을 직접 호출하여 정품 NNB+BUC를 발급받아 DB에 적재
        """
        results = []
        cur_ip = get_public_ip() if not proxy else proxy

        for _ in range(count):
            packet = harvest_single_packet(proxy=proxy)
            if not packet:
                continue

            with get_db_cursor(commit=True) as (cur, conn):
                cur.execute("""
                    INSERT INTO nnbs (nnb, buc, use_count, status, memo, ip, device_id, source, dur_sec, created_at)
                    VALUES (%s, %s, 0, 'AGING', %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE buc = VALUES(buc), dur_sec = VALUES(dur_sec)
                """, (
                    packet["nnb"],
                    packet["buc"],
                    memo,
                    cur_ip,
                    device_id,
                    packet["source"],
                    packet["dur_sec"]
                ))
                new_id = cur.lastrowid
                results.append({
                    "nnb": packet["nnb"],
                    "buc": packet["buc"],
                    "dur_sec": packet["dur_sec"],
                    "ip": cur_ip,
                    "device_id": device_id,
                    "source": packet["source"],
                    "status": "AGING"
                })
            time.sleep(0.05)  # 짧은 쿨타임

        return results

    @staticmethod
    def topup_pool(
        target_size: int = TARGET_NNB_POOL_SIZE,
        device_id: Optional[str] = None,
        proxy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        [수위 조절기] 활성 NNB(READY + AGING) 수량이 target_size 미달 시 패킷으로 즉시 자동 보충
        """
        with get_db_cursor(commit=False) as (cur, _):
            cur.execute("""
                SELECT COUNT(*) as active_count
                FROM nnbs
                WHERE status IN ('AGING', 'READY', 'ACTIVE')
            """)
            active_count = cur.fetchone()["active_count"]

        needed = max(0, target_size - active_count)
        if needed <= 0:
            return {
                "needed": 0,
                "collected": 0,
                "current_active_pool": active_count,
                "target_size": target_size,
                "message": f"수위 충족: 현재 활성 풀 {active_count}개 >= 목표치 {target_size}개"
            }

        # 부족분 채굴
        harvested = NNBService.harvest_and_save(
            count=needed,
            proxy=proxy,
            device_id=device_id,
            memo="WATERMARK_TOPUP"
        )

        return {
            "needed": needed,
            "collected": len(harvested),
            "current_active_pool": active_count + len(harvested),
            "target_size": target_size,
            "harvested_items": harvested
        }

    @staticmethod
    def assign_nnb(
        device_id: Optional[str] = None,
        ip: Optional[str] = None,
        min_age_seconds: int = 1200,
        memo: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        [NNB 단독 할당]
        - 키워드, 상품 정보 없이 20분(1200초) 이상 숙성된 NNB+BUC 토큰만 단독 할당
        - 동시성 제어: SELECT ... FOR UPDATE
        - use_count + 1, last_used_at = NOW(), device_id, ip 갱신
        """
        min_age_seconds = max(1200, int(min_age_seconds or 1200))

        with get_db_cursor(commit=True) as (cur, conn):
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
            selected = cur.fetchone()

            if not selected or int(selected.get("age_seconds") or 0) < 1200:
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

            cur.execute("""
                UPDATE nnbs
                SET use_count = use_count + 1,
                    status = 'READY',
                    last_used_at = NOW(),
                    device_id = COALESCE(%s, device_id),
                    ip = COALESCE(%s, ip),
                    memo = COALESCE(%s, memo)
                WHERE id = %s
            """, (device_id, ip, memo, selected["id"]))

            return {
                "success": True,
                "nnb": selected["nnb"],
                "buc": selected["buc"],
                "device_id": device_id,
                "ip": ip,
                "use_count": int(selected["use_count"]) + 1,
                "age_seconds": int(selected["age_seconds"])
            }

    @staticmethod
    def acquire_nnb_for_job(
        min_age_seconds: int = MIN_AGING_SECONDS,
        target: Optional[str] = None,
        device_id: Optional[str] = None,
        memo: Optional[str] = None,
        mark_as_used: bool = False
    ) -> Dict[str, Any]:
        """
        [작업 호출] created_at 기준 min_age_seconds(기본 1200초) 이상 숙성된 토큰 선점
        - 동시성 안전: SELECT ... FOR UPDATE 락
        - 선점 시 use_count += 1, last_used_at = NOW(), used_target = target
        - mark_as_used=True 지정 시 즉시 status='USED'로 변경
        """
        with get_db_cursor(commit=True) as (cur, conn):
            # 1200초 이상 숙성된 유효 토큰 선점 (가장 오래되고 사용횟수 적은 순)
            query = """
                SELECT id, nnb, buc, use_count, status, memo, ip, device_id, source, created_at, last_used_at,
                       TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                FROM nnbs
                WHERE status IN ('AGING', 'READY', 'ACTIVE')
                  AND created_at <= NOW() - INTERVAL %s SECOND
                ORDER BY use_count ASC, created_at ASC, id ASC
                LIMIT 1
                FOR UPDATE
            """
            cur.execute(query, (min_age_seconds,))
            selected = cur.fetchone()

            if not selected:
                return {
                    "success": False,
                    "allocated": False,
                    "message": f"할당 가능한 숙성 NNB가 없습니다. (created_at 기준 {min_age_seconds}초 초과 항목 없음)",
                    "data": None
                }

            new_status = "USED" if mark_as_used else "READY"
            cur.execute("""
                UPDATE nnbs
                SET use_count = use_count + 1,
                    status = %s,
                    last_used_at = NOW(),
                    used_target = COALESCE(%s, used_target),
                    device_id = COALESCE(%s, device_id),
                    memo = COALESCE(%s, memo)
                WHERE id = %s
            """, (new_status, target, device_id, memo, selected["id"]))

            cur.execute("""
                SELECT id, nnb, buc, use_count, status, memo, ip, device_id, source,
                       created_at, last_used_at, used_target,
                       TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                FROM nnbs WHERE id = %s
            """, (selected["id"],))
            updated = cur.fetchone()

            return {
                "success": True,
                "allocated": True,
                "message": f"작업용 정품 NNB 할당 성공 (경과: {updated['age_seconds']}초, 사용횟수: {updated['use_count']}회)",
                "data": {
                    "nnb": updated["nnb"],
                    "buc": updated["buc"],
                    "use_count": updated["use_count"],
                    "status": updated["status"],
                    "age_seconds": updated["age_seconds"],
                    "min_required_age": min_age_seconds,
                    "created_at": updated["created_at"].strftime("%Y-%m-%d %H:%M:%S") if updated["created_at"] else None,
                    "last_used_at": updated["last_used_at"].strftime("%Y-%m-%d %H:%M:%S") if updated["last_used_at"] else None,
                    "used_target": updated["used_target"],
                    "device_id": updated["device_id"],
                    "source": updated["source"]
                }
            }

    @staticmethod
    def mark_nnb_used(nnb: str, target: Optional[str] = None, memo: Optional[str] = None) -> bool:
        """타격 완료된 NNB를 USED 상태로 확정 갱신"""
        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                UPDATE nnbs
                SET status = 'USED',
                    last_used_at = NOW(),
                    used_target = COALESCE(%s, used_target),
                    memo = COALESCE(%s, memo)
                WHERE nnb = %s
            """, (target, memo, nnb.strip().upper()))
            return cur.rowcount > 0

    @staticmethod
    def get_pool_status(min_age_seconds: int = MIN_AGING_SECONDS) -> Dict[str, Any]:
        """
        풀 전체 상태 추적:
        - ready_count (1200초 이상 숙성 완료)
        - aging_count (1200초 미만 숙성 중)
        - used_count  (작업 완료)
        - total
        """
        with get_db_cursor(commit=False) as (cur, _):
            # 상태 및 숙성 시간 기준 집계
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN use_count = 0 AND status IN ('AGING', 'READY', 'ACTIVE') THEN 1 ELSE 0 END) AS zero_use_count,
                    SUM(CASE WHEN status != 'USED' AND status != 'BLOCKED' AND created_at <= NOW() - INTERVAL %s SECOND THEN 1 ELSE 0 END) AS ready_count,
                    SUM(CASE WHEN status != 'USED' AND status != 'BLOCKED' AND created_at > NOW() - INTERVAL %s SECOND THEN 1 ELSE 0 END) AS aging_count,
                    SUM(CASE WHEN status = 'USED' THEN 1 ELSE 0 END) AS used_count,
                    SUM(CASE WHEN status = 'BLOCKED' THEN 1 ELSE 0 END) AS blocked_count,
                    COALESCE(SUM(use_count), 0) AS total_use_count
                FROM nnbs
            """, (min_age_seconds, min_age_seconds))
            summary = cur.fetchone()

            # 최근 항목 샘플
            cur.execute("""
                SELECT nnb, buc, status, use_count, source, device_id, created_at,
                       TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds,
                       used_target
                FROM nnbs
                ORDER BY created_at DESC
                LIMIT 30
            """)
            recent_items = cur.fetchall()

            for item in recent_items:
                if item["created_at"]:
                    item["created_at"] = item["created_at"].strftime("%Y-%m-%d %H:%M:%S")

            return {
                "total": int(summary["total"] or 0),
                "zero_use_count": int(summary["zero_use_count"] or 0),
                "ready_count": int(summary["ready_count"] or 0),
                "aging_count": int(summary["aging_count"] or 0),
                "used_count": int(summary["used_count"] or 0),
                "blocked_count": int(summary["blocked_count"] or 0),
                "total_use_count": int(summary["total_use_count"] or 0),
                "min_age_seconds": min_age_seconds,
                "recent_items": recent_items
            }
