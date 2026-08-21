"""Verify frontend/assets/js/qrcode-gen.js actually produces scannable QR codes.

The publish page renders a share-link QR that a shop owner prints and sticks on
a counter. A QR that is subtly wrong still *looks* like a QR, so eyeballing it
proves nothing and a screenshot test proves nothing either.

Two layers:

1. Dependency-free. Drive the real generator through Node, then reverse the
   whole pipeline in Python: undo the mask, walk the zigzag, de-interleave the
   blocks, recompute the Reed-Solomon remainder from the spec, and decode the
   byte-mode payload back to text. This fails if placement, masking, format
   bits, padding or ECC are wrong.
2. Optional. If zxing-cpp is installed, decode a rendered bitmap with a real
   third-party decoder.

Note on segno: it is deliberately not used as an oracle. segno emits one extra
0x00 byte before the 0xEC/0x11 pad sequence, so its matrices differ from a
literal reading of ISO/IEC 18004 clause 8.4.9. Both forms decode; byte-equality
with segno is not the property worth asserting.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QR_JS = ROOT / "frontend" / "assets" / "js" / "qrcode-gen.js"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to run the generator")


# The real shapes this page produces, plus the boundaries that break naive
# implementations: the version-10 jump to a 16-bit character count, versions
# carrying version-info bits (>= 7), multi-block ECC, and multibyte input.
CASES = [
    ("https://bot.example.com/chat/wgt_9f2ac1", "M"),
    ("https://t.me/olympicedu_bot", "M"),
    ("a", "M"),
    ("hello", "M"),
    ("https://bot.example.com/chat/" + "x" * 200, "M"),
    ("https://bot.example.com/chat/" + "y" * 700, "M"),
    ("Klinik Seri Damai " + "z" * 60, "L"),
    ("Klinik Seri Damai " + "z" * 60, "Q"),
    ("Klinik Seri Damai " + "z" * 60, "H"),
    ("Pusat Tuisyen Cahaya, Jalan Ampang", "H"),
    ("Klinik Pergigian Sri Muara \u2014 sesi kaunseling", "M"),
]

ECC_PER_BLOCK = {
    "L": [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "M": [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    "Q": [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "H": [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
}

NUM_BLOCKS = {
    "L": [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    "M": [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    "Q": [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    "H": [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
}

ECL_FORMAT_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}


# ---- Spec helpers, written from ISO/IEC 18004 rather than from the JS ----

def raw_data_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        num_align = ver // 7 + 2
        result -= (25 * num_align - 10) * num_align - 55
        if ver >= 7:
            result -= 36
    return result


def alignment_positions(ver):
    if ver == 1:
        return []
    num_align = ver // 7 + 2
    step = 26 if ver == 32 else -(-(ver * 4 + 4) // (num_align * 2 - 2)) * 2
    result = [6]
    pos = ver * 4 + 10
    while len(result) < num_align:
        result.insert(1, pos)
        pos -= step
    return result


def function_map(ver):
    """Every module the spec reserves, so whatever is left is the data region."""
    size = ver * 4 + 17
    fn = [[False] * size for _ in range(size)]

    def mark(x, y):
        if 0 <= x < size and 0 <= y < size:
            fn[y][x] = True

    for i in range(size):
        mark(6, i)
        mark(i, 6)

    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                mark(cx + dx, cy + dy)

    pos = alignment_positions(ver)
    for i in range(len(pos)):
        for j in range(len(pos)):
            corner = (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) \
                or (i == len(pos) - 1 and j == 0)
            if not corner:
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        mark(pos[i] + dx, pos[j] + dy)

    for i in range(6):
        mark(8, i)
    mark(8, 7)
    mark(8, 8)
    mark(7, 8)
    for i in range(9, 15):
        mark(14 - i, 8)
    for i in range(8):
        mark(size - 1 - i, 8)
    for i in range(8, 15):
        mark(8, size - 15 + i)
    mark(8, size - 8)

    if ver >= 7:
        for i in range(18):
            mark(size - 11 + i % 3, i // 3)
            mark(i // 3, size - 11 + i % 3)

    return fn


def mask_at(mask, x, y):
    return [
        (x + y) % 2 == 0,
        y % 2 == 0,
        x % 3 == 0,
        (x + y) % 3 == 0,
        (x // 3 + y // 2) % 2 == 0,
        (x * y % 2 + x * y % 3) == 0,
        (x * y % 2 + x * y % 3) % 2 == 0,
        ((x + y) % 2 + x * y % 3) % 2 == 0,
    ][mask]


def read_raw_codewords(rows, ver, mask):
    """Walk the zigzag backwards and undo the mask."""
    size = ver * 4 + 17
    fn = function_map(ver)
    bits = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not fn[y][x]:
                    value = 1 if rows[y][x] else 0
                    if mask_at(mask, x, y):
                        value ^= 1
                    bits.append(value)
        right -= 2

    out = []
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for k in range(8):
            byte = (byte << 1) | bits[i + k]
        out.append(byte)
    return out


def deinterleave(stream, ver, ecl):
    """Inverse of the block interleave: returns (data_blocks, ecc_blocks)."""
    num_blocks = NUM_BLOCKS[ecl][ver]
    block_ecc_len = ECC_PER_BLOCK[ecl][ver]
    raw_codewords = raw_data_modules(ver) // 8
    num_short = num_blocks - raw_codewords % num_blocks
    short_len = raw_codewords // num_blocks
    data_len = short_len - block_ecc_len

    data_blocks = [[] for _ in range(num_blocks)]
    ecc_blocks = [[] for _ in range(num_blocks)]

    pos = 0
    for i in range(short_len + 1):
        for j in range(num_blocks):
            if i == data_len and j < num_short:
                continue
            limit = data_len + (0 if j < num_short else 1)
            if i < limit:
                data_blocks[j].append(stream[pos])
            else:
                ecc_blocks[j].append(stream[pos])
            pos += 1
    return data_blocks, ecc_blocks


def rs_multiply(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = ((z << 1) ^ ((z >> 7) * 0x11D)) & 0x1FF
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def rs_divisor(degree):
    result = [0] * degree
    result[degree - 1] = 1
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = rs_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = rs_multiply(root, 0x02)
    return result


def rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i in range(len(result)):
            result[i] ^= rs_multiply(divisor[i], factor)
    return result


def decode_format_bits(rows):
    """Read the first format-info copy and undo its BCH mask."""
    bits = 0
    for i in range(6):
        bits |= (1 if rows[i][8] else 0) << i
    bits |= (1 if rows[7][8] else 0) << 6
    bits |= (1 if rows[8][8] else 0) << 7
    bits |= (1 if rows[8][7] else 0) << 8
    for i in range(9, 15):
        bits |= (1 if rows[8][14 - i] else 0) << i
    data = (bits ^ 0x5412) >> 10
    return data >> 3, data & 7


def decode_payload(data_blocks, ver):
    """Parse the byte-mode segment back to text."""
    payload = []
    for block in data_blocks:
        payload.extend(block)

    bits = []
    for byte in payload:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)

    state = {"pos": 0}

    def take(n):
        chunk = bits[state["pos"]:state["pos"] + n]
        state["pos"] += n
        value = 0
        for b in chunk:
            value = (value << 1) | b
        return value

    assert take(4) == 0x4, "not a byte-mode segment"
    length = take(8 if ver < 10 else 16)
    raw = bytes(bytearray(take(8) for _ in range(length)))
    return raw.decode("utf-8")


NODE_ENCODE = (
    "const qr = require(%s);"
    "const cases = JSON.parse(process.argv[1]);"
    "process.stdout.write(JSON.stringify(cases.map(function (c) {"
    "  const r = qr.encode(c[0], c[1]);"
    "  return { size: r.size, version: r.version, mask: r.mask,"
    "    rows: r.modules.map(function (row) {"
    "      return row.map(function (m) { return m ? 1 : 0; });"
    "    }) };"
    "})));"
)


def run_node(cases):
    script = NODE_ENCODE % json.dumps(str(QR_JS))
    result = subprocess.run(
        [NODE, "-e", script, json.dumps(cases)],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_js(body):
    """Run a snippet with the generator already required as `qr`."""
    script = ("const qr = require(%s);" % json.dumps(str(QR_JS))) + body
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def generated():
    return run_node(CASES)


def test_symbol_size_matches_its_version(generated):
    for (text, _), actual in zip(CASES, generated):
        assert actual["size"] == actual["version"] * 4 + 17, repr(text[:40])
        assert len(actual["rows"]) == actual["size"]
        assert all(len(row) == actual["size"] for row in actual["rows"])


def test_finder_and_timing_patterns_are_in_place(generated):
    for (text, _), actual in zip(CASES, generated):
        rows, size = actual["rows"], actual["size"]
        label = repr(text[:40])

        for ox, oy in ((0, 0), (size - 7, 0), (0, size - 7)):
            for dy in range(7):
                for dx in range(7):
                    dist = max(abs(dx - 3), abs(dy - 3))
                    expected = 1 if dist != 2 else 0
                    assert rows[oy + dy][ox + dx] == expected, \
                        "finder at (%d,%d) broken for %s" % (ox, oy, label)

        for i in range(8, size - 8):
            assert rows[6][i] == (1 if i % 2 == 0 else 0), "row timing broken for " + label
            assert rows[i][6] == (1 if i % 2 == 0 else 0), "column timing broken for " + label

        # The one module that is always dark, whatever the data or the mask.
        assert rows[size - 8][8] == 1, "dark module missing for " + label


def test_format_bits_report_the_real_ecc_level_and_mask(generated):
    for (text, ecl), actual in zip(CASES, generated):
        level_bits, mask = decode_format_bits(actual["rows"])
        assert level_bits == ECL_FORMAT_BITS[ecl], "wrong ECC level in %r" % text[:40]
        assert mask == actual["mask"], "format bits disagree with the applied mask"


def test_error_correction_bytes_recompute_from_the_spec(generated):
    for (text, ecl), actual in zip(CASES, generated):
        ver = actual["version"]
        stream = read_raw_codewords(actual["rows"], ver, actual["mask"])
        data_blocks, ecc_blocks = deinterleave(stream, ver, ecl)
        divisor = rs_divisor(ECC_PER_BLOCK[ecl][ver])

        for i, (data, ecc) in enumerate(zip(data_blocks, ecc_blocks)):
            assert rs_remainder(data, divisor) == ecc, \
                "block %d has bad error correction for %r" % (i, text[:40])


def test_matrix_decodes_back_to_the_original_text(generated):
    """End to end: placement, mask, padding and block order all have to be right."""
    for (text, ecl), actual in zip(CASES, generated):
        ver = actual["version"]
        stream = read_raw_codewords(actual["rows"], ver, actual["mask"])
        data_blocks, _ = deinterleave(stream, ver, ecl)
        assert decode_payload(data_blocks, ver) == text, \
            "round trip failed for %r" % text[:40]


def test_a_real_decoder_reads_every_case(generated):
    zxingcpp = pytest.importorskip("zxingcpp", reason="third-party decoder cross-check")
    image_mod = pytest.importorskip("PIL.Image", reason="third-party decoder cross-check")

    for (text, _), actual in zip(CASES, generated):
        rows, size, scale, quiet = actual["rows"], actual["size"], 6, 4
        dim = (size + quiet * 2) * scale
        img = image_mod.new("L", (dim, dim), 255)
        px = img.load()
        for y in range(size):
            for x in range(size):
                if rows[y][x]:
                    for dy in range(scale):
                        for dx in range(scale):
                            px[(x + quiet) * scale + dx, (y + quiet) * scale + dy] = 0

        result = zxingcpp.read_barcode(img)
        assert result is not None, "decoder found no code for %r" % text[:40]
        assert result.text == text, "decoder read %r for %r" % (result.text[:40], text[:40])


def test_svg_is_self_contained_and_labelled():
    svg = run_js(
        "process.stdout.write(qr.toSvg('https://bot.example.com/chat/wgt_9f2ac1',"
        " {label: 'QR code for your chat link'}));"
    )

    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")
    assert "role=" in svg and "img" in svg
    assert "QR code for your chat link" in svg
    # Vector, one path, nothing fetched from anywhere.
    assert svg.count("<path") == 1
    assert "http://www.w3.org/2000/svg" in svg
    assert "<image" not in svg
    assert "base64" not in svg


def test_svg_label_is_escaped():
    svg = run_js("process.stdout.write(qr.toSvg('hi', {label: 'a<b&c'}));")
    assert "a&lt;b&amp;c" in svg
    assert "a<b&c" not in svg


def test_svg_quiet_zone_is_four_modules():
    raw = run_js(
        "const r = qr.encode('hello', 'M');"
        "const svg = qr.toSvg('hello', {ecl: 'M'});"
        "const box = svg.split('viewBox=')[1].split(String.fromCharCode(34))[1];"
        "const parts = box.split(' ');"
        "process.stdout.write(JSON.stringify({size: r.size, w: +parts[2], h: +parts[3]}));"
    )
    data = json.loads(raw)

    # Four light modules on every side is the spec minimum for reliable scanning.
    assert data["w"] == data["size"] + 8
    assert data["h"] == data["size"] + 8


def test_oversized_input_fails_loudly():
    out = run_js(
        "try { qr.encode('x'.repeat(5000), 'H'); process.stdout.write('NO_ERROR'); }"
        "catch (e) { process.stdout.write(e.message); }"
    )
    assert "too long" in out.lower()
