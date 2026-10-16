from flask import Blueprint, request, jsonify
from database import get_db_cursor

keyword_bp = Blueprint("keyword", __name__, url_prefix="/api/v1/keyword")

@keyword_bp.route("/random", methods=["GET"])
def get_random_keyword():
    """
    [키워드 랜덤 조회 API]
    - keyword: nshop_list의 product_name 값
    - nv_mid: nshop_list의 target_id
    - compare_id: nshop_list의 mall_product_id (없으면 target_id 대체 또는 빈값)
    - Query 파라미터:
        - count: 반환 개수 (기본 1, 최대 50)
        - with_compare: compare_id(mall_product_id)가 존재하는 상품만 조회할지 여부 (기본 false)
    """
    count = min(max(int(request.args.get("count", 1)), 1), 50)
    with_compare = request.args.get("with_compare", "false").lower() in ("true", "1")

    where_clauses = ["is_active = 1", "product_name IS NOT NULL", "product_name != ''"]
    if with_compare:
        where_clauses.append("mall_product_id IS NOT NULL AND mall_product_id != ''")

    where_sql = " AND ".join(where_clauses)

    try:
        with get_db_cursor(commit=False) as (cur, _):
            query = f"""
                SELECT id, target_id, product_name, product_title, mall_product_id, mall_name, price
                FROM nshop_list
                WHERE {where_sql}
                ORDER BY RAND()
                LIMIT %s
            """
            cur.execute(query, (count,))
            rows = cur.fetchall()

            if not rows:
                return jsonify({"success": False, "message": "일치하는 키워드/상품 데이터가 없습니다.", "data": None}), 404

            formatted = []
            for r in rows:
                compare_id = r["mall_product_id"] if r["mall_product_id"] else None
                formatted.append({
                    "keyword": r["product_name"],
                    "nv_mid": r["target_id"],
                    "compare_id": compare_id,
                    "product_title": r["product_title"],
                    "mall_name": r["mall_name"],
                    "price": r["price"]
                })

            if count == 1:
                return jsonify({
                    "success": True,
                    "keyword": formatted[0]["keyword"],
                    "nv_mid": formatted[0]["nv_mid"],
                    "compare_id": formatted[0]["compare_id"],
                    "data": formatted[0]
                }), 200
            else:
                return jsonify({
                    "success": True,
                    "count": len(formatted),
                    "items": formatted
                }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@keyword_bp.route("/active-list", methods=["GET"])
def get_active_list():
    """현재 활성화(is_active = 1)된 타겟 상품 목록 반환"""
    try:
        with get_db_cursor(commit=False) as (cur, _):
            cur.execute("""
                SELECT id, target_id, product_name, product_title, is_active, updated_at
                FROM nshop_list
                WHERE is_active = 1
                ORDER BY id ASC
            """)
            rows = cur.fetchall()
            return jsonify({
                "success": True,
                "count": len(rows),
                "data": rows
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@keyword_bp.route("/toggle", methods=["POST"])
def toggle_keyword():
    """타겟 상품 개별 ON/OFF 토글 API"""
    data = request.get_json(silent=True) or {}
    target_id = str(data.get("target_id") or data.get("nv_mid") or "").strip()
    is_active = data.get("is_active")

    if not target_id:
        return jsonify({"success": False, "error": "target_id (또는 nv_mid)는 필수입니다."}), 400

    try:
        with get_db_cursor(commit=True) as (cur, _):
            if is_active is None:
                # 상태 반전
                cur.execute("UPDATE nshop_list SET is_active = IF(is_active = 1, 0, 1) WHERE target_id = %s", (target_id,))
            else:
                new_state = 1 if bool(is_active) else 0
                cur.execute("UPDATE nshop_list SET is_active = %s WHERE target_id = %s", (new_state, target_id))

            if cur.rowcount == 0:
                return jsonify({"success": False, "error": f"일치하는 target_id '{target_id}'를 찾을 수 없습니다."}), 404

            cur.execute("SELECT id, target_id, product_name, is_active FROM nshop_list WHERE target_id = %s", (target_id,))
            row = cur.fetchone()
            return jsonify({
                "success": True,
                "message": f"상품 {target_id}의 활성 상태가 {'ON' if row['is_active'] else 'OFF'}로 변경되었습니다.",
                "data": row
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
