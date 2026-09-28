// Pure logic for industry-template-mcp: validation (mirrors
// app/services/industry_template_catalog.validate_extension, which stays the authority
// and runs again in CI), file rendering, .dockerignore insertion and the PR body.

export const EXTENSION_DIR = "app/services/industry_templates";
export const CATALOG_PATH = "app/services/industry_template_catalog.py";
export const DOCKERIGNORE_PATH = ".dockerignore";
export const TEMPLATE_VERSION = "1.0.0";

export type IndustrySpec = {
	id: string;
	name: string;
	description: string;
	questions: string[];
	required_information: string[];
	unavailable_actions: string[];
	classification_hint: string;
	lead_rule: string;
	rules: string;
	samples: string[];
};

const ID_PATTERN = /^[a-z][a-z_]{1,39}$/;
const TEXT_BOUNDS: Record<string, [number, number]> = {
	name: [3, 60],
	description: [10, 200],
	classification_hint: [20, 400],
	lead_rule: [10, 300],
};
const LIST_BOUNDS: Record<string, [number, number]> = {
	questions: [2, 5],
	required_information: [2, 6],
	unavailable_actions: [2, 8],
};

// Python's len() counts code points; JavaScript's .length counts UTF-16 units.
const codePoints = (value: string) => [...value.trim()].length;

// Same character rule as the Python catalog (_FORBIDDEN_CATEGORIES/_FORBIDDEN_CHARACTERS): no
// control, surrogate, private-use, line/paragraph separator, bidi-control or byte-order-mark
// characters; "\n" only in rules. It also makes trim() agree with Python's str.strip().
const FORBIDDEN = /[\p{Cc}\p{Cs}\p{Co}\p{Zl}\p{Zp}‪-‮⁦-⁩﻿]/u;

function checkText(errors: string[], what: string, value: unknown, low: number, high: number, multiline = false) {
	if (typeof value !== "string" || codePoints(value) < low || codePoints(value) > high) {
		errors.push(`${what} must be text of ${low}-${high} characters`);
	} else if (FORBIDDEN.test(multiline ? value.replaceAll("\n", "") : value)) {
		errors.push(`${what} contains a control, bidi, line-break or other invisible character`);
	}
}

/** Every problem with the spec; an empty list means valid. `taken` = built-in + existing ids. */
export function validateSpec(spec: IndustrySpec, taken: Iterable<string>): string[] {
	const errors: string[] = [];
	if (typeof spec.id !== "string" || !ID_PATTERN.test(spec.id)) {
		errors.push("id must match ^[a-z][a-z_]{1,39}$ (lowercase letters and underscores)");
	} else if (new Set(taken).has(spec.id)) {
		errors.push(`id "${spec.id}" already exists`);
	}
	for (const [field, [low, high]] of Object.entries(TEXT_BOUNDS)) {
		checkText(errors, field, (spec as Record<string, unknown>)[field], low, high);
	}
	for (const [field, [low, high]] of Object.entries(LIST_BOUNDS)) {
		const items = (spec as Record<string, unknown>)[field];
		if (!Array.isArray(items) || items.length < low || items.length > high) {
			errors.push(`${field} must list ${low}-${high} items`);
			continue;
		}
		items.forEach((item, index) => checkText(errors, `${field}[${index}]`, item, 5, 150));
	}
	checkText(errors, "rules", spec.rules, 100, 1500, true);
	if (!Array.isArray(spec.samples) || spec.samples.length !== 3) {
		errors.push("samples must list exactly 3 sentences (English, Malay, Chinese)");
	} else {
		spec.samples.forEach((sample, index) => checkText(errors, `samples[${index}]`, sample, 10, 240));
	}
	return errors;
}

/** The data-only Python file the catalog parses with ast.literal_eval. */
export function renderTemplateFile(spec: IndustrySpec, login: string): string {
	const template = {
		id: spec.id,
		version: TEMPLATE_VERSION,
		name: spec.name.trim(),
		description: spec.description.trim(),
		questions: spec.questions.map((q) => q.trim()),
		required_information: spec.required_information.map((q) => q.trim()),
		unavailable_actions: spec.unavailable_actions.map((q) => q.trim()),
		classification_hint: spec.classification_hint.trim(),
		lead_rule: spec.lead_rule.trim(),
	};
	const author = login.replace(/[^A-Za-z0-9-]/g, "");
	// JSON string/array/object literals of strings are valid Python literals.
	return (
		`"""Industry template: ${spec.id}. Proposed by @${author} via industry-template-mcp. Data only: parsed, never executed."""\n` +
		`TEMPLATE = ${JSON.stringify(template, null, 4)}\n` +
		`RULES = ${JSON.stringify(spec.rules.trim())}\n` +
		`SAMPLES = ${JSON.stringify(spec.samples.map((s) => s.trim()), null, 4)}\n`
	);
}

/** Insert `!<path>` keeping the allowlist sorted (test_container_release pins the order). */
export function insertDockerignoreLine(text: string, path: string): string {
	const entry = `!${path}`;
	const lines = text.split("\n");
	if (lines.includes(entry)) return text;
	const allow = lines.map((line, index) => ({ line, index })).filter(({ line }) => line.startsWith("!"));
	const after = allow.find(({ line }) => line > entry);
	const at = after ? after.index : (allow.at(-1)?.index ?? lines.length - 1) + 1;
	lines.splice(at, 0, entry);
	return lines.join("\n");
}

/** Built-in ids from the catalog source (each built-in template has one `        "id": "<id>",` line). */
export function builtinIds(catalogSource: string): string[] {
	return [...catalogSource.matchAll(/^ {8}"id": "([a-z][a-z_]{1,39})",$/gm)].map((match) => match[1]);
}

export function prBody(spec: IndustrySpec, login: string): string {
	return [
		`Adds the **${spec.name.trim()}** industry (\`${spec.id}\`), proposed by @${login} through industry-template-mcp.`,
		"",
		"The file is data only: the catalog parses it with `ast.literal_eval` and never executes it. CI runs the industry and container tests.",
		"",
		"### Reviewer checklist",
		"- [ ] `rules` never promise an action the bot cannot perform (booking, payment, confirming availability)",
		"- [ ] No medical, legal or financial advice beyond published business information",
		"- [ ] `classification_hint` names what this industry is NOT confused with",
		"- [ ] The 3 samples read like real businesses (English, Malay, Chinese)",
		"- [ ] Live detection check run on the samples (see docs/superpowers/plans/2026-09-28-industry-template-mcp.md)",
		"- [ ] After merge: deploy Flask and redeploy the worker on the same image",
	].join("\n");
}

/** Whether the base branch's catalog loads industry_templates/ at all; without it a proposal is inert. */
export function baseLoadsExtensions(catalogSource: string): boolean {
	return catalogSource.includes("def load_extensions(");
}

type PullSummary = { state: string; merged_at: string | null; html_url: string };

/** Why an existing industry/<id> branch blocks a new proposal, from the pull requests that used it. */
export function branchConflict(branch: string, pulls: PullSummary[]): string {
	const pull = pulls.find((item) => item.state === "open") ?? pulls[0];
	if (!pull) {
		return `Branch ${branch} exists without a pull request (an earlier proposal failed part-way); delete the branch on GitHub to propose this id again.`;
	}
	if (pull.state === "open") {
		return `Branch ${branch} already has an open pull request: ${pull.html_url}. Update or close that one instead.`;
	}
	const outcome = pull.merged_at ? "merged" : "closed";
	return `Branch ${branch} is left over from a ${outcome} pull request (${pull.html_url}); delete the branch on GitHub to propose this id again.`;
}

type Repo = { owner: string; repo: string };
// The slice of Octokit that publishBranch uses, so tests can pass a fake.
type BranchApi = {
	rest: {
		git: {
			createRef(params: Repo & { ref: string; sha: string }): Promise<unknown>;
			deleteRef(params: Repo & { ref: string }): Promise<unknown>;
		};
		pulls: {
			create(params: Repo & { title: string; head: string; base: string; body: string }): Promise<{
				data: { html_url: string };
			}>;
		};
	};
};

/** Create industry/<id> at `sha` and open its pull request. If the pull request cannot be
 * opened, delete the branch again so the id is not blocked by an orphan. */
export async function publishBranch(
	github: BranchApi,
	repo: Repo,
	request: { branch: string; sha: string; base: string; title: string; body: string },
): Promise<string> {
	const { branch, sha, base, title, body } = request;
	await github.rest.git.createRef({ ...repo, ref: `refs/heads/${branch}`, sha });
	try {
		const { data } = await github.rest.pulls.create({ ...repo, title, head: branch, base, body });
		return data.html_url;
	} catch (error) {
		try {
			await github.rest.git.deleteRef({ ...repo, ref: `heads/${branch}` });
		} catch (cleanup) {
			throw new Error(
				`${(error as Error).message}. Branch ${branch} was created but could not be removed (${(cleanup as Error).message}); delete it on GitHub before retrying.`,
			);
		}
		throw error;
	}
}
