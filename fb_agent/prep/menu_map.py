"""매출입력(매출영수증상세)의 메뉴명 -> 표준 bom 의 메뉴(상품명 통일) 변환.

영수증에는 세트 대표 행(유가), 세트 구성품 행(무가, 'A - 새우볶음밥'), 주문 옵션(ETC), 배달 채널 접두사('(배민)')가 섞여 있다.
BOM 에 쓰이는 건 실제 음식 행뿐이므로 이름을 규칙으로 BOM 메뉴에 붙이고, 규칙으로 못 붙이는 건 별칭 파일(수동)에서 찾는다.
BOM 의 메뉴 열은 달마다 달라서(메뉴 개편) 변환은 달별로, 그 달 BOM 에 있는 열로만 한다.

종류: 정확일치 · 공백무시 · 채널접두사 · 세트구성품 · 별칭 · 규격추정 · 세트대표 · 옵션 · 비식재 · 미매핑
"""
import re
from pathlib import Path

import pandas as pd

ALIAS_FILE = Path(__file__).resolve().parent.parent / "data" / "menu_bom_alias.csv"
ALIAS_COLUMNS = ["메뉴명", "BOM상품명", "시작월", "끝월", "메모"]
EXCLUDE = "[무가제외]"  # BOM상품명 칸에 쓰면 그 기간 그 이름의 단가 0 행은 판매로 세지 않는다 (유가 행은 그대로 센다)
CHANNEL = re.compile(r"^\((배달|배민|쿠팡|요기요|땡겨요|포장)\)\s*|^초복_")
COMPONENT = re.compile(r"^(?:#?세트\d*|[^\-]{1,12}?)\s*-\s*(.+)$")
NON_FOOD = ("맥주잔", "생수", "잔필요없음", "고량주잔", "전용잔", "스트레이트잔", "잔선택안함")
KINDS = ("정확일치", "공백무시", "채널접두사", "세트구성품", "별칭", "규격추정", "세트대표", "옵션", "무가행", "비식재", "미매핑")


def norm(s) -> str:
    return re.sub(r"\s+", "", str(s)).casefold()


def load_aliases(path=None) -> pd.DataFrame:
    path = Path(path or ALIAS_FILE)
    if not path.exists():
        return pd.DataFrame(columns=ALIAS_COLUMNS)
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")


def _alias_target(name: str, month: str, aliases: pd.DataFrame, bom: set):
    """별칭 파일에서 (메뉴명, 월)에 맞는 BOM 상품명. 그 달 BOM 에 없는 대상은 건너뛴다."""
    for _, a in aliases[aliases["메뉴명"].map(norm) == norm(name)].iterrows():
        if a["시작월"] and month < a["시작월"]:
            continue
        if a["끝월"] and month > a["끝월"]:
            continue
        if a["BOM상품명"] == EXCLUDE or a["BOM상품명"] in bom:
            return a["BOM상품명"]
    return None


def map_name(name: str, subclass: str, priced: bool, month: str, bom: set, aliases: pd.DataFrame):
    """(BOM 상품명 또는 None, 종류). 한 메뉴명 한 달 기준."""
    by_norm = {norm(b): b for b in bom}
    if subclass == "ETC" and not priced:
        return None, "옵션"          # 이름이 BOM 과 같아도 주문 옵션(변형 선택)이라 판매가 아니다
    target = _alias_target(name, month, aliases, bom)
    if target == EXCLUDE:
        if not priced:
            return None, "무가행"          # 사이즈 분리 뒤 남은 선택 표시. 유가 행(소·중, (4)·(8))이 따로 팔려 세면 겹친다
        target = None
    if target:
        return target, "별칭"
    if name in bom:
        return name, "정확일치"
    if norm(name) in by_norm:
        return by_norm[norm(name)], "공백무시"
    core, kind = name, None
    m = CHANNEL.match(name)
    if m:
        core, kind = name[m.end():].lstrip("- "), "채널접두사"
        for cand in (f"({m.group(1)}){core}" if m.group(1) else core, "(배달)" + core, core, _alias_target(core, month, aliases, bom) or core,
                     core.replace("(삶은)", "")):
            if cand in bom or norm(cand) in by_norm:
                return by_norm.get(norm(cand), cand), "채널접두사"
    c = COMPONENT.match(core)
    if c:
        part = c.group(1).strip()
        for cand in (part, _alias_target(part, month, aliases, bom)):
            if cand and (cand in bom or norm(cand) in by_norm):
                return by_norm.get(norm(cand), cand), "세트구성품"
        core = part
        kind = kind or "세트구성품"
    if core in bom or norm(core) in by_norm:
        return by_norm.get(norm(core), core), kind or "공백무시"
    target = _alias_target(core, month, aliases, bom) or _alias_target(name, month, aliases, bom)
    if target:
        return target, "별칭"
    cands = [b for b in bom if norm(b).startswith(norm(core) + "(")]
    if len(cands) == 1:
        return cands[0], "규격추정"
    if subclass == "ETC":
        return None, "옵션"
    if (subclass == "세트" and (priced or re.search(r"세트|SET", name, re.I))) or (priced and re.search(r"세트$", name)):
        return None, "세트대표"          # 구성품이 영수증에 따로 찍히므로 대표 행은 세지 않는다
    if norm(name) in {norm(x) for x in NON_FOOD}:
        return None, "비식재"
    return None, "미매핑"


# ---------------------------------------------------------------- 실행
SRC = Path(__file__).resolve().parent.parent / "data" / "source" / "수불부"
OUT = Path(__file__).resolve().parent.parent / "data" / "cleaned" / "매출"


def build(src=SRC, aliases=None):
    """모든 달의 변환표와 월별 검증을 만든다. 반환: (변환표, 월별검증, 상품별검증)"""
    from prep import bom_sheets, clean_sales
    from prep.md_tables import read_sheets
    aliases = load_aliases() if aliases is None else aliases
    tables, months, products = [], [], []
    for path in sorted(Path(src).glob("*/*.md")):
        month = path.stem
        sheets = read_sheets(path)
        usage = sheets[bom_sheets.SHEET_USAGE]
        bom_sales = bom_sheets.read_sales_row(usage).drop(labels=["ETC", "세트메뉴명칭"], errors="ignore")
        r = sheets[clean_sales.SHEET]
        r = r[r["메뉴명"].notna()].copy()                      # 메뉴명 없는 행 = 합계 행
        for c in ("수량", "단가"):
            r[c] = pd.to_numeric(r[c], errors="coerce")
        r["유가"] = r["단가"].abs() > 0                           # 한 달 안에도 유가·무가 행이 섞이므로 행 단위로 본다
        g = r.groupby(["메뉴코드", "메뉴명", "소분류명", "유가"], dropna=False).agg(수량=("수량", "sum")).reset_index()
        bom = set(bom_sales.index)
        res = [map_name(x["메뉴명"], x["소분류명"], x["유가"], month, bom, aliases) for _, x in g.iterrows()]
        g["BOM상품명"], g["종류"] = [o[0] for o in res], [o[1] for o in res]
        g.insert(0, "월", month)
        tables.append(g)
        q = g[g["BOM상품명"].notna()].groupby("BOM상품명")["수량"].sum()
        x = pd.concat([q.rename("시트_수량"), bom_sales.rename("워크북_판매량")], axis=1).fillna(0)
        x.insert(0, "월", month)
        products.append(x.rename_axis("BOM상품명").reset_index())
        diff = (x["시트_수량"] - x["워크북_판매량"]).abs().sum()
        months.append({"월": month, "시트_수량(매핑)": x["시트_수량"].sum(), "워크북_판매량": x["워크북_판매량"].sum(),
                       "절대차": diff, "절대차_비율": diff / x["워크북_판매량"].sum()})
    return pd.concat(tables), pd.DataFrame(months), pd.concat(products)


def main(argv=None) -> int:
    table, months, products = build()
    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "메뉴_BOM_변환표.csv", index=False, encoding="utf-8-sig")
    months.round(4).to_csv(OUT / "메뉴_BOM_변환_검증_월별.csv", index=False, encoding="utf-8-sig")
    products["차이"] = products["시트_수량"] - products["워크북_판매량"]
    products.to_csv(OUT / "메뉴_BOM_변환_검증_상품별.csv", index=False, encoding="utf-8-sig")
    un = table[table["종류"] == "미매핑"].groupby("메뉴명").agg(수량=("수량", "sum"), 첫달=("월", "min"), 끝달=("월", "max")).sort_values("수량", ascending=False)
    un.to_csv(OUT / "메뉴_BOM_미매핑.csv", encoding="utf-8-sig")
    print(table.groupby("종류")["수량"].sum().to_string())
    print(f"미매핑 {len(un)}개 이름, 수량 {int(un['수량'].sum())} -> {OUT / '메뉴_BOM_미매핑.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
