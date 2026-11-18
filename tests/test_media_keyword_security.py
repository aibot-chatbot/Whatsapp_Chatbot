"""Run the real card renderer and verify stored keywords remain literal text."""

from html.parser import HTMLParser
import json
import re
import shutil
import subprocess

import pytest

from tests.frontend_pages import WEB_PUBLIC_JS, page_source_path


def test_media_keywords_cannot_create_html_elements():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute the frontend renderer")
    source = page_source_path("media_attachments.html").read_text(encoding="utf-8")
    source += "\n" + (WEB_PUBLIC_JS / "media_attachments.js").read_text(encoding="utf-8")
    render = source[source.index("        function renderAttachments()"):source.index("        function openModal(")]
    escape = source[source.index("        function escapeHtml("):source.index("        // Drag and Drop Logic")]
    keywords = [
        "menu & pricing", '<brochure> "today"',
        '<img src=x onerror="window.keywordExecution=1">',
        '<svg onload="window.keywordExecution=1"></svg>',
    ]
    script = """
const cards = [];
const grid = {innerHTML: '', appendChild(card) { cards.push(card.innerHTML); }};
const document = {getElementById() { return grid; }, createElement() { return {}; }};
const lucide = {createIcons() {}};
const attachments = [{id: 1, label: 'Brochure', media_url: 'https://example.test/file.pdf', keywords: KEYWORDS}];
""".replace("KEYWORDS", json.dumps(keywords)) + escape + render + "\nrenderAttachments(); console.log(JSON.stringify(cards));"
    result = subprocess.run([node, "-"], input=script, text=True, capture_output=True, timeout=10, check=True)
    cards = json.loads(result.stdout)
    assert len(cards) == 1
    tags = re.findall(r'<span class="keyword-tag">(.*?)</span>', cards[0], re.S)
    assert len(tags) == len(keywords)
    for rendered, keyword in zip(tags, keywords):
        elements, text = [], []
        parser = HTMLParser(convert_charrefs=True)
        parser.handle_starttag = lambda tag, attrs: elements.append(tag)
        parser.handle_data = text.append
        parser.feed(rendered)
        parser.close()
        assert elements == [], f"Keyword created HTML elements: {elements}"
        assert "".join(text) == keyword
