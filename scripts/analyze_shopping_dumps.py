#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[분석 스크립트] exposed_dumps 및 unexposed_dumps 내 쇼핑 카드 일괄 분석 및 분류기
(scripts/analyze_shopping_dumps.py)
========================================================================================
사용법:
    python3 scripts/analyze_shopping_dumps.py
    python3 scripts/analyze_shopping_dumps.py --dir logs/exposed_dumps --limit 10
    python3 scripts/analyze_shopping_dumps.py --file logs/exposed_dumps/exposed_...xml
========================================================================================
"""

import os
import sys
import glob
import argparse

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.macro.shopping_xml_parser import ShoppingXMLParser


def main():
    parser = argparse.ArgumentParser(description="Analyze Naver Shopping UI XML Dumps")
    parser.add_argument("--dir", "-d", type=str, default="logs/exposed_dumps", help="Target directory containing XML dumps")
    parser.add_argument("--file", "-f", type=str, default="", help="Specific XML file path to analyze")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Maximum files to analyze (0 = all)")
    args = parser.parse_args()

    if args.file:
        files = [args.file]
    else:
        files = sorted(glob.glob(os.path.join(args.dir, "*.xml")), key=os.path.getmtime, reverse=True)
        if args.limit > 0:
            files = files[:args.limit]

    if not files:
        print(f"[!] 분석할 XML 파일이 없습니다: {args.dir}")
        return

    print(f"\n========================================================================================")
    print(f" 📊 [네이버 쇼핑/가격비교 XML 덤프 일괄 분석 리포트] (총 {len(files)}개 파일)")
    print(f"========================================================================================\n")

    for f_idx, xml_path in enumerate(files, 1):
        try:
            res = ShoppingXMLParser.parse_xml_string_or_file(xml_path)
            print(f"[{f_idx}/{len(files)}] 📄 파일: {res['source']}")
            print(f"     ↳ 섹션 유형: {res['section_type']} ('{res['section_title']}')")
            print(f"     ↳ 통계 요약: 총 상품 {res['total_items_count']}개 | [가로 1P 가시: {res['slide_1_items_count']}개 / 가로 2P+ 숨김: {res['slide_2_plus_items_count']}개] | [광고: {res['ad_items_count']}개 / 오가닉: {res['organic_items_count']}개]")
            print(f"     " + "-" * 80)

            for item in res["items"]:
                ad_badge = "🔴 [광고  ]" if item["is_ad"] else "🟢 [오가닉]"
                slide_badge = "✨ [Slide 1 가시]" if item["is_slide_1"] else f"⚪ [Slide #{item['slide_page']} 숨김]"
                mid_str = f"MID: {item['mid']}" if item['mid'] else "MID: N/A"
                print(f"     #{item['item_index']:02d} {ad_badge} {slide_badge} [{item['price']:>11}] {mid_str:>17} | {item['bounds']:<23} | {item['title'][:36]}")
            print("\n")
        except Exception as e:
            print(f"[!] 파일 분석 중 예외 발생 ({xml_path}): {e}\n")


if __name__ == "__main__":
    main()
