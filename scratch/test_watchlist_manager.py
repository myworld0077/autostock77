import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.watchlist_manager import get_dynamic_watchlist
from core.universe import get_kis_kospi200_top150

def run_tests():
    print("=== watchlist_manager 테스트 시작 ===")
    
    # 1. 150 유니버스 로드
    universe = get_kis_kospi200_top150()
    print(f"KOSPI 150 유니버스 개수: {len(universe)}개")
    
    # 2. 보유 종목이 없는 경우 (10개 정상 선정 확인)
    held = set()
    max_slots = 10
    print(f"\n테스트 1: 보유 종목 없음, 슬롯 {max_slots}개")
    watchlist = get_dynamic_watchlist(universe, held, max_slots)
    assert len(watchlist) == max_slots, f"선정된 개수 오류: {len(watchlist)}"
    print(f"결과: 성공, {len(watchlist)}개 선정됨.")
    
    # 3. 일부 종목 보유 중인 경우 (보유 종목 제외하고 선정되는지 확인)
    held = {watchlist[0], watchlist[1], watchlist[2], "005930"} # 일부 선정되었던 종목 + 삼성전자 보유
    max_slots = 7 # 10 - 3 (실제 보유된 KOSPI 종목 수 등)
    print(f"\n테스트 2: {len(held)}개 종목 보유 중, 슬롯 {max_slots}개")
    watchlist2 = get_dynamic_watchlist(universe, held, max_slots)
    assert len(watchlist2) == max_slots, f"선정된 개수 오류: {len(watchlist2)}"
    for code in watchlist2:
        assert code not in held, f"보유 중인 종목 {code}가 감시 리스트에 포함됨!"
    print(f"결과: 성공, {len(watchlist2)}개 선정됨 (보유종목 제외 완료).")
    
    # 4. 남은 슬롯이 없는 경우
    held_all = set(universe[:10])
    max_slots = 0
    print(f"\n테스트 3: 남은 슬롯 {max_slots}개")
    watchlist3 = get_dynamic_watchlist(universe, held_all, max_slots)
    assert len(watchlist3) == 0, f"선정된 개수 오류: {len(watchlist3)}"
    print("결과: 성공, 0개 선정됨.")
    
    print("\n=== 모든 테스트 통과! ===")

if __name__ == "__main__":
    run_tests()
