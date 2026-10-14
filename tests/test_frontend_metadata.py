import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class FrontendMetadataTests(unittest.TestCase):
    def test_every_html_page_has_one_omnexa_title_and_shared_favicon(self):
        pages = sorted(FRONTEND.glob("*.html"))
        self.assertGreaterEqual(len(pages), 40)
        for page in pages:
            source = page.read_text(encoding="utf-8")
            head_match = re.search(r"<head\b[^>]*>(.*?)(?:</head>|<body\b|\Z)", source, re.I | re.S)
            self.assertIsNotNone(head_match, page.name)
            head = head_match.group(1)
            titles = re.findall(r"<title\b[^>]*>(.*?)</title>", head, re.I | re.S)
            self.assertEqual(len(titles), 1, page.name)
            self.assertIn("Omnexa", titles[0], page.name)
            icons = re.findall(
                r'<link\b(?=[^>]*\brel="icon")(?=[^>]*\bhref="favicon\.svg")(?=[^>]*\btype="image/svg\+xml")[^>]*>',
                head,
                re.I,
            )
            self.assertEqual(len(icons), 1, page.name)

    def test_shared_favicon_is_valid_svg(self):
        favicon = FRONTEND / "favicon.svg"
        self.assertTrue(favicon.is_file())
        root = ET.parse(favicon).getroot()
        self.assertTrue(root.tag.endswith("svg"))


if __name__ == "__main__":
    unittest.main()
