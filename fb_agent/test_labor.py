import unittest
from datetime import date

import pandas as pd

import labor

TABLE = {"A20.5": 9.5, "A20.5+": 10.5, "AS20.5+": 10.0, "훈련": 8.0}
WEEKDAY, SUNDAY = date(2025, 9, 9), date(2025, 9, 7)   # 화, 일


class ClassifyTest(unittest.TestCase):
    def test_휴무와_휴가는_시간이_없다(self):
        for raw, kind in [("/", "휴무"), ("대휴", "대휴"), ("연차", "연차"), ("반차", "반차")]:
            self.assertEqual(labor.classify(raw, WEEKDAY, TABLE)["종류"], kind)
            self.assertEqual(labor.classify(raw, WEEKDAY, TABLE)["근무시간"], 0.0)

    def test_표에_있으면_표_값(self):
        self.assertEqual(labor.classify("a20.5", WEEKDAY, TABLE)["근무시간"], 9.5)   # 소문자도 읽는다

    def test_평일_플러스는_떼서_휴게_2시간(self):
        r = labor.classify("A20.5+", WEEKDAY, TABLE)
        self.assertEqual((r["근무시간"], r["비고"]), (9.5, "평일+보정"))

    def test_일요일_플러스는_표_그대로(self):
        self.assertEqual(labor.classify("AS20.5+", SUNDAY, TABLE)["근무시간"], 10.0)

    def test_표에_없으면_계산(self):
        r = labor.classify("B20.5", WEEKDAY, {})   # 10시~20:30 = 10.5h, 휴게 2h
        self.assertEqual(r["근무시간"], 8.5)
        self.assertIn("표없음계산", r["비고"])

    def test_못_읽는_값은_미해석(self):
        self.assertEqual(labor.classify("??", WEEKDAY, TABLE)["종류"], "미해석")

    def test_본사_지원_표기는_읽지_않는다(self):
        for raw in ("PM님C20", "실장님지원"):
            r = labor.classify(raw, WEEKDAY, TABLE)
            self.assertEqual((r["종류"], r["근무시간"]), ("본사지원", 0.0))


def _rows(name, role, dept, days):
    return [{"월": d.strftime("%Y-%m"), "부서": dept, "이름": name, "직급": role, "날짜": d, "원문": "A20.5", "종류": "근무", "근무시간": h, "비고": ""} for d, h in days]


class IgnoredCellTest(unittest.TestCase):
    def test_지정한_오타만_무시하고_다른_사람의_오타는_미해석(self):
        self.assertEqual(labor._cell("최동진", "??", WEEKDAY, TABLE)["종류"], "무시")
        self.assertEqual(labor._cell("지현구", ".", WEEKDAY, TABLE)["종류"], "무시")
        self.assertEqual(labor._cell("다른사람", "??", WEEKDAY, TABLE)["종류"], "미해석")
        self.assertEqual(labor._cell("최동진", "", WEEKDAY, TABLE)["종류"], "빈칸")


class AggregateTest(unittest.TestCase):
    def test_중국인은_직급_없는_직원_리더는_별도_시급(self):
        df = labor.tidy(pd.DataFrame(_rows("가", "중국인", "BK", [(WEEKDAY, 9.5)]) + _rows("나", "PT리더", "FOH", [(WEEKDAY, 9.5)]) + _rows("다", "PT", "FOH", [(WEEKDAY, 5.0)])))
        got = df.set_index("이름")[["직급", "구분"]].to_dict("index")
        self.assertEqual(got["가"], {"직급": "", "구분": "직원"})
        self.assertEqual(got["나"]["구분"], "PT리더")
        self.assertEqual(labor.WAGE, {"PT": 10400, "PT리더": 12000})

    def test_점장급_중복은_BK_FK_지원_값을_쓴다(self):
        d1, d2 = date(2025, 9, 1), date(2025, 9, 2)
        bk = _rows("점장", "GM", "BK", [(d1, 9.0)])
        bk[0]["원문"] = "AS20.5"                                  # FOH(A20.5)와 코드가 다른 날
        df = labor.dedupe(labor.tidy(pd.DataFrame(_rows("점장", "GM", "FOH", [(d1, 9.5), (d2, 9.5)]) + bk)))
        pm = labor.person_month(df)
        self.assertEqual(pm["근무시간"].iloc[0], 18.5)          # d1은 BK(지원) 9.0, d2는 FOH 9.5
        self.assertEqual(int(df["집계"].sum()), 2)
        self.assertEqual(df[df["중복코드상이"]]["날짜"].nunique(), 1)   # d1만 코드 상이로 표시
        self.assertEqual(set(df[df["집계"] & (df["날짜"] == d1)]["부서"]), {"BK"})

    def test_점장급이_FOH_근무_BK_휴무면_근무가_이긴다(self):
        d1 = date(2025, 9, 1)
        off = {"월": "2025-09", "부서": "BK", "이름": "점장", "직급": "GM", "날짜": d1, "원문": "/", "종류": "휴무", "근무시간": 0.0, "비고": ""}
        df = labor.dedupe(labor.tidy(pd.DataFrame(_rows("점장", "GM", "FOH", [(d1, 9.5)]) + [off])))
        self.assertEqual(labor.person_month(df)["근무시간"].iloc[0], 9.5)

    def test_일반_직원_중복은_주부서만_센다(self):
        d1, d2, d3 = date(2025, 9, 1), date(2025, 9, 2), date(2025, 9, 3)
        df = labor.dedupe(labor.tidy(pd.DataFrame(_rows("가", "사원", "BK", [(d1, 9.5), (d2, 9.5)]) + _rows("가", "사원", "FK", [(d2, 9.0), (d3, 8.0)]))))
        # BK 2일 > FK 2일이 아니라 동률 → FOH→BK→FK 순이라 BK가 주 부서. 겹친 d2는 BK 값
        self.assertEqual(df[df["집계"] & (df["날짜"] == d2)]["부서"].tolist(), ["BK"])
        self.assertEqual(labor.person_month(df)["근무시간"].iloc[0], 9.5 + 9.5 + 8.0)

    def test_직급_확정_보정은_비어_있던_줄에만(self):
        d = date(2026, 4, 1)
        rows = _rows("이아인", "(SM)", "FOH", [(d, 9.5)]) + _rows("이아인", "SM", "FOH", [(date(2026, 5, 1), 9.5)])
        t = labor.tidy(pd.DataFrame(rows)).set_index("날짜")
        self.assertEqual(t.loc[d, "직급"], "사원")                # 이어받은 SM → 사원
        self.assertEqual(t.loc[date(2026, 5, 1), "직급"], "SM")  # 적혀 있던 건 그대로

    def test_주휴_15시간_미만은_없고_이상은_비례_최대_8시간(self):
        mon = date(2025, 9, 1)
        def week(hours_per_day, n):
            return pd.DataFrame(_rows("가", "PT", "FOH", [(date(2025, 9, 1 + i), hours_per_day) for i in range(n)]))
        low = labor.dedupe(labor.tidy(week(5.0, 2)))       # 10h
        mid = labor.dedupe(labor.tidy(week(5.0, 4)))       # 20h → 4h
        full = labor.dedupe(labor.tidy(week(10.0, 5)))     # 50h → 상한 8h
        self.assertEqual(labor.weekly_paid_holiday(low)["주휴시간"].iloc[0], 0.0)
        self.assertEqual(labor.weekly_paid_holiday(mid)["주휴시간"].iloc[0], 4.0)
        self.assertEqual(labor.weekly_paid_holiday(full)["주휴시간"].iloc[0], 8.0)
        self.assertEqual(labor.hourly_cost(mid)["인건비"].iloc[0], round((20 + 4) * 10400))


class RoleHistoryTest(unittest.TestCase):
    def _tidy(self, name, months, role="PT"):
        return labor.tidy(pd.DataFrame([{"월": m, "부서": "FK", "이름": name, "직급": role, "날짜": date.fromisoformat(m + "-01"), "원문": "/", "종류": "휴무", "근무시간": 0.0, "비고": ""} for m in months])).set_index("월")["직급"]

    def test_박주형은_2024년까지_사원_2025년부터_PT(self):
        r = self._tidy("박주형", ["2024-02", "2024-12", "2025-01"])
        self.assertEqual(r.tolist(), ["사원", "사원", "PT"])

    def test_양영모는_2025_6월까지_AM_이후_KM(self):
        r = self._tidy("양영모", ["2024-01", "2025-06", "2025-07", "2026-11"], role="TR")
        self.assertEqual(r.tolist(), ["AM", "AM", "KM", "KM"])

    def test_이수빈은_AM(self):
        self.assertEqual(self._tidy("이수빈", ["2024-03"]).tolist(), ["AM"])

    def test_직급_순위는_점장_SM_KM_AM_TR_PT리더_사원_PT(self):
        order = ["GM", "SM", "AM", "TR", "PT리더", "사원", "PT"]
        ranks = [labor.RANK[r] for r in order]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(labor.RANK["SM"], labor.RANK["KM"])
        self.assertGreater(labor.RANK[""], labor.RANK["PT"])      # 직급 없는 직원

    def test_예비군_한글자는_예비군_0시간(self):
        for ch in "예비군":
            r = labor.classify(ch, WEEKDAY, TABLE)
            self.assertEqual((r["종류"], r["근무시간"]), ("예비군", 0.0))


if __name__ == "__main__":
    unittest.main()
