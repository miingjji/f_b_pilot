"""품목의 최근 활동(입고·구매청구) 조회 (Streamlit 비의존). 마스터를 만들 때(휴면 판정)와 화면(활동 있는 품목만 보기)이 같은 기준을 쓴다."""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

CLEANED = Path(__file__).resolve().parent / "data" / "cleaned"
DORMANT_DAYS = 45                            # 이 기간 입고·구매청구가 없으면 요즘 쓰지 않는 품목 후보


def _ledger_dirs(ledger: Path | None, months: int) -> list[Path]:
    ledger = ledger or Path(__file__).resolve().parent / "data" / "cleaned" / "수불부"
    return sorted(p for p in ledger.glob("20??/20??-??") if (p / "입고내역_정제.csv").exists())[-months:]


def recent_activity_codes(ledger: Path | None = None, requests: Path | None = None, days: int = DORMANT_DAYS) -> set | None:
    """자료 끝(수불부 입고일 · 구매청구 청구일/입고일 중 가장 늦은 날)부터 days 일 안에 입고나 구매청구가 있었던 품목의 RMS 코드.
    수불부 일자별 입고(최근 두 달)와 구매청구 정제본(2026)을 함께 본다. 둘 다 없으면 None (판단하지 않는다)."""
    cleaned = Path(__file__).resolve().parent / "data" / "cleaned"
    events: dict = {}                                     # {코드: 마지막 입고·청구일}
    end = None

    def see(code, d):
        nonlocal end
        events[code] = max(events.get(code, d), d)
        end = max(end or d, d)

    for p in _ledger_dirs(ledger, 2):
        d = pd.read_csv(p / "입고내역_정제.csv", encoding="utf-8-sig", dtype={"품목코드_RMS": str})
        y, m = int(p.name[:4]), int(p.name[5:])
        for c in (c for c in d.columns if c.endswith("일_수량") and c[:-4].isdigit()):
            for code in d.loc[(d[c].fillna(0) > 0) & (d["품목코드_RMS"] != "없음"), "품목코드_RMS"]:
                see(code, date(y, m, int(c[:-4])))
    req = requests or cleaned / "2026" / "구매청구_정제.csv"
    if Path(req).exists():
        r = pd.read_csv(req, dtype={"품목코드_RMS": str}, usecols=["청구일자", "입고일자", "품목코드_RMS"])
        for col in ("청구일자", "입고일자"):
            for code, x in zip(r["품목코드_RMS"], pd.to_datetime(r[col], errors="coerce")):
                if pd.notna(x):
                    see(code, x.date())
    if end is None:
        return None
    cutoff = end - timedelta(days=days - 1)
    return {code for code, d in events.items() if d >= cutoff}


def stamp() -> float:
    """활동 계산에 쓰는 파일이 바뀌면 달라지는 값 (화면 캐시용)."""
    files = [CLEANED / "2026" / "구매청구_정제.csv", *(p / "입고내역_정제.csv" for p in _ledger_dirs(None, 2))]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0)
