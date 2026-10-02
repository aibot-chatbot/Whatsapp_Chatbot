import OAuthProvider from "@cloudflare/workers-oauth-provider";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpAgent } from "agents/mcp";
import { Octokit } from "octokit";
import { z } from "zod";
import { GitHubHandler } from "./github-handler";
import {
	baseLoadsExtensions,
	branchConflict,
	builtinIds,
	CATALOG_PATH,
	DOCKERIGNORE_PATH,
	EXTENSION_DIR,
	type IndustrySpec,
	insertDockerignoreLine,
	prBody,
	publishBranch,
	renderTemplateFile,
	validateSpec,
} from "./industry";

// Context from the GitHub sign-in, encrypted inside the OAuth token (this.props).
type Props = {
	login: string;
	name: string;
	email: string;
	accessToken: string;
};

const SPEC_SHAPE = {
	id: z.string().describe("New industry id: lowercase letters and underscores, e.g. dental_clinic"),
	name: z.string().describe("Display name, 3-60 characters, e.g. 'Dental clinic'"),
	description: z.string().describe("One sentence: what the bot answers for this industry (10-200 characters)"),
	questions: z.array(z.string()).describe("2-5 clarifying questions the bot may ask, one at a time"),
	required_information: z
		.array(z.string())
		.describe("2-6 kinds of business information the owner must upload (services, prices, policies)"),
	unavailable_actions: z
		.array(z.string())
		.describe("2-8 actions the bot must never claim to perform (bookings, payments, confirming availability)"),
	classification_hint: z
		.string()
		.describe("Evidence that identifies this industry in an uploaded document, and what it must NOT be confused with (20-400)"),
	lead_rule: z.string().describe("When a customer counts as a qualified lead for this industry (10-300 characters)"),
	rules: z
		.string()
		.describe(
			"Chatbot rules text (100-1500 characters). Answer only from published business information; never promise bookings, payments, stock or availability; no medical, legal or financial advice.",
		),
	samples: z
		.array(z.string())
		.describe("Exactly 3 short sentences a real business of this industry would write: one English, one Malay, one Chinese"),
};

const text = (value: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] });
const failure = (message: string) => ({ content: [{ type: "text" as const, text: message }], isError: true });

export class IndustryTemplateMCP extends McpAgent<Env, Record<string, never>, Props> {
	server = new McpServer({ name: "Omnexa industry templates", version: "0.1.0" });

	private octokit() {
		return new Octokit({ auth: this.props!.accessToken });
	}

	private repo() {
		return { owner: this.env.REPO_OWNER, repo: this.env.REPO_NAME };
	}

	/** Only collaborators who can push to the repository may use any tool. */
	private async requireWriteAccess() {
		const { data } = await this.octokit().rest.repos.getCollaboratorPermissionLevel({
			...this.repo(),
			username: this.props!.login,
		});
		const allowed = ["admin", "maintain", "write"];
		if (!allowed.includes(data.permission) && !allowed.includes(data.role_name)) {
			throw new Error(`@${this.props!.login} needs write access to ${this.env.REPO_OWNER}/${this.env.REPO_NAME}.`);
		}
	}

	private async readText(path: string): Promise<string | null> {
		try {
			const { data } = await this.octokit().rest.repos.getContent({ ...this.repo(), path, ref: this.env.BASE_BRANCH });
			if (Array.isArray(data) || data.type !== "file") return null;
			const bytes = Uint8Array.from(atob(data.content.replace(/\n/g, "")), (c) => c.charCodeAt(0));
			return new TextDecoder().decode(bytes);
		} catch (error) {
			if ((error as { status?: number }).status === 404) return null;
			throw error;
		}
	}

	private async addedIds(): Promise<string[]> {
		try {
			const { data } = await this.octokit().rest.repos.getContent({
				...this.repo(),
				path: EXTENSION_DIR,
				ref: this.env.BASE_BRANCH,
			});
			return Array.isArray(data)
				? data.filter((item) => item.type === "file" && item.name.endsWith(".py")).map((item) => item.name.slice(0, -3))
				: [];
		} catch (error) {
			if ((error as { status?: number }).status === 404) return [];
			throw error;
		}
	}

	private async industries() {
		const catalog = await this.readText(CATALOG_PATH);
		if (!catalog) throw new Error(`${CATALOG_PATH} not found on ${this.env.BASE_BRANCH}.`);
		return {
			builtIn: builtinIds(catalog),
			added: await this.addedIds(),
			acceptsNewIndustries: baseLoadsExtensions(catalog),
		};
	}

	private async branchExists(branch: string): Promise<boolean> {
		try {
			await this.octokit().rest.git.getRef({ ...this.repo(), ref: `heads/${branch}` });
			return true;
		} catch (error) {
			if ((error as { status?: number }).status === 404) return false;
			throw error;
		}
	}

	private async check(spec: IndustrySpec) {
		const { builtIn, added, acceptsNewIndustries } = await this.industries();
		const errors = validateSpec(spec, [...builtIn, ...added]);
		if (!acceptsNewIndustries) {
			errors.push(
				`${this.env.BASE_BRANCH} cannot load added industries yet (its catalog has no load_extensions); merge the industry-template loader into it first.`,
			);
		}
		const branch = `industry/${spec.id}`;
		if (!errors.length && (await this.branchExists(branch))) {
			const { data: pulls } = await this.octokit().rest.pulls.list({
				...this.repo(),
				head: `${this.env.REPO_OWNER}:${branch}`,
				state: "all",
			});
			errors.push(branchConflict(branch, pulls));
		}
		return { errors, branch, filePath: `${EXTENSION_DIR}/${spec.id}.py` };
	}

	async init() {
		this.server.tool(
			"list_industries",
			"List the chatbot industries on the base branch: built-in ones and ones added through this server.",
			{},
			async () => {
				try {
					await this.requireWriteAccess();
					return text({ base_branch: this.env.BASE_BRANCH, ...(await this.industries()) });
				} catch (error) {
					return failure((error as Error).message);
				}
			},
		);

		this.server.tool(
			"validate_industry",
			"Check a new industry against the catalog rules and preview the file that propose_industry would add. Changes nothing.",
			SPEC_SHAPE,
			async (spec) => {
				try {
					await this.requireWriteAccess();
					const { errors, filePath } = await this.check(spec);
					return text({
						valid: errors.length === 0,
						errors,
						file_path: filePath,
						file_preview: errors.length ? null : renderTemplateFile(spec, this.props!.login),
					});
				} catch (error) {
					return failure((error as Error).message);
				}
			},
		);

		this.server.tool(
			"propose_industry",
			"Open a pull request that adds a new industry (one data-only file plus its .dockerignore line) to the base branch. Never merges or deploys: a human reviews, CI runs the tests, and the owner merges.",
			SPEC_SHAPE,
			async (spec) => {
				try {
					await this.requireWriteAccess();
					const { errors, branch, filePath } = await this.check(spec);
					if (errors.length) return failure(`Not proposed:\n- ${errors.join("\n- ")}`);
					const octokit = this.octokit();
					const repo = this.repo();
					const base = this.env.BASE_BRANCH;
					const dockerignore = await this.readText(DOCKERIGNORE_PATH);
					if (dockerignore === null) throw new Error(`${DOCKERIGNORE_PATH} not found on ${base}.`);
					const { data: ref } = await octokit.rest.git.getRef({ ...repo, ref: `heads/${base}` });
					const { data: baseCommit } = await octokit.rest.git.getCommit({ ...repo, commit_sha: ref.object.sha });
					const { data: tree } = await octokit.rest.git.createTree({
						...repo,
						base_tree: baseCommit.tree.sha,
						tree: [
							{ path: filePath, mode: "100644", type: "blob", content: renderTemplateFile(spec, this.props!.login) },
							{
								path: DOCKERIGNORE_PATH,
								mode: "100644",
								type: "blob",
								content: insertDockerignoreLine(dockerignore, filePath),
							},
						],
					});
					const { data: commit } = await octokit.rest.git.createCommit({
						...repo,
						message: `feat: add the ${spec.name.trim()} industry (${spec.id})\n\nProposed by @${this.props!.login} via industry-template-mcp.`,
						tree: tree.sha,
						parents: [ref.object.sha],
					});
					const pullRequest = await publishBranch(octokit, repo, {
						branch,
						sha: commit.sha,
						base,
						title: `feat: add the ${spec.name.trim()} industry (${spec.id})`,
						body: prBody(spec, this.props!.login),
					});
					return text({ pull_request: pullRequest, branch, file_path: filePath });
				} catch (error) {
					return failure((error as Error).message);
				}
			},
		);
	}
}

export default new OAuthProvider({
	apiHandler: IndustryTemplateMCP.serve("/mcp"),
	apiRoute: "/mcp",
	authorizeEndpoint: "/authorize",
	clientRegistrationEndpoint: "/register",
	defaultHandler: GitHubHandler as any,
	tokenEndpoint: "/token",
});
