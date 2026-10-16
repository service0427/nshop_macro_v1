from flask import Blueprint, request, jsonify
from database import get_db_cursor
import logging

network_bp = Blueprint("network", __name__, url_prefix="/api/v1/network")
logger = logging.getLogger("NetworkRoute")

@network_bp.route("/lte-log", methods=["POST"])
def record_lte_log():
    """LTE 모뎀 토글 및 세션 트래픽(Upload/Download) 기록 및 일일 트래픽 집계 API"""
    data = request.get_json(silent=True) or {}
    cycle = int(data.get("cycle", 0))
    old_ip = data.get("old_ip")
    new_ip = data.get("new_ip")
    is_ip_changed = 1 if data.get("is_ip_changed") else (1 if old_ip != new_ip and new_ip and new_ip != "UNKNOWN" else 0)
    session_upload_bytes = int(data.get("session_upload_bytes", 0))
    session_download_bytes = int(data.get("session_download_bytes", 0))
    total_upload_bytes = int(data.get("total_upload_bytes", 0))
    total_download_bytes = int(data.get("total_download_bytes", 0))
    connect_time_seconds = int(data.get("connect_time_seconds", 0))
    toggle_duration_seconds = float(data.get("toggle_duration_seconds", 0.0))
    status = str(data.get("status", "SUCCESS"))
    device_count = int(data.get("device_count", 20))
    memo = data.get("memo")

    try:
        with get_db_cursor(commit=True) as (cur, _):
            # 1. lte_modem_logs 개별 세션 로그 기록
            cur.execute("""
                INSERT INTO lte_modem_logs (
                    cycle, old_ip, new_ip, is_ip_changed,
                    session_upload_bytes, session_download_bytes,
                    total_upload_bytes, total_download_bytes,
                    connect_time_seconds, toggle_duration_seconds,
                    status, device_count, memo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                cycle, old_ip, new_ip, is_ip_changed,
                session_upload_bytes, session_download_bytes,
                total_upload_bytes, total_download_bytes,
                connect_time_seconds, toggle_duration_seconds,
                status, device_count, memo
            ))
            log_id = cur.lastrowid

            # 2. lte_daily_traffic 일일 누적 사용량 실시간 업데이트
            _update_daily_traffic_record(cur, log_id, total_upload_bytes, total_download_bytes, session_upload_bytes, session_download_bytes)

            return jsonify({
                "success": True,
                "log_id": log_id,
                "message": "LTE modem traffic log and daily aggregate updated successfully."
            }), 201
    except Exception as e:
        logger.error(f"Failed to record lte log: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _ensure_daily_table(cur):
    """lte_daily_traffic 테이블 자동 생성"""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lte_daily_traffic (
            target_date DATE NOT NULL PRIMARY KEY,
            first_log_id BIGINT NOT NULL,
            last_log_id BIGINT NOT NULL,
            first_total_upload_bytes BIGINT NOT NULL DEFAULT 0,
            first_total_download_bytes BIGINT NOT NULL DEFAULT 0,
            first_total_bytes BIGINT NOT NULL DEFAULT 0,
            last_total_upload_bytes BIGINT NOT NULL DEFAULT 0,
            last_total_download_bytes BIGINT NOT NULL DEFAULT 0,
            last_total_bytes BIGINT NOT NULL DEFAULT 0,
            daily_upload_bytes BIGINT NOT NULL DEFAULT 0,
            daily_download_bytes BIGINT NOT NULL DEFAULT 0,
            daily_total_bytes BIGINT NOT NULL DEFAULT 0,
            daily_total_gb DECIMAL(10, 3) NOT NULL DEFAULT 0.000,
            toggle_count INT NOT NULL DEFAULT 0,
            first_seen_at DATETIME NOT NULL,
            last_seen_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_date (target_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)


def _update_daily_traffic_record(cur, log_id, total_up, total_down, session_up, session_down):
    """당일 최초값과 현재 최신값을 비교하여 일일 사용량 갱신"""
    _ensure_daily_table(cur)
    cur.execute("SELECT * FROM lte_daily_traffic WHERE target_date = CURDATE() FOR UPDATE")
    existing = cur.fetchone()

    total_cur = total_up + total_down

    if not existing:
        # 당일 첫 번째 진입: 최초값으로 등록
        cur.execute("""
            INSERT INTO lte_daily_traffic (
                target_date, first_log_id, last_log_id,
                first_total_upload_bytes, first_total_download_bytes, first_total_bytes,
                last_total_upload_bytes, last_total_download_bytes, last_total_bytes,
                daily_upload_bytes, daily_download_bytes, daily_total_bytes, daily_total_gb,
                toggle_count, first_seen_at, last_seen_at
            ) VALUES (
                CURDATE(), %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                1, NOW(), NOW()
            )
        """, (
            log_id, log_id,
            total_up, total_down, total_cur,
            total_up, total_down, total_cur,
            session_up, session_down, session_up + session_down,
            round((session_up + session_down) / (1024 * 1024 * 1024), 3)
        ))
    else:
        # 당일 후속 진입: 최신값 업데이트 및 최초값 대비 사용량 차분 계산
        first_up = existing["first_total_upload_bytes"]
        first_down = existing["first_total_download_bytes"]

        # 모뎀 하드웨어 누적 카운터 기반 차분 계산
        daily_up = total_up - first_up if total_up >= first_up else existing["daily_upload_bytes"] + session_up
        daily_down = total_down - first_down if total_down >= first_down else existing["daily_download_bytes"] + session_down
        daily_total = daily_up + daily_down
        daily_gb = round(daily_total / (1024 * 1024 * 1024), 3)

        cur.execute("""
            UPDATE lte_daily_traffic
            SET last_log_id = %s,
                last_total_upload_bytes = %s,
                last_total_download_bytes = %s,
                last_total_bytes = %s,
                daily_upload_bytes = %s,
                daily_download_bytes = %s,
                daily_total_bytes = %s,
                daily_total_gb = %s,
                toggle_count = toggle_count + 1,
                last_seen_at = NOW()
            WHERE target_date = CURDATE()
        """, (
            log_id,
            total_up, total_down, total_cur,
            daily_up, daily_down, daily_total, daily_gb
        ))


@network_bp.route("/lte-log", methods=["GET"])
def get_lte_logs():
    """최근 LTE 모뎀 토글 및 트래픽 기록 조회 API"""
    limit = min(max(int(request.args.get("limit", 20)), 1), 100)
    try:
        with get_db_cursor(commit=False) as (cur, _):
            cur.execute("""
                SELECT id, cycle, old_ip, new_ip, is_ip_changed,
                       session_upload_bytes, session_download_bytes,
                       total_upload_bytes, total_download_bytes,
                       connect_time_seconds, toggle_duration_seconds,
                       status, device_count, memo, created_at
                FROM lte_modem_logs
                ORDER BY id DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            return jsonify({
                "success": True,
                "count": len(rows),
                "items": rows
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@network_bp.route("/daily-traffic", methods=["GET"])
def get_daily_traffic():
    """
    [일자별 LTE 동글 트래픽 하루 사용량 조회 API]
    - target_date (기본: 오늘)
    - 당일 최초값, 현재값, 순수 하루 사용량(GB/MB), 토글 횟수 반환
    """
    target_date = request.args.get("date")
    try:
        with get_db_cursor(commit=True) as (cur, _):
            _ensure_daily_table(cur)

            # 1. 기존 lte_modem_logs로부터 전체 일자 백필/동기화 실행
            _sync_all_daily_from_logs(cur)

            # 2. 조회 대상 일자 쿼리
            if target_date:
                cur.execute("SELECT * FROM lte_daily_traffic WHERE target_date = %s", (target_date,))
            else:
                cur.execute("SELECT * FROM lte_daily_traffic ORDER BY target_date DESC LIMIT 7")
            rows = cur.fetchall()

            # 오늘 데이터 상세 요약
            cur.execute("SELECT * FROM lte_daily_traffic WHERE target_date = CURDATE()")
            today_row = cur.fetchone()

            # 오늘 세션 트래픽 단순 합산 대조값
            cur.execute("""
                SELECT 
                    COUNT(*) as today_toggles,
                    COALESCE(SUM(session_upload_bytes), 0) as sum_session_up,
                    COALESCE(SUM(session_download_bytes), 0) as sum_session_down,
                    COALESCE(SUM(session_upload_bytes + session_download_bytes), 0) as sum_session_total
                FROM lte_modem_logs
                WHERE DATE(created_at) = CURDATE()
            """)
            today_session_sum = cur.fetchone()

            return jsonify({
                "success": True,
                "today": today_row,
                "today_session_sum": {
                    "total_toggles": today_session_sum["today_toggles"],
                    "sum_upload_mb": round(today_session_sum["sum_session_up"] / (1024 * 1024), 2),
                    "sum_download_mb": round(today_session_sum["sum_session_down"] / (1024 * 1024), 2),
                    "sum_total_mb": round(today_session_sum["sum_session_total"] / (1024 * 1024), 2),
                    "sum_total_gb": round(today_session_sum["sum_session_total"] / (1024 * 1024 * 1024), 3)
                },
                "history": rows
            }), 200
    except Exception as e:
        logger.error(f"Failed to get daily traffic: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _sync_all_daily_from_logs(cur):
    """lte_modem_logs의 과거 기록으로부터 lte_daily_traffic 전체 일자 자동 집계 동기화"""
    cur.execute("""
        SELECT DISTINCT DATE(created_at) as log_date
        FROM lte_modem_logs
        ORDER BY log_date ASC
    """)
    dates = [r["log_date"] for r in cur.fetchall() if r["log_date"]]

    for d in dates:
        # 해당 일자의 첫 번째 로그
        cur.execute("""
            SELECT id, total_upload_bytes, total_download_bytes, created_at
            FROM lte_modem_logs
            WHERE DATE(created_at) = %s AND total_download_bytes > 0
            ORDER BY id ASC
            LIMIT 1
        """, (d,))
        first_r = cur.fetchone()

        # 해당 일자의 마지막 로그
        cur.execute("""
            SELECT id, total_upload_bytes, total_download_bytes, created_at
            FROM lte_modem_logs
            WHERE DATE(created_at) = %s AND total_download_bytes > 0
            ORDER BY id DESC
            LIMIT 1
        """, (d,))
        last_r = cur.fetchone()

        # 해당 일자 총 토글 수 및 세션 합계
        cur.execute("""
            SELECT COUNT(*) as cnt,
                   COALESCE(SUM(session_upload_bytes), 0) as s_up,
                   COALESCE(SUM(session_download_bytes), 0) as s_down
            FROM lte_modem_logs
            WHERE DATE(created_at) = %s
        """, (d,))
        agg = cur.fetchone()

        if not first_r or not last_r:
            continue

        f_up = first_r["total_upload_bytes"]
        f_down = first_r["total_download_bytes"]
        f_tot = f_up + f_down

        l_up = last_r["total_upload_bytes"]
        l_down = last_r["total_download_bytes"]
        l_tot = l_up + l_down

        # 차분 계산 (하드웨어 누적 카운터 기준)
        if l_up >= f_up and l_down >= f_down:
            d_up = l_up - f_up
            d_down = l_down - f_down
        else:
            # 리셋된 경우 세션 합계 활용
            d_up = agg["s_up"]
            d_down = agg["s_down"]

        # 첫 로그의 세션 바이트를 감안 (첫 로그도 당일 사용량이므로 세션 바이트 가산)
        d_tot = d_up + d_down
        if d_tot == 0 and agg["cnt"] > 0:
            d_tot = agg["s_up"] + agg["s_down"]
            d_up = agg["s_up"]
            d_down = agg["s_down"]

        d_gb = round(d_tot / (1024 * 1024 * 1024), 3)

        cur.execute("""
            INSERT INTO lte_daily_traffic (
                target_date, first_log_id, last_log_id,
                first_total_upload_bytes, first_total_download_bytes, first_total_bytes,
                last_total_upload_bytes, last_total_download_bytes, last_total_bytes,
                daily_upload_bytes, daily_download_bytes, daily_total_bytes, daily_total_gb,
                toggle_count, first_seen_at, last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                last_log_id = VALUES(last_log_id),
                last_total_upload_bytes = VALUES(last_total_upload_bytes),
                last_total_download_bytes = VALUES(last_total_download_bytes),
                last_total_bytes = VALUES(last_total_bytes),
                daily_upload_bytes = VALUES(daily_upload_bytes),
                daily_download_bytes = VALUES(daily_download_bytes),
                daily_total_bytes = VALUES(daily_total_bytes),
                daily_total_gb = VALUES(daily_total_gb),
                toggle_count = VALUES(toggle_count),
                last_seen_at = VALUES(last_seen_at)
        """, (
            d, first_r["id"], last_r["id"],
            f_up, f_down, f_tot,
            l_up, l_down, l_tot,
            d_up, d_down, d_tot, d_gb,
            agg["cnt"], first_r["created_at"], last_r["created_at"]
        ))
