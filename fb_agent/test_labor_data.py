import unittest

import labor_data as L
import sales_data


@unittest.skipUnless(L.available(), "정제 스케줄 CSV 없음")
class LaborDataTest(unittest.TestCase):
    def test_월_목록은_2024_01부터_정렬(self):
        ms = L.months()
        self.assertEqual(ms[0], "2024-01")
        self.assertEqual(ms, sorted(ms))

    def test_스케줄표는_직급_순서이고_부서_필터가_먹는다(self):
        g = L.schedule_grid("2025-09")
        self.assertEqual(g.iloc[0]["직급"], "GM")                       # 점장이 맨 위
        self.assertEqual(g["이름"].is_unique, True)                      # 한 사람 한 줄 (부서 중복 제거)
        self.assertTrue(set(L.schedule_grid("2025-09", "BK")["부서"]) <= {"BK"})

    def test_PT_인건비는_근무와_주휴에_시급을_곱한_값(self):
        p = L.hourly_pay("2026-09")
        row = p.iloc[0]
        self.assertEqual(row["인건비(원)"], round((row["근무시간(시간)"] + row["주휴(시간)"]) * row["시급(원)"]))
        self.assertTrue(set(p["시급(원)"]) <= {10400, 12000})

    def test_직원은_인건비_없이_시간만(self):
        s = L.staff_hours("2026-09")
        self.assertNotIn("인건비(원)", s.columns)
        self.assertNotIn("PT", set(s["직급"]))

    def test_월별_요약은_스케줄이_있는_달만이고_매출_없는_달은_비율이_비어_있다(self):
        sm = L.month_summary(sales_data.monthly(sales_data.last_date(), 48))
        self.assertEqual(sm["월"].tolist(), L.months())
        last = sm[sm["월"] == "2026-11"].iloc[0]
        self.assertTrue(last["변동 인건비율(%)"] != last["변동 인건비율(%)"])    # NaN
        ok = sm[sm["월"] == "2026-03"].iloc[0]
        self.assertAlmostEqual(ok["변동 인건비율(%)"], ok["합계(원)"] / ok["순매출(원)"] * 100, delta=0.05)

    def test_입퇴사_후보는_월로_거른다(self):
        r = L.roster("2026-03")
        self.assertTrue((r["월"] == "2026-03").all())
        self.assertIn("권민지", set(r["이름"]))


if __name__ == "__main__":
    unittest.main()
