import json
import glob
import os
from collections import defaultdict, Counter
from datetime import datetime

def main():
    records = []
    for f in sorted(glob.glob("logs/execution_history_202610*.jsonl")):
        with open(f, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass

    print(f"Total records loaded: {len(records)}")

    # Group by product
    prod_records = defaultdict(list)
    for r in records:
        kw = r.get("keyword")
        store = r.get("store_name") or "미지정"
        prod = f"{kw} ({store})"
        prod_records[prod].append(r)

    # Filter for products with successes
    success_per_prod = {}
    for prod, r_list in prod_records.items():
        succ_list = [r for r in r_list if r.get("success")]
        if len(succ_list) > 0:
            success_per_prod[prod] = succ_list

    stats = {}
    for prod, succ_list in success_per_prod.items():
        ips = [r.get("ip") for r in succ_list if r.get("ip")]
        c_classes = [r.get("ip_c_class") for r in succ_list if r.get("ip_c_class")]
        nnbs = [r.get("nnb") for r in succ_list if r.get("nnb")]
        dwells = [r.get("dwell_duration_seconds", 0) for r in succ_list]
        durations = [r.get("duration_seconds", 0) for r in succ_list]
        devices = [r.get("device_id") for r in succ_list if r.get("device_id")]
        
        # Sort by timestamp
        succ_sorted = sorted(succ_list, key=lambda x: x.get("timestamp", ""))
        timestamps = []
        for r in succ_sorted:
            ts_str = r.get("timestamp")
            if ts_str:
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    timestamps.append(dt)
                except Exception:
                    pass
                    
        gaps_min = []
        for i in range(1, len(timestamps)):
            diff = (timestamps[i] - timestamps[i-1]).total_seconds() / 60.0
            gaps_min.append(diff)
            
        avg_gap = sum(gaps_min) / len(gaps_min) if gaps_min else 0
        min_gap = min(gaps_min) if gaps_min else 0
        max_gap = max(gaps_min) if gaps_min else 0
        
        avg_dwell = sum(dwells) / len(dwells) if dwells else 0
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        first_entry = succ_sorted[0]
        last_entry = succ_sorted[-1]
        
        f_shop = first_entry.get("shopping_rank")
        f_serp = first_entry.get("serp_rank")
        first_r = f"SERP {f_serp}" if f_serp is not None else (f"SHOP {f_shop}" if f_shop is not None else "N/A")
        
        l_shop = last_entry.get("shopping_rank")
        l_serp = last_entry.get("serp_rank")
        last_r = f"SERP {l_serp}" if l_serp is not None else (f"SHOP {l_shop}" if l_shop is not None else "N/A")
        
        st_str = timestamps[0].strftime("%d일 %H:%M") if timestamps else "-"
        et_str = timestamps[-1].strftime("%d일 %H:%M") if timestamps else "-"
        
        stats[prod] = {
            "count": len(succ_list),
            "unique_ips": len(set(ips)),
            "unique_c_classes": len(set(c_classes)),
            "unique_nnbs": len(set(nnbs)),
            "unique_devices": len(set(devices)),
            "avg_dwell": round(avg_dwell, 1),
            "avg_duration": round(avg_duration, 1),
            "avg_gap_min": round(avg_gap, 1),
            "min_gap_min": round(min_gap, 1),
            "max_gap_min": round(max_gap, 1),
            "first_rank": first_r,
            "last_rank": last_r,
            "start_time": st_str,
            "end_time": et_str,
            "ip_repeat_rate": round((1 - len(set(ips)) / len(ips)) * 100, 1) if ips else 0
        }

    print("\n=== PRODUCT TRAFFIC CHARACTERISTICS ===")
    print(f"{'상품/키워드':<32} | {'유효타':>4} | {'IP수(C클)':>10} | {'IP재사용률':>8} | {'NNB수':>5} | {'기기수':>4} | {'평균체류':>5} | {'평균간격':>6} | {'최소간격':>6} | {'순위변화':>18}")
    print("-" * 125)
    for prod, s in sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True):
        p_name = prod[:30]
        cnt = s["count"]
        ip_info = f"{s['unique_ips']}개({s['unique_c_classes']})"
        ip_rep = f"{s['ip_repeat_rate']}%"
        nnbs = f"{s['unique_nnbs']}개"
        devs = f"{s['unique_devices']}대"
        dwell = f"{s['avg_dwell']}s"
        gap = f"{s['avg_gap_min']}분"
        mgap = f"{s['min_gap_min']}분"
        r_change = f"{s['first_rank']} -> {s['last_rank']}"
        print(f"{p_name:<32} | {cnt:>5} | {ip_info:>10} | {ip_rep:>10} | {nnbs:>6} | {devs:>5} | {dwell:>7} | {gap:>8} | {mgap:>8} | {r_change:>18}")

if __name__ == "__main__":
    main()
