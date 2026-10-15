import sys
from data import DEFAULT_CALENDAR, ITEMS, SAMPLE_COUNTS
from converter import parse_count, to_boxes, to_grams
from reorder import fmt_date, recommend
from errors import InvalidInputError


def show(name, g):
    item = ITEMS.get(name)
    if item is None:
        raise InvalidInputError(f"등록되지 않은 품목: {name}")
    box, pk, loose = to_boxes(item, g)
    r = recommend(item, g, cal=DEFAULT_CALENDAR)
    left = "-" if r.days_left is None else f"{r.days_left:.1f}일"
    print(f"[{name}] 재고 {item.fmt(g)} = {box}BOX {pk}PK {item.fmt(loose)} | 잔여 {left} | "
          f"{r.status} | 발주 {fmt_date(r.order_date)} -> 입고 {fmt_date(r.arrival_date)} "
          f"{r.order_packs}PK ({r.supplier}) | {r.message}")


def main():
    if len(sys.argv) >= 3:  # python main.py 짜사이 "1pk 300g"
        try:
            name = sys.argv[1]
            if name not in ITEMS:
                raise InvalidInputError(f"등록되지 않은 품목: {name}")
            show(name, parse_count(ITEMS[name], " ".join(sys.argv[2:])))
        except (InvalidInputError, ValueError) as e:
            print(f"입력 오류: {e}")
            sys.exit(1)
        return
    for name, (b, p, l) in SAMPLE_COUNTS.items():
        show(name, to_grams(ITEMS[name], p, l, boxes=b))
    print("\n-- 잘못된 입력 테스트 --")
    for name, text in [("짜사이", "-1pk"), ("짜사이", "3dozen"), ("짜사이", "abc"), ("김치", "1pk")]:
        try:
            show(name, parse_count(ITEMS[name], text)) if name in ITEMS else show(name, 0)
        except InvalidInputError as e:
            print(f"입력 오류 처리됨: {e}")


if __name__ == "__main__":
    main()
