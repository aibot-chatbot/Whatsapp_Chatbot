import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
	builtinIds,
	insertDockerignoreLine,
	type IndustrySpec,
	prBody,
	renderTemplateFile,
	validateSpec,
} from "./industry";

const REPO = resolve(__dirname, "../../..");

const SPEC: IndustrySpec = {
	id: "dental_clinic",
	name: "Dental clinic",
	description: "Answer dental service, price and appointment policy questions.",
	questions: ["Which branch are you asking about?", "Which dental service do you need?"],
	required_information: ["Clinic name and branches", "Dental services and prices"],
	unavailable_actions: ["Booking or changing appointments", "Diagnosis or treatment advice"],
	classification_hint: "Needs dental services such as scaling, fillings, braces or dentures.",
	lead_rule: "The customer wants a dental appointment or a treatment quotation.",
	rules:
		"Dental clinic: answer supported questions about published dental services, prices and policies. Do not diagnose, give treatment advice or confirm appointment slots.",
	samples: [
		"Our dental clinic offers scaling and braces.",
		"Klinik gigi kami menawarkan cabutan dan pendakap.",
		"本牙科诊所提供洗牙和矫正服务。",
	],
};

describe("validateSpec mirrors the Python catalog rules", () => {
	it("accepts a valid spec", () => {
		expect(validateSpec(SPEC, ["clinic"])).toEqual([]);
	});

	it.each([
		["bad id", { id: "Dental-Clinic" }],
		["taken id", { id: "clinic" }],
		["short name", { name: "X" }],
		["one question", { questions: ["Only one question?"] }],
		["short hint", { classification_hint: "short" }],
		["short rules", { rules: "Too short." }],
		["long rules", { rules: "x".repeat(1501) }],
		["two samples", { samples: SPEC.samples.slice(0, 2) }],
		["long sample", { samples: [...SPEC.samples.slice(0, 2), "x".repeat(241)] }],
	])("rejects %s", (_label, change) => {
		expect(validateSpec({ ...SPEC, ...change } as IndustrySpec, ["clinic"])).not.toEqual([]);
	});

	it("counts characters like Python (code points, not UTF-16 units)", () => {
		const hint = "😀".repeat(20); // 20 code points = 40 UTF-16 units
		expect(validateSpec({ ...SPEC, classification_hint: hint }, [])).toEqual([]);
	});

	// Same table as tests/test_industry_template_extensions.py: one character rule on both sides.
	it.each([
		["NEL around the name (Python strips it, JS trim does not)", { name: "\u0085Dental\u0085" }],
		["file separator", { name: "\u001cDental clinic" }],
		["NUL", { name: "Dental\u0000clinic" }],
		["newline in a single-line field", { name: "Dental\n\nCo-authored-by: X <x@y.z>" }],
		["bidi override", { description: "Answer dental questions ‮ for the clinic." }],
		["line separator", { lead_rule: "Wants an appointment today." }],
		["lone surrogate", { classification_hint: "Needs dental services \ud800 such as scaling." }],
		["byte-order mark", { name: "﻿Dental clinic" }],
		["carriage return in rules", { rules: SPEC.rules.replace(". ", ".\r\n") }],
		["bidi isolate in a sample", { samples: [SPEC.samples[0], SPEC.samples[1], "本牙科诊所⁦提供洗牙和矫正服务。"] }],
	])("rejects %s", (_label, change) => {
		expect(validateSpec({ ...SPEC, ...change } as IndustrySpec, [])).not.toEqual([]);
	});

	it("allows newlines in rules and any script or emoji", () => {
		const spec = { ...SPEC, name: "牙科诊所 Klinik 🦷", rules: SPEC.rules.replace(". ", ".\n") };
		expect(validateSpec(spec, [])).toEqual([]);
	});
});

describe("renderTemplateFile", () => {
	it("writes a data-only file the Python loader accepts (round-trip fixture)", () => {
		const text = renderTemplateFile(SPEC, "some-dev");
		expect(text).toContain('TEMPLATE = {\n    "id": "dental_clinic"');
		expect(text).toContain('"version": "1.0.0"');
		expect(text).not.toMatch(/\b(import|def|lambda|exec|eval)\b/);
		const dir = join(REPO, "..", "mcp-roundtrip-fixture");
		mkdirSync(dir, { recursive: true });
		writeFileSync(join(dir, "dental_clinic.py"), text, "utf8");
	});

	it("strips anything but GitHub-login characters from the author credit", () => {
		expect(renderTemplateFile(SPEC, 'evil"""\nimport os')).toContain("@evilimportos via");
	});

	it("keeps quotes and newlines inside JSON-escaped strings", () => {
		const text = renderTemplateFile({ ...SPEC, rules: `${SPEC.rules} Say "hi"\nthen stop.` }, "dev");
		expect(text).toContain('Say \\"hi\\"\\nthen stop.');
	});
});

describe("insertDockerignoreLine", () => {
	const real = readFileSync(join(REPO, ".dockerignore"), "utf8");
	const path = "app/services/industry_templates/dental_clinic.py";

	it("keeps the real allowlist sorted and unique", () => {
		const updated = insertDockerignoreLine(real, path);
		const allow = updated.split("\n").filter((line) => line.startsWith("!"));
		expect(allow).toContain(`!${path}`);
		expect(allow).toEqual([...new Set(allow)].sort());
		expect(updated.split("\n").length).toBe(real.split("\n").length + 1);
	});

	it("is idempotent", () => {
		const once = insertDockerignoreLine(real, path);
		expect(insertDockerignoreLine(once, path)).toBe(once);
	});
});

describe("builtinIds", () => {
	it("reads the nine built-in industries from the real catalog", () => {
		const catalog = readFileSync(join(REPO, "app/services/industry_template_catalog.py"), "utf8");
		expect(builtinIds(catalog)).toEqual([
			"restaurant", "clinic", "tuition_center", "general", "beauty_salon",
			"property_agent", "car_workshop", "retail_shop", "travel_agency",
		]);
	});
});

describe("prBody", () => {
	it("carries the reviewer checklist", () => {
		expect(prBody(SPEC, "dev")).toContain("never promise an action the bot cannot perform");
	});
});
