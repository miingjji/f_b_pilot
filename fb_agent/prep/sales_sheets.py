"""'판매및할인' 시트 정제: 상품별 판매 요약표.

- 왼쪽 표(순번·상품코드·상품명·판매수량·판매금액·Dead·테스트·직원중식)가 본체이고, 오른쪽 15~18열은 같은 상품의 조회표다.
  조회표가 왼쪽과 똑같으면 지우고 BOM유무만 남긴다.
- 상품코드가 중복된 행은 삭제하지 않고 `중복행`으로 표시한다 (정제와 별개로 데이터를 지우는 결정이기 때문).
- 시트 아래의 '합계' 행과 대조해 정제가 값을 바꾸지 않았음을 확인한다.
"""
import pandas as pd

from prep.blocks import (REPORT_COLUMNS, ensure_no_missing, fill, find_row, label, make_check, notes_above, take_block,
                         to_numbers)

SHEET_SALES_SUMMARY = "판매및할인"
LOOKUP_FROM_COL = 14                  # 이 열부터는 오른쪽 조회표
CODE_COL = 2
EXCLUDED_FIRST_ROWS = 2               # 시트의 합계행은 앞의 주문 메모 항목 2행(순번 1~2)을 빼고 더한다
INT_COLS = ["순번", "판매수량", "판매금액", "Dead", "테스트", "직원중식"]
LOOKUP_PAIRS = [("조회_품목코드", "상품코드"), ("조회_품명", "상품명"), ("조회_상품명통일", "상품명통일")]
TOTAL_COLS = [("판매수량", 5), ("판매금액", 6), ("Dead", 7), ("테스트", 8), ("직원중식", 9)]


def clean_sales_summary(raw: pd.DataFrame):
    """'판매및할인' 시트 -> (정제표, 처리내역, info). info 에는 dropped·checks·notes·duplicates·reconcile_rows 등."""
    h = find_row(raw, 1, "순번")
    if h is None:
        raise ValueError("머리글 행('순번')을 찾지 못했습니다.")
    names = [(("조회_" if j >= LOOKUP_FROM_COL else "") + label(raw.iat[h, j])) if pd.notna(raw.iat[h, j]) else None
             for j in range(raw.shape[1])]
    start = h + 1
    end = start
    while end < len(raw) and pd.notna(raw.iat[end, CODE_COL]):
        end += 1
    df, dropped = take_block(raw, names, start, end, last_col=raw.shape[1] - 1)

    for lookup, left in LOOKUP_PAIRS:                       # 왼쪽 표와 똑같은 조회 열은 중복이라 삭제
        if lookup in df and left in df and df[lookup].equals(df[left]):
            df = df.drop(columns=lookup)
            dropped.append(f"{lookup} (왼쪽 '{left}'와 같음)")

    report: list[dict] = []
    for col in df.columns:
        if col == "조회_BOM유무":
            fill(df, col, "미기재", df[col].isna(), "BOM 정보가 적혀 있지 않음", report)
    to_numbers(df, INT_COLS)
    ensure_no_missing(df)
    for col in INT_COLS:
        df[col] = df[col].round().astype("int64")
    df["상품코드"] = df["상품코드"].astype(str)

    df["중복행"] = df.duplicated("상품코드", keep="first")
    dup = df[df["중복행"]]
    duplicates = {"rows": int(len(dup)), "amount": int(dup["판매금액"].sum()), "quantity": int(dup["판매수량"].sum())}

    checks, notes, reconcile = [], notes_above(raw, h), {}
    total = find_row(raw, 3, "합계", start=end)
    if total is not None:
        body = df.iloc[EXCLUDED_FIRST_ROWS:]
        for col, j in TOTAL_COLS:
            expected = pd.to_numeric(raw.iat[total, j])
            if col == "판매금액":
                checks.append(make_check("판매금액 합계", expected, df[col].sum()))
            else:
                checks.append(make_check(f"{col} 합계 (순번 1~2 제외: 합계행의 계산 범위)", expected, body[col].sum()))
        for i in range(total + 1, len(raw)):                  # 합계 아래 대조 블록: '매출입력', '표준사용량' 등
            lab = raw.iat[i, 4]
            if pd.notna(lab) and pd.notna(raw.iat[i, 5]) and pd.notna(raw.iat[i, 6]):
                reconcile[str(lab)] = {"수량": float(raw.iat[i, 5]), "금액": float(raw.iat[i, 6])}
    info = {"dropped": dropped, "checks": checks, "notes": notes, "duplicates": duplicates, "reconcile_rows": reconcile,
            "amount_total": int(df["판매금액"].sum()),
            "amount_without_duplicates": int(df.loc[~df["중복행"], "판매금액"].sum())}
    return df, pd.DataFrame(report, columns=REPORT_COLUMNS), info
