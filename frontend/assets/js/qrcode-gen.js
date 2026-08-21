/**
 * qrcode-gen.js - QR Code generator. Byte mode, versions 1-40, ECC L/M/Q/H.
 *
 * Vendored so the publish page can draw a share-link QR with no build step and
 * no runtime dependency. Output is vector, so "Save the QR code" hands the
 * owner the same image at print resolution.
 *
 * Algorithm per ISO/IEC 18004. Verified module-for-module against segno in
 * tests/test_qrcode_gen.py.
 *
 * Exposes window.QRCodeGen = { encode, toSvg }.
 */
(function (global) {
    "use strict";

    /* ---- Spec tables. Rows are L, M, Q, H; column 0 is unused. ---- */

    var ECL = { L: 0, M: 1, Q: 2, H: 3 };
    var ECL_FORMAT_BITS = [1, 0, 3, 2];

    var ECC_PER_BLOCK = [
        [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
        [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
        [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
        [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30]
    ];

    var NUM_BLOCKS = [
        [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
        [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
        [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
        [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81]
    ];

    var PENALTY_N1 = 3, PENALTY_N2 = 3, PENALTY_N3 = 40, PENALTY_N4 = 10;

    /* ---- Capacity ---- */

    function rawDataModules(ver) {
        var result = (16 * ver + 128) * ver + 64;
        if (ver >= 2) {
            var numAlign = Math.floor(ver / 7) + 2;
            result -= (25 * numAlign - 10) * numAlign - 55;
            if (ver >= 7) result -= 36;
        }
        return result;
    }

    function dataCodewords(ver, ecl) {
        return Math.floor(rawDataModules(ver) / 8)
            - ECC_PER_BLOCK[ecl][ver] * NUM_BLOCKS[ecl][ver];
    }

    function alignmentPositions(ver) {
        if (ver === 1) return [];
        var numAlign = Math.floor(ver / 7) + 2;
        var step = (ver === 32) ? 26 : Math.ceil((ver * 4 + 4) / (numAlign * 2 - 2)) * 2;
        var result = [6];
        for (var pos = ver * 4 + 10; result.length < numAlign; pos -= step) {
            result.splice(1, 0, pos);
        }
        return result;
    }

    /* ---- Reed-Solomon over GF(256), primitive polynomial 0x11D ---- */

    function rsMultiply(x, y) {
        var z = 0;
        for (var i = 7; i >= 0; i--) {
            z = (z << 1) ^ ((z >>> 7) * 0x11D);
            z ^= ((y >>> i) & 1) * x;
        }
        return z & 0xFF;
    }

    function rsDivisor(degree) {
        var result = [], i, j;
        for (i = 0; i < degree; i++) result.push(0);
        result[degree - 1] = 1;
        var root = 1;
        for (i = 0; i < degree; i++) {
            for (j = 0; j < degree; j++) {
                result[j] = rsMultiply(result[j], root);
                if (j + 1 < degree) result[j] ^= result[j + 1];
            }
            root = rsMultiply(root, 0x02);
        }
        return result;
    }

    function rsRemainder(data, divisor) {
        var result = [], i, d;
        for (i = 0; i < divisor.length; i++) result.push(0);
        for (d = 0; d < data.length; d++) {
            var factor = data[d] ^ result.shift();
            result.push(0);
            for (i = 0; i < result.length; i++) {
                result[i] ^= rsMultiply(divisor[i], factor);
            }
        }
        return result;
    }

    /* ---- Bit stream ---- */

    function utf8Bytes(text) {
        if (typeof TextEncoder !== "undefined") {
            return Array.prototype.slice.call(new TextEncoder().encode(text));
        }
        var out = [], legacy = unescape(encodeURIComponent(text));
        for (var i = 0; i < legacy.length; i++) out.push(legacy.charCodeAt(i) & 0xFF);
        return out;
    }

    function BitBuffer() { this.bits = []; }

    BitBuffer.prototype.append = function (value, len) {
        for (var i = len - 1; i >= 0; i--) this.bits.push((value >>> i) & 1);
    };

    function buildCodewords(bytes, ver, ecl) {
        var capacityBits = dataCodewords(ver, ecl) * 8;
        var bb = new BitBuffer(), i;

        bb.append(0x4, 4);                                  /* byte mode */
        bb.append(bytes.length, ver < 10 ? 8 : 16);
        for (i = 0; i < bytes.length; i++) bb.append(bytes[i], 8);

        bb.append(0, Math.min(4, capacityBits - bb.bits.length));
        bb.append(0, (8 - bb.bits.length % 8) % 8);

        for (var pad = 0xEC; bb.bits.length < capacityBits; pad ^= 0xEC ^ 0x11) {
            bb.append(pad, 8);
        }

        var words = [];
        for (var b = 0; b < bb.bits.length; b += 8) {
            var w = 0;
            for (var k = 0; k < 8; k++) w = (w << 1) | bb.bits[b + k];
            words.push(w);
        }
        return words;
    }

    function addEccAndInterleave(data, ver, ecl) {
        var numBlocks = NUM_BLOCKS[ecl][ver];
        var blockEccLen = ECC_PER_BLOCK[ecl][ver];
        var rawCodewords = Math.floor(rawDataModules(ver) / 8);
        var numShortBlocks = numBlocks - rawCodewords % numBlocks;
        var shortBlockLen = Math.floor(rawCodewords / numBlocks);
        var divisor = rsDivisor(blockEccLen);
        var blocks = [], i, j, k = 0;

        for (i = 0; i < numBlocks; i++) {
            var len = shortBlockLen - blockEccLen + (i < numShortBlocks ? 0 : 1);
            var dat = data.slice(k, k + len);
            k += len;
            var ecc = rsRemainder(dat, divisor);
            if (i < numShortBlocks) dat = dat.concat([0]);
            blocks.push(dat.concat(ecc));
        }

        var result = [];
        for (i = 0; i < blocks[0].length; i++) {
            for (j = 0; j < blocks.length; j++) {
                if (i !== shortBlockLen - blockEccLen || j >= numShortBlocks) {
                    result.push(blocks[j][i]);
                }
            }
        }
        return result;
    }

    /* ---- Matrix ---- */

    function QrMatrix(ver) {
        this.version = ver;
        this.size = ver * 4 + 17;
        this.modules = [];
        this.isFunction = [];
        for (var y = 0; y < this.size; y++) {
            var row = [], flags = [];
            for (var x = 0; x < this.size; x++) { row.push(false); flags.push(false); }
            this.modules.push(row);
            this.isFunction.push(flags);
        }
    }

    QrMatrix.prototype.setFunction = function (x, y, dark) {
        this.modules[y][x] = dark;
        this.isFunction[y][x] = true;
    };

    QrMatrix.prototype.drawFinder = function (cx, cy) {
        for (var dy = -4; dy <= 4; dy++) {
            for (var dx = -4; dx <= 4; dx++) {
                var dist = Math.max(Math.abs(dx), Math.abs(dy));
                var x = cx + dx, y = cy + dy;
                if (x >= 0 && x < this.size && y >= 0 && y < this.size) {
                    this.setFunction(x, y, dist !== 2 && dist !== 4);
                }
            }
        }
    };

    QrMatrix.prototype.drawAlignment = function (cx, cy) {
        for (var dy = -2; dy <= 2; dy++) {
            for (var dx = -2; dx <= 2; dx++) {
                this.setFunction(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
            }
        }
    };

    QrMatrix.prototype.drawFormatBits = function (ecl, mask) {
        var data = (ECL_FORMAT_BITS[ecl] << 3) | mask;
        var rem = data, i;
        for (i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
        var bits = ((data << 10) | rem) ^ 0x5412;

        for (i = 0; i <= 5; i++) this.setFunction(8, i, ((bits >>> i) & 1) !== 0);
        this.setFunction(8, 7, ((bits >>> 6) & 1) !== 0);
        this.setFunction(8, 8, ((bits >>> 7) & 1) !== 0);
        this.setFunction(7, 8, ((bits >>> 8) & 1) !== 0);
        for (i = 9; i < 15; i++) this.setFunction(14 - i, 8, ((bits >>> i) & 1) !== 0);

        for (i = 0; i < 8; i++) {
            this.setFunction(this.size - 1 - i, 8, ((bits >>> i) & 1) !== 0);
        }
        for (i = 8; i < 15; i++) {
            this.setFunction(8, this.size - 15 + i, ((bits >>> i) & 1) !== 0);
        }
        this.setFunction(8, this.size - 8, true);           /* always dark */
    };

    QrMatrix.prototype.drawVersionBits = function () {
        if (this.version < 7) return;
        var rem = this.version, i;
        for (i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
        var bits = (this.version << 12) | rem;

        for (i = 0; i < 18; i++) {
            var dark = ((bits >>> i) & 1) !== 0;
            var a = this.size - 11 + i % 3;
            var b = Math.floor(i / 3);
            this.setFunction(a, b, dark);
            this.setFunction(b, a, dark);
        }
    };

    QrMatrix.prototype.drawFunctionPatterns = function (ecl) {
        var i, j;

        for (i = 0; i < this.size; i++) {
            this.setFunction(6, i, i % 2 === 0);
            this.setFunction(i, 6, i % 2 === 0);
        }

        this.drawFinder(3, 3);
        this.drawFinder(this.size - 4, 3);
        this.drawFinder(3, this.size - 4);

        var pos = alignmentPositions(this.version);
        for (i = 0; i < pos.length; i++) {
            for (j = 0; j < pos.length; j++) {
                var corner = (i === 0 && j === 0)
                    || (i === 0 && j === pos.length - 1)
                    || (i === pos.length - 1 && j === 0);
                if (!corner) this.drawAlignment(pos[i], pos[j]);
            }
        }

        this.drawFormatBits(ecl, 0);                        /* placeholder */
        this.drawVersionBits();
    };

    QrMatrix.prototype.drawCodewords = function (data) {
        var i = 0;
        for (var right = this.size - 1; right >= 1; right -= 2) {
            if (right === 6) right = 5;                     /* skip timing column */
            for (var vert = 0; vert < this.size; vert++) {
                for (var j = 0; j < 2; j++) {
                    var x = right - j;
                    var upward = ((right + 1) & 2) === 0;
                    var y = upward ? this.size - 1 - vert : vert;
                    if (!this.isFunction[y][x] && i < data.length * 8) {
                        this.modules[y][x] = ((data[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0;
                        i++;
                    }
                }
            }
        }
    };

    function maskAt(mask, x, y) {
        switch (mask) {
            case 0: return (x + y) % 2 === 0;
            case 1: return y % 2 === 0;
            case 2: return x % 3 === 0;
            case 3: return (x + y) % 3 === 0;
            case 4: return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
            case 5: return x * y % 2 + x * y % 3 === 0;
            case 6: return (x * y % 2 + x * y % 3) % 2 === 0;
            case 7: return ((x + y) % 2 + x * y % 3) % 2 === 0;
        }
        return false;
    }

    QrMatrix.prototype.applyMask = function (mask) {
        for (var y = 0; y < this.size; y++) {
            for (var x = 0; x < this.size; x++) {
                if (!this.isFunction[y][x] && maskAt(mask, x, y)) {
                    this.modules[y][x] = !this.modules[y][x];
                }
            }
        }
    };

    /* Rule 3 works off a rolling history of the last seven run lengths. */
    QrMatrix.prototype.addRun = function (runLength, history) {
        if (history[0] === 0) runLength += this.size;       /* leading light border */
        history.pop();
        history.unshift(runLength);
    };

    QrMatrix.prototype.countFinders = function (history) {
        var n = history[1];
        var core = n > 0 && history[2] === n && history[3] === n * 3
            && history[4] === n && history[5] === n;
        return (core && history[0] >= n * 4 && history[6] >= n ? 1 : 0)
            + (core && history[6] >= n * 4 && history[0] >= n ? 1 : 0);
    };

    QrMatrix.prototype.terminateRuns = function (runColor, runLength, history) {
        if (runColor) {
            this.addRun(runLength, history);
            runLength = 0;
        }
        runLength += this.size;                             /* trailing light border */
        this.addRun(runLength, history);
        return this.countFinders(history);
    };

    QrMatrix.prototype.penalty = function () {
        var result = 0, size = this.size, x, y, runColor, runLen, history;

        for (y = 0; y < size; y++) {
            runColor = false; runLen = 0; history = [0, 0, 0, 0, 0, 0, 0];
            for (x = 0; x < size; x++) {
                if (this.modules[y][x] === runColor) {
                    runLen++;
                    if (runLen === 5) result += PENALTY_N1;
                    else if (runLen > 5) result++;
                } else {
                    this.addRun(runLen, history);
                    if (!runColor) result += this.countFinders(history) * PENALTY_N3;
                    runColor = this.modules[y][x];
                    runLen = 1;
                }
            }
            result += this.terminateRuns(runColor, runLen, history) * PENALTY_N3;
        }

        for (x = 0; x < size; x++) {
            runColor = false; runLen = 0; history = [0, 0, 0, 0, 0, 0, 0];
            for (y = 0; y < size; y++) {
                if (this.modules[y][x] === runColor) {
                    runLen++;
                    if (runLen === 5) result += PENALTY_N1;
                    else if (runLen > 5) result++;
                } else {
                    this.addRun(runLen, history);
                    if (!runColor) result += this.countFinders(history) * PENALTY_N3;
                    runColor = this.modules[y][x];
                    runLen = 1;
                }
            }
            result += this.terminateRuns(runColor, runLen, history) * PENALTY_N3;
        }

        for (y = 0; y < size - 1; y++) {
            for (x = 0; x < size - 1; x++) {
                var c = this.modules[y][x];
                if (c === this.modules[y][x + 1] && c === this.modules[y + 1][x]
                    && c === this.modules[y + 1][x + 1]) {
                    result += PENALTY_N2;
                }
            }
        }

        var dark = 0;
        for (y = 0; y < size; y++) {
            for (x = 0; x < size; x++) if (this.modules[y][x]) dark++;
        }
        var total = size * size;
        var k = Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1;
        result += k * PENALTY_N4;

        return result;
    };

    /* ---- Public API ---- */

    function encode(text, eclName) {
        var ecl = ECL[eclName || "M"];
        if (ecl === undefined) throw new Error("Unknown error correction level: " + eclName);

        var bytes = utf8Bytes(String(text == null ? "" : text));

        var ver = 0;
        for (var v = 1; v <= 40; v++) {
            var headerBits = 4 + (v < 10 ? 8 : 16);
            if (headerBits + bytes.length * 8 <= dataCodewords(v, ecl) * 8) { ver = v; break; }
        }
        if (!ver) throw new Error("Data is too long for a QR code");

        var codewords = addEccAndInterleave(buildCodewords(bytes, ver, ecl), ver, ecl);

        var qr = new QrMatrix(ver);
        qr.drawFunctionPatterns(ecl);
        qr.drawCodewords(codewords);

        var bestMask = 0, bestPenalty = Infinity;
        for (var mask = 0; mask < 8; mask++) {
            qr.applyMask(mask);
            qr.drawFormatBits(ecl, mask);
            var p = qr.penalty();
            if (p < bestPenalty) { bestPenalty = p; bestMask = mask; }
            qr.applyMask(mask);                             /* xor is its own inverse */
        }

        qr.applyMask(bestMask);
        qr.drawFormatBits(ecl, bestMask);

        return { size: qr.size, version: ver, mask: bestMask, modules: qr.modules };
    }

    function escapeAttr(value) {
        return String(value).replace(/[&<>"]/g, function (c) {
            if (c === "&") return "&amp;";
            if (c === "<") return "&lt;";
            if (c === ">") return "&gt;";
            return "&quot;";
        });
    }

    /** One <path> of 1x1 squares, so it stays sharp at any print size. */
    function toSvg(text, options) {
        var opts = options || {};
        var quiet = opts.quiet == null ? 4 : opts.quiet;
        var dark = opts.dark || "#0a0b0d";
        var light = opts.light || "#ffffff";
        var qr = encode(text, opts.ecl);
        var dim = qr.size + quiet * 2;
        var parts = [];

        for (var y = 0; y < qr.size; y++) {
            for (var x = 0; x < qr.size; x++) {
                if (qr.modules[y][x]) {
                    parts.push("M" + (x + quiet) + " " + (y + quiet) + "h1v1h-1z");
                }
            }
        }

        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + dim + " " + dim + '"'
            + ' role="img" aria-label="' + escapeAttr(opts.label || "QR code") + '"'
            + ' shape-rendering="crispEdges">'
            + '<rect width="' + dim + '" height="' + dim + '" fill="' + light + '"/>'
            + '<path fill="' + dark + '" d="' + parts.join("") + '"/>'
            + "</svg>";
    }

    var api = { encode: encode, toSvg: toSvg };

    if (typeof module !== "undefined" && module.exports) module.exports = api;
    global.QRCodeGen = api;
}(typeof window !== "undefined" ? window : this));
