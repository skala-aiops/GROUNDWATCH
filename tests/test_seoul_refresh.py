import unittest
from scripts.build_seoul_refresh import validated_rows

STATION={'station_id':'S1','district_code':'11110'}
def page(code='S1',rain='0',unit='수위 (gl.-m)'):
    return f'''var obsvCode = "{code}"; {unit} 강수량 (mm)
    categories1[0] = "2026-09-28"; seriesData1[0] = -2.5; seriesData4[0] = {rain};'''

class SeoulRefreshTests(unittest.TestCase):
    def test_wrong_station_or_unit_never_becomes_canonical(self):
        for text in [page(code='S2'),page(unit='수위 (m)')]:
            with self.assertRaises(ValueError):validated_rows(text,STATION,'2026-09-28','2026-09-30')

    def test_missing_rain_is_excluded_and_actual_zero_retained(self):
        rows,quality=validated_rows(page(),STATION,'2026-09-28','2026-09-30')
        self.assertEqual(rows[0]['rainfall_mm'],0.)
        self.assertEqual(rows[0]['groundwater_level'],-2.5)
        self.assertEqual(quality['missing_dates'],['2026-09-29','2026-09-30'])
        rows,quality=validated_rows(page(rain='null'),STATION,'2026-09-28','2026-09-30')
        self.assertEqual(rows,[])
        self.assertEqual(quality['invalid_rows'],1)

    def test_duplicate_date_is_quarantined_without_last_write_wins(self):
        text=page()+'''categories1[1] = "2026-09-28"; seriesData1[1] = -3; seriesData4[1] = 1;'''
        rows,quality=validated_rows(text,STATION,'2026-09-28','2026-09-30')
        self.assertEqual(rows,[])
        self.assertEqual(quality['duplicate_dates'],['2026-09-28'])
