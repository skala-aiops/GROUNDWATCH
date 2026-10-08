import unittest
from scripts.collect_asos_hub_history import parse

class AsosHubHistoryTest(unittest.TestCase):
    def raw(self, rain, station='203'):
        fields=['0']*56
        fields[0]='20200101';fields[1]=station;fields[38]=rain
        return ('#START7777\n# 39. RN_DAY : 일 강수량 (mm)\n'+' '.join(fields)+'\n#7777END').encode('cp949')

    def test_source_missing_is_excluded_but_explicit_zero_remains(self):
        good,bad=parse(self.raw('-9.0'),'203','2020-01-01','2020-01-01')
        self.assertEqual(good,[]);self.assertEqual(len(bad),1)
        good,bad=parse(self.raw('0.0'),'203','2020-01-01','2020-01-01')
        self.assertEqual(good[0]['rainfall_mm'],0);self.assertEqual(bad,[])

    def test_identity_and_truncated_payload_are_rejected(self):
        with self.assertRaises(ValueError):parse(self.raw('2','165'),'203','2020-01-01','2020-01-01')
        with self.assertRaises(ValueError):parse(self.raw('2').replace(b'#7777END',b''),'203','2020-01-01','2020-01-01')

if __name__=='__main__':unittest.main()
