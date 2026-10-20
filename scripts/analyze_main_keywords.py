# ==============================================================================
# scripts/analyze_main_keywords.py
#
# [메인급 핵심 키워드 vs 서브 키워드 순위 연동 분석기]
# - 10/19 대비 10/20 순위 변동 추적
# - 메인 키워드(1~2어절 단문형) 순위 상승 효과 정량 분석
# - 검색어당 일일 타수(10회 미만 적정 타수)와의 상관관계 분석
# ==============================================================================

import json
from collections import defaultdict
from typing import Dict, Any, List

def main():
    data = defaultdict(lambda: defaultdict(list))
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
                success = obj.get("success", False)
                s_rank = obj.get("serp_rank")
                sh_rank = obj.get("shopping_rank")
                js_rank = obj.get("js_target_rank")
                
                rank_val = None
                rank_type = None
                if s_rank is not None and s_rank > 0:
                    rank_val = s_rank
                    rank_type = "SERP"
                elif sh_rank is not None and sh_rank > 0:
                    rank_val = sh_rank
                    rank_type = "SHOP"
                elif js_rank is not None and js_rank > 0:
                    rank_val = js_rank
                    rank_type = "SHOP"
                
                data[(mid, store, kw)][date_str].append({
                    "rank_val": rank_val,
                    "rank_type": rank_type,
                    "success": success
                })

    # Group by Product (mid, store)
    products = defaultdict(lambda: {"main": [], "sub": []})

    for (mid, store, kw), dates in data.items():
        if "1019" not in dates or "1020" not in dates:
            continue

        r19_valid = [x["rank_val"] for x in dates["1019"] if x["rank_val"] is not None]
        r20_valid = [x["rank_val"] for x in dates["1020"] if x["rank_val"] is not None]

        if not r19_valid or not r20_valid:
            continue

        t19 = [x["rank_type"] for x in dates["1019"] if x["rank_type"] is not None][-1]
        t20 = [x["rank_type"] for x in dates["1020"] if x["rank_type"] is not None][-1]

        r19 = r19_valid[0] # 시작 순위
        r20 = r20_valid[-1] # 최종 순위
        diff = r19 - r20

        hits_19 = sum(1 for x in dates["1019"] if x["success"])
        hits_20 = sum(1 for x in dates["1020"] if x["success"])

        words = kw.split()
        # 메인 키워드 판정 기준: 1어절이거나, 2어절 이하이면서 글자수 7자 이하
        is_main = len(words) == 1 or (len(words) == 2 and len(kw) <= 8)

        entry = {
            "mid": mid,
            "store": store,
            "kw": kw,
            "is_main": is_main,
            "r19": r19,
            "t19": t19,
            "r20": r20,
            "t20": t20,
            "diff": diff,
            "hits_19": hits_19,
            "hits_20": hits_20
        }

        if is_main:
            products[(mid, store)]["main"].append(entry)
        else:
            products[(mid, store)]["sub"].append(entry)

    print("=" * 86)
    print("🏆 [상품별 서브키워드 분산 타격 ➔ 메인키워드 동반 상승 연동 분석]")
    print("=" * 86)

    total_main = 0
    climbed_main = 0
    maintained_main = 0

    for (mid, store), grp in products.items():
        main_list = grp["main"]
        sub_list = grp["sub"]

        if not main_list:
            continue

        print(f"\n📦 상품: [{store}] (MID: {mid})")
        print("  🔹 [서브키워드 타격 현황 (10회 미만 분산 유입)]:")
        sub_climbs = 0
        for s in sub_list[:4]: # 상위 4개 서브키워드 샘플
            d_str = f"+{s['diff']}위" if s['diff'] > 0 else (f"{s['diff']}위" if s['diff'] < 0 else "유지")
            icon = "🔺" if s['diff'] > 0 else ("🔻" if s['diff'] < 0 else "➖")
            print(f"     {icon} '{s['kw']}': {s['t19']} {s['r19']}위 -> {s['t20']} {s['r20']}위 ({d_str:>6}) | 19일: {s['hits_19']}타, 20일: {s['hits_20']}타")
            if s['diff'] > 0:
                sub_climbs += 1
        if len(sub_list) > 4:
            print(f"     ... 외 서브키워드 {len(sub_list)-4}개 분산 타격 진행")

        print("  👑 [메인 키워드 순위 반응]:")
        for m in main_list:
            total_main += 1
            d_str = f"+{m['diff']}위 상승 🚀" if m['diff'] > 0 else (f"{m['diff']}위 하락" if m['diff'] < 0 else "유지 (최상위 방어)")
            icon = "🔺" if m['diff'] > 0 else ("🔻" if m['diff'] < 0 else "➖")
            if m['diff'] > 0:
                climbed_main += 1
            elif m['diff'] == 0:
                maintained_main += 1
            print(f"     {icon} '{m['kw']}': {m['t19']} {m['r19']}위 -> {m['t20']} {m['r20']}위 ({d_str}) | 직접타수: {m['hits_20']}타")

    print("\n" + "=" * 86)
    print(f"📊 [메인 키워드 종합 지표 요약]")
    print(f"• 추적된 메인급 키워드: 총 {total_main}개")
    print(f"• 메인 키워드 상승: {climbed_main}개 ({(climbed_main/total_main*100):.1f}%)")
    print(f"• 메인 키워드 유지: {maintained_main}개 ({(maintained_main/total_main*100):.1f}%)")
    positive_rate = ((climbed_main + maintained_main) / total_main * 100) if total_main > 0 else 0
    print(f"• 순위 상승 및 최상위 방어율: {positive_rate:.1f}%")
    print("=" * 86 + "\n")

if __name__ == "__main__":
    main()
