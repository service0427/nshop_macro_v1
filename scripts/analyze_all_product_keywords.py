# ==============================================================================
# scripts/analyze_all_product_keywords.py
#
# [전체 상품군별 전체 키워드 순위 변동 전수 조사 보고서]
# ==============================================================================

import json
from collections import defaultdict
from typing import Dict, Any, List

def main():
    # store -> mid -> kw -> date -> list of ranks
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    files = ["logs/execution_history_20261019.jsonl", "logs/execution_history_20261020.jsonl"]

    for f in files:
        date_str = "1019" if "1019" in f else "1020"
        with open(f, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                kw = obj.get("keyword", "").strip()
                mid = obj.get("nv_mid")
                store = obj.get("store_name") or "미지정"
                s_rank = obj.get("serp_rank")
                sh_rank = obj.get("shopping_rank")
                js_rank = obj.get("js_target_rank")
                
                rank_val = s_rank or sh_rank or js_rank
                if rank_val and rank_val > 0:
                    data[store][mid][kw][date_str].append(rank_val)

    print("=" * 88)
    print(f"📋 [등록된 전체 상품({len(data)}개 스토어) 키워드 순위 변동 전수 조사 리포트]")
    print("=" * 88)

    all_products = []

    for store, mids in data.items():
        for mid, kws in mids.items():
            tracked_both = []
            only_19 = []
            only_20 = []

            for kw, dates in kws.items():
                if "1019" in dates and "1020" in dates:
                    r19 = dates["1019"][0] # 19일 첫 관측
                    r20 = dates["1020"][-1] # 20일 최신 관측
                    diff = r19 - r20
                    tracked_both.append({
                        "kw": kw,
                        "r19": r19,
                        "r20": r20,
                        "diff": diff
                    })
                elif "1019" in dates:
                    only_19.append((kw, dates["1019"][-1]))
                elif "1020" in dates:
                    only_20.append((kw, dates["1020"][-1]))

            climbed = [x for x in tracked_both if x["diff"] > 0]
            maintained = [x for x in tracked_both if x["diff"] == 0]
            dropped = [x for x in tracked_both if x["diff"] < 0]

            all_products.append({
                "store": store,
                "mid": mid,
                "tracked_both": tracked_both,
                "climbed": climbed,
                "maintained": maintained,
                "dropped": dropped,
                "only_19": only_19,
                "only_20": only_20
            })

    # Sort by positive rate or total climbs
    all_products.sort(key=lambda x: (len(x["climbed"]) * 100 + len(x["maintained"])), reverse=True)

    for p in all_products:
        tot = len(p["tracked_both"])
        if tot == 0:
            continue
        c_cnt = len(p["climbed"])
        m_cnt = len(p["maintained"])
        d_cnt = len(p["dropped"])
        pos_rate = ((c_cnt + m_cnt) / tot * 100) if tot > 0 else 0

        print(f"\n📦 [{p['store']}] (MID: {p['mid']}) | 추적 키워드: {tot}개 | 긍정/방어율: {pos_rate:.1f}% (🔺상승 {c_cnt}, 👑유지 {m_cnt}, 🔻하락 {d_cnt})")

        # 1. 상승 키워드
        if p["climbed"]:
            print("   🔺 [순위 상승 키워드]:")
            for item in sorted(p["climbed"], key=lambda x: x["diff"], reverse=True):
                print(f"      • '{item['kw']}': {item['r19']}위 -> {item['r20']}위 (+{item['diff']}위 상승 🚀)")

        # 2. 최상위 유지 키워드 (상위 5위 이내 위주)
        top_m = [x for x in p["maintained"] if x["r20"] <= 5]
        if top_m:
            print("   👑 [최상위(1~5위) 견고 유지 키워드]:")
            for item in top_m:
                print(f"      • '{item['kw']}': {item['r20']}위 유지")

        # 3. 신규 20일 진입 키워드 (어제 미관측 -> 오늘 신규 포착)
        if p["only_20"]:
            top_new = [x for x in p["only_20"] if x[1] <= 10]
            if top_new:
                print("   ✨ [오늘 20일 신규 순위권(Top 10) 포착 키워드]:")
                for kw, r in top_new:
                    print(f"      • '{kw}': 신규 {r}위 안착")

    print("\n" + "=" * 88)

if __name__ == "__main__":
    main()
