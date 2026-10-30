"""'표준 bom'(메뉴 1개당 식재료 g)과 '표준사용량(g)'(= 그 달 판매량 × bom) 시트를 읽는다.

두 시트는 같은 모양이다: 가로 = 메뉴(상품명 통일), 세로 = 식재료(품목코드_RMS), 칸 = g.
'표준사용량(g)'에는 '판매량' 행과 가로 합계 열이 더 있다. 원본은 고치지 않고 읽기만 한다.
"""
import pandas as pd

from prep.blocks import find_row, label

SHEET_BOM = "표준 bom"
SHEET_USAGE = "표준사용량(g)"
CODE_COL, FIRST_PRODUCT_COL = 3, 9
META_COLS = {1: "계정명", 3: "품목코드_RMS", 5: "거래처명"}


def _header(raw: pd.DataFrame) -> int:
    hdr = find_row(raw, CODE_COL, "품목코드(RMS)")
    if hdr is None:
        raise ValueError("머리글 행('품목코드(RMS)')을 찾지 못했습니다.")
    return hdr


def _product_row(raw: pd.DataFrame, hdr: int) -> int:
    row = find_row(raw, FIRST_PRODUCT_COL - 1, "상품명 통일")
    if row is None or row >= hdr:
        raise ValueError("'상품명 통일' 행을 찾지 못했습니다.")
    return row


def read_matrix(raw: pd.DataFrame) -> pd.DataFrame:
    """시트 -> 행 = 품목코드, 열 = 메뉴(상품명 통일), 값 = g. 같은 코드가 여러 번 나오면 더한다. 메뉴 이름이 겹치면 더한다."""
    hdr = _header(raw)
    prow = _product_row(raw, hdr)
    cols = [j for j in range(FIRST_PRODUCT_COL, raw.shape[1]) if pd.notna(raw.iat[prow, j])]
    names = [str(raw.iat[prow, j]).strip() for j in cols]
    body = raw.iloc[hdr + 1:]
    codes = body.iloc[:, CODE_COL]
    keep = codes.notna() & (codes.astype(str).map(label) != "없음")
    values = body.loc[keep].iloc[:, cols].apply(pd.to_numeric, errors="coerce")
    if values.isna().all(axis=None):
        raise ValueError("메뉴 칸이 모두 숫자가 아닙니다.")
    values.columns = names
    values.index = codes[keep].astype(str).values
    values = values.fillna(0.0)
    return values.T.groupby(level=0, sort=False).sum().T.groupby(level=0, sort=False).sum()


def read_items(raw: pd.DataFrame) -> pd.DataFrame:
    """품목 정보 [품목코드_RMS, 계정명, 거래처명, 품명, 규격]. 품명·규격 열 순서가 시트마다 달라 둘 다 담는다."""
    hdr = _header(raw)
    body = raw.iloc[hdr + 1:]
    codes = body.iloc[:, CODE_COL]
    keep = codes.notna() & (codes.astype(str).map(label) != "없음")
    b = body.loc[keep]
    out = pd.DataFrame({
        "품목코드_RMS": b.iloc[:, CODE_COL].astype(str).values,
        "계정명": b.iloc[:, 1].values,
        "거래처명": b.iloc[:, 5].values,
        "열6": b.iloc[:, 6].values,
        "열7": b.iloc[:, 7].values,
    })
    return out.drop_duplicates("품목코드_RMS").reset_index(drop=True)


def read_sales_row(raw: pd.DataFrame) -> pd.Series:
    """'표준사용량(g)' 시트의 '판매량' 행 -> 메뉴별 판매량. 같은 이름은 더한다."""
    hdr = _header(raw)
    prow = _product_row(raw, hdr)
    srow = find_row(raw, FIRST_PRODUCT_COL - 1, "판매량")
    if srow is None or srow >= hdr:
        raise ValueError("'판매량' 행을 찾지 못했습니다.")
    cols = [j for j in range(FIRST_PRODUCT_COL, raw.shape[1]) if pd.notna(raw.iat[prow, j])]
    s = pd.Series([pd.to_numeric(raw.iat[srow, j], errors="coerce") for j in cols],
                  index=[str(raw.iat[prow, j]).strip() for j in cols]).fillna(0.0)
    return s.groupby(level=0, sort=False).sum()


# ---------------------------------------------------------------- 실행
def long_form(bom: pd.DataFrame) -> pd.DataFrame:
    """행렬 -> 0 이 아닌 칸만 [품목코드_RMS, 메뉴, 사용량_g]."""
    s = bom.stack()
    s = s[s > 0]
    out = s.rename("사용량_g").reset_index()
    out.columns = ["품목코드_RMS", "메뉴", "사용량_g"]
    return out


def main(argv=None) -> int:
    """모든 달의 '표준 bom' 을 data/cleaned/수불부/<연도>/<월>/표준BOM_정제.csv 로 저장한다 (0 이 아닌 칸만)."""
    from pathlib import Path
    from prep.md_tables import read_sheets
    root = Path(__file__).resolve().parent.parent / "data"
    for path in sorted((root / "source" / "수불부").glob("*/*.md")):
        bom = read_matrix(read_sheets(path)[SHEET_BOM])
        out = root / "cleaned" / "수불부" / path.parent.name / path.stem / "표준BOM_정제.csv"
        long_form(bom).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"{path.stem}: 메뉴 {bom.shape[1]}개 × 품목 {bom.shape[0]}개 -> {len(long_form(bom))}칸")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
