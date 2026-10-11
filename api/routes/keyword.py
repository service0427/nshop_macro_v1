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

    where_clauses = ["product_name IS NOT NULL", "product_name != ''"]
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
