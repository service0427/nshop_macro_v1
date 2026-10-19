import json
import glob
import os
from collections import defaultdict

def main():
    files = sorted(glob.glob("logs/execution_history_202610*.jsonl"))

    data = defaultdict(lambda: defaultdict(list))

    for f in files:
        date_str = os.path.basename(f).replace("execution_history_", "").replace(".jsonl", "")
        with open(f, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    kw = obj.get("keyword")
                    mid = obj.get("nv_mid")
                    store = obj.get("store_name") or "미지정"
                    prod = f"{kw} ({store})"
                    success = obj.get("success", False)
                    status = obj.get("status")
                    s_rank = obj.get("serp_rank")
                    sh_rank = obj.get("shopping_rank")
                    js_rank = obj.get("js_target_rank")
                    
                    rank_str = None
                    rank_num = None
                    rank_type = None
                    if s_rank is not None:
                        rank_str = f"SERP {s_rank}위"
                        rank_num = s_rank
                        rank_type = "SERP"
                    elif sh_rank is not None:
                        rank_str = f"SHOP {sh_rank}위"
                        rank_num = sh_rank
                        rank_type = "SHOP"
                    elif js_rank is not None:
                        rank_str = f"SHOP {js_rank}위"
                        rank_num = js_rank
                        rank_type = "SHOP"
                    
                    ts = obj.get("timestamp")
                    
                    data[prod][date_str].append({
                        "ts": ts,
                        "kw": kw,
                        "store": store,
                        "mid": mid,
                        "success": success,
                        "status": status,
                        "rank_str": rank_str,
                        "rank_num": rank_num,
                        "rank_type": rank_type
                    })
                except Exception:
                    pass

    report = []
    for prod, dates in data.items():
        cnt_18 = sum(1 for x in dates.get("20261018", []) if x["success"])
        cnt_19 = sum(1 for x in dates.get("20261019", []) if x["success"])
        tot = cnt_18 + cnt_19
        
        ranks_18 = [x for x in dates.get("20261018", []) if x["rank_str"] is not None]
        ranks_19 = [x for x in dates.get("20261019", []) if x["rank_str"] is not None]
        
        first_r18 = ranks_18[0]["rank_str"] if ranks_18 else "미발견"
        last_r18 = ranks_18[-1]["rank_str"] if ranks_18 else "미발견"
        first_r19 = ranks_19[0]["rank_str"] if ranks_19 else "미발견"
        last_r19 = ranks_19[-1]["rank_str"] if ranks_19 else "미발견"
        
        all_ranks = ranks_18 + ranks_19
        if all_ranks:
            start_rank = all_ranks[0]
            end_rank = all_ranks[-1]
            s_str = start_rank["rank_str"]
            e_str = end_rank["rank_str"]
            if start_rank["rank_type"] == end_rank["rank_type"] and start_rank["rank_num"] is not None and end_rank["rank_num"] is not None:
                diff = start_rank["rank_num"] - end_rank["rank_num"]
                if diff > 0:
                    delta_str = f"🔺 {diff}단계 상승 ({s_str} -> {e_str})"
                elif diff < 0:
                    delta_str = f"🔻 {-diff}단계 하락 ({s_str} -> {e_str})"
                else:
                    delta_str = f"➖ 유지 ({s_str})"
            else:
                delta_str = f"영역변동 ({s_str} -> {e_str})"
        else:
            delta_str = "순위권 밖 (NOT_FOUND)"
            
        report.append({
            "prod": prod,
            "tot": tot,
            "cnt_18": cnt_18,
            "cnt_19": cnt_19,
            "first_r18": first_r18,
            "last_r18": last_r18,
            "first_r19": first_r19,
            "last_r19": last_r19,
            "delta": delta_str
        })

    report.sort(key=lambda x: x["tot"], reverse=True)

    print(f"=== 총 {len(report)}개 상품 추적 결과 ===")
    for r in report:
        if r["tot"] == 0 and "미발견" in r["first_r18"] and "미발견" in r["last_r19"]:
            continue
        p = r["prod"]
        c18 = r["cnt_18"]
        c19 = r["cnt_19"]
        tot = r["tot"]
        f18 = r["first_r18"]
        l19 = r["last_r19"]
        d = r["delta"]
        print(f"{p:<38} | 10/18: {c18:>2}타 | 10/19: {c19:>2}타 (총 {tot:>3}타) | 18초기: {f18:<10} -> 19최신: {l19:<10} | {d}")

if __name__ == "__main__":
    main()
