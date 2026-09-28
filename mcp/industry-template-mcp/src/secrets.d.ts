// Secret bindings set with `wrangler secret put`; `wrangler types` cannot see them.
// `env` from "cloudflare:workers" is typed as Cloudflare.Env; the global Env extends the same base.
declare namespace Cloudflare {
	interface Env {
		GITHUB_CLIENT_ID: string;
		GITHUB_CLIENT_SECRET: string;
		COOKIE_ENCRYPTION_KEY: string;
	}
}
interface Env {
	GITHUB_CLIENT_ID: string;
	GITHUB_CLIENT_SECRET: string;
	COOKIE_ENCRYPTION_KEY: string;
}
