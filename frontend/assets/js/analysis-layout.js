// Analysis report layouts. Each report type (CRM, Bookings, Sales, Documents) has its own
// headline numbers and sections, frozen into the report when it was made, so a report always
// looks the same as its PDF and Excel file. The Analysis page passes its own element helpers,
// so both draw alike. Every value is written with textContent; nothing is parsed as HTML.
(function () {
    "use strict";
    /* pure:start (run in Node by tests/test_analysis_layout_frontend.py) */
    function formatMyr(micro) {
        const sen = Math.floor(Number(micro) / 10000);
        return "RM " + Math.floor(sen / 100).toLocaleString("en-US") + "." + String(sen % 100).padStart(2, "0");
    }
    function metricValue(metric) {
        if (!metric || metric.value == null || !["available", "partial"].includes(metric.status)) return null;
        return metric.unit === "micro_myr" ? formatMyr(metric.value) : String(metric.value);
    }
    function cellValue(table, index, value) {
        if (value == null) return "Unavailable";
        return (table.money_columns || []).includes(index) && Number.isInteger(value) ? formatMyr(value) : String(value);
    }
    // The sections this report has data for, in layout order: [{title, parts: [{kind, payload}]}].
    function layoutSections(snapshot) {
        const layout = snapshot && snapshot.layout;
        if (!layout || !Array.isArray(layout.sections)) return [];
        const byKey = list => new Map((Array.isArray(list) ? list : [])
            .filter(item => item && typeof item === "object").map(item => [item.key, item]));
        const metrics = byKey(snapshot.metrics), tables = byKey(snapshot.tables), grids = byKey(snapshot.distributions);
        const questions = snapshot.customer_questions && Array.isArray(snapshot.customer_questions.excerpts)
            && snapshot.customer_questions.excerpts.length > 0;
        const documents = Array.isArray(snapshot.documents) && snapshot.documents.length > 0;
        const sections = [];
        for (const section of layout.sections) {
            const parts = [];
            for (const item of section && Array.isArray(section.items) ? section.items : []) {
                if (item.kind === "table" && tables.has(item.key)) parts.push({kind: "table", payload: tables.get(item.key)});
                else if (item.kind === "distribution" && grids.has(item.key)) parts.push({kind: "grid", payload: grids.get(item.key)});
                else if (item.kind === "metrics") {
                    const chosen = (item.keys || []).filter(key => metrics.has(key)).map(key => metrics.get(key));
                    if (item.prefix) for (const [key, metric] of metrics) if (String(key).startsWith(item.prefix)) chosen.push(metric);
                    if (chosen.length) parts.push({kind: "metrics", payload: chosen});
                } else if (item.kind === "questions" && questions) parts.push({kind: "questions", payload: snapshot});
                else if (item.kind === "documents" && documents) parts.push({kind: "documents", payload: snapshot.documents});
            }
            if (parts.length) sections.push({title: String(section.title || "Details"), parts});
        }
        return sections;
    }
    /* pure:end */

    function card(h, metric) {
        const tile = h.el("div", null, "kw-stat");
        const head = h.el("div", null, "kw-stat-head");
        head.append(h.el("span", metric.label || "Figure", "kw-stat-label"));
        const value = metricValue(metric);
        tile.append(head, h.el("p", value ?? "Not available yet", value == null ? "kw-stat-value analysis-stat-missing" : "kw-stat-value"));
        if (metric.status === "partial") tile.append(h.el("p", "Based on part of your data", "kw-stat-unit"));
        if (typeof metric.reason === "string") tile.append(h.el("p", metric.reason, "kw-stat-unit"));
        return tile;
    }
    function table(h, data) {
        if (data.available === false) return [h.el("p", "We couldn't read this data. It doesn't mean there were none.", "kw-help")];
        const rows = Array.isArray(data.rows) ? data.rows.filter(Array.isArray) : [];
        if (!rows.length) return [h.el("p", "None in this period.", "kw-help")];
        const money = data.money_columns || [];
        const node = h.el("table", null, "analysis-table");
        node.append(h.el("caption", data.label || "", "kw-visually-hidden"));
        const head = h.el("tr");
        for (const name of Array.isArray(data.columns) ? data.columns : []) head.append(Object.assign(h.el("th", name), {scope: "col"}));
        const thead = h.el("thead"); thead.append(head);
        const body = h.el("tbody");
        for (const row of rows) {
            const line = h.el("tr");
            row.forEach((value, index) => line.append(h.el("td", cellValue(data, index, value),
                money.includes(index) || Number.isInteger(value) ? "analysis-num" : null)));
            body.append(line);
        }
        node.append(thead, body);
        const scroll = h.el("div", null, "analysis-table-scroll");
        scroll.append(node);
        return data.truncated ? [scroll, h.el("p", "Only the first rows are shown.", "kw-help")] : [scroll];
    }
    function figures(h, metrics) {
        const list = h.el("dl", null, "analysis-figures");
        for (const metric of metrics) {
            // One row per figure, so a long "why not" wraps under its label instead of squeezing it.
            const row = h.el("div", null, "analysis-figure");
            row.append(h.el("dt", metric.label || metric.key), h.el("dd", metricValue(metric) ?? metric.reason ?? "Not available yet"));
            list.append(row);
        }
        return [list];
    }
    function documentBlocks(h, documents) {
        return documents.filter(doc => doc && typeof doc === "object").map(doc => {
            const block = h.el("div", null, "analysis-document");
            block.append(h.el("h4", doc.name || "Document"));
            for (const excerpt of Array.isArray(doc.excerpts) ? doc.excerpts : []) {
                if (excerpt && typeof excerpt.text === "string" && excerpt.text.trim()) block.append(h.el("p", excerpt.text, "analysis-sample"));
            }
            if (doc.truncated) block.append(h.el("p", "Only part of this document was read.", "kw-help"));
            return block;
        });
    }
    function part(h, piece) {
        if (piece.kind === "table") return table(h, piece.payload);
        if (piece.kind === "grid") return [h.heatmap(piece.payload)];
        if (piece.kind === "metrics") return figures(h, piece.payload);
        if (piece.kind === "questions") return [h.questionSamples(piece.payload)].filter(Boolean);
        return documentBlocks(h, piece.payload);
    }
    // {title, nodes} for a report made with a layout, else null (older reports keep their look).
    function render(snapshot, result, h) {
        const layout = snapshot && snapshot.layout;
        if (!layout || !Array.isArray(layout.sections)) return null;
        const metrics = new Map((Array.isArray(snapshot.metrics) ? snapshot.metrics : [])
            .filter(item => item && typeof item === "object").map(item => [item.key, item]));
        const nodes = [];
        const cards = (Array.isArray(layout.cards) ? layout.cards : []).filter(key => metrics.has(key)).map(key => card(h, metrics.get(key)));
        if (cards.length) {
            const grid = h.el("div", null, "analysis-stats");
            grid.append(...cards);
            nodes.push(h.section("Key numbers", grid));
        }
        const summary = h.summary(result);
        if (summary) nodes.push(summary);
        for (const section of layoutSections(snapshot)) nodes.push(h.section(section.title, ...section.parts.flatMap(piece => part(h, piece))));
        return {title: String(layout.title || "Your report"), nodes};
    }
    window.AnalysisLayout = {render};
})();
