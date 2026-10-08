import unittest

from kioskctl.platform import WaylandTools


SAMPLE = '''HDMI-A-1 "Example Display"
  Enabled: yes
  Modes:
    1920x1080 px, 60.000000 Hz (preferred, current)
    1280x720 px, 60.000000 Hz
  Position: 0,0
  Transform: normal
  Scale: 1.000000
DP-1 "Second Display"
  Enabled: no
  Modes:
    2560x1440 px, 59.950000 Hz (preferred)
  Transform: 90
  Scale: 1.250000
'''


class DisplayParserTests(unittest.TestCase):
    def test_parse_wlr_randr(self):
        outputs = WaylandTools.parse_outputs(SAMPLE)
        self.assertEqual(len(outputs), 2)
        hdmi = outputs[0]
        self.assertEqual(hdmi['name'], 'HDMI-A-1')
        self.assertTrue(hdmi['enabled'])
        self.assertEqual(hdmi['current_mode']['width'], 1920)
        self.assertTrue(hdmi['preferred_mode']['preferred'])
        self.assertEqual(hdmi['scale'], 1.0)
        self.assertEqual(outputs[1]['transform'], '90')


if __name__ == '__main__':
    unittest.main()
