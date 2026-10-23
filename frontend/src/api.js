import { toast } from "./store";

const METHOD = "/api/method/";
const UI = "codsync.codsync.ui_api.";

// CSRF token: injected by www/cod-ledger.html in production; in dev (or after it goes stale) it is
// fetched from the logged-in session via ui_api.csrf_token. Never sent empty.
let token = (window.CODSYNC && window.CODSYNC.csrf_token) || "";
let pending = null;

async function fetchToken() {
	const res = await fetch(METHOD + UI + "csrf_token", {
		credentials: "same-origin",
		headers: { Accept: "application/json" },
	});
	if (res.status === 401 || res.status === 403) throw sessionExpired();
	if (!res.ok) throw new Error(await errorText(res));
	token = (await res.json()).message;
	return token;
}
function refreshToken() {
	pending = pending || fetchToken().finally(() => (pending = null));
	return pending;
}
async function csrf() {
	return token || refreshToken();
}

// Inside Shopify admin cookies are unavailable: every request carries the App Bridge session token.
export const embedded = () => !!(window.CODSYNC && window.CODSYNC.embedded);
const SESSION_HEADER = "X-Shopify-Session-Token";
async function sessionToken() {
	if (!window.shopify || !window.shopify.idToken) throw new Error("Open CODSync from Shopify admin");
	return window.shopify.idToken();
}

let redirecting = false;
function sessionExpired() {
	if (!redirecting) {
		redirecting = true;
		toast("Your session expired. Redirecting to login...", "e");
		const dev = window.CODSYNC && window.CODSYNC.dev;
		const back = encodeURIComponent(location.pathname + location.search);
		setTimeout(
			() =>
				(location.href = `${
					dev ? "http://codsync.localhost:8000" : ""
				}/login?redirect-to=${back}`),
			800
		);
	}
	const err = new Error("Session expired");
	err.status = 401;
	err.sessionExpired = true;
	return err;
}

// fetch with the session cookie and a valid CSRF token; one retry with a fresh token on CSRFTokenError
async function send(url, makeInit) {
	if (embedded()) {
		const init = makeInit();
		init.headers = { ...init.headers, [SESSION_HEADER]: await sessionToken() };
		return fetch(url, init);
	}
	for (let attempt = 0; ; attempt++) {
		const init = makeInit();
		init.credentials = "same-origin";
		init.headers = { ...init.headers, "X-Frappe-CSRF-Token": await csrf() };
		const res = await fetch(url, init);
		if (res.ok) return res;
		const body = await res.clone().text();
		if (res.status === 400 && /CSRFTokenError|Invalid Request/.test(body) && attempt === 0) {
			token = "";
			await refreshToken();
			continue;
		}
		if (res.status === 401 || res.status === 403) {
			// a 403 can be a permission error, so only treat it as expiry when the session is really gone
			try {
				token = "";
				await refreshToken();
			} catch (e) {
				if (e.sessionExpired) throw e;
			}
		}
		return res;
	}
}

// Frappe reports errors in _server_messages (JSON list of JSON strings) or exception text.
async function errorText(res) {
	try {
		const body = await res.json();
		if (body._server_messages) {
			const msgs = JSON.parse(body._server_messages).map((m) => JSON.parse(m).message);
			return msgs.join(" ").replace(/<[^>]+>/g, "");
		}
		if (/PermissionError/.test(body.exception || ""))
			return "You do not have permission to do this.";
		if (body.exception)
			return String(body.exception).split(":").slice(1).join(":").trim() || body.exception;
	} catch (e) {
		/* fall through */
	}
	return `Request failed (${res.status})`;
}

export async function call(fn, args = {}, { silent = false, method = null } = {}) {
	const path = fn.includes(".") ? fn : UI + fn;
	const res = await send(METHOD + path, () => ({
		method: "POST",
		headers: { "Content-Type": "application/json", Accept: "application/json" },
		body: JSON.stringify(args),
	}));
	if (!res.ok) {
		const msg = await errorText(res);
		if (!silent) toast(msg, "e");
		const err = new Error(msg);
		err.status = res.status;
		throw err;
	}
	return (await res.json()).message;
}

// First open inside Shopify: connects the shop (token exchange, user, webhooks). Idempotent.
export const connectShop = () => call("codsync.shopify_auth.connect", {}, { silent: true });

// api.orders({tab: "COD"}) -> POST /api/method/codsync.codsync.ui_api.orders
export const api = new Proxy({}, { get: (_, fn) => (args, opts) => call(fn, args, opts) });

export async function upload(file) {
	const fd = new FormData();
	fd.append("file", file, file.name);
	fd.append("is_private", "1");
	fd.append("folder", "Home");
	const res = await send(METHOD + "upload_file", () => ({
		method: "POST",
		headers: { Accept: "application/json" },
		body: fd,
	}));
	if (!res.ok) {
		const msg = await errorText(res);
		toast(msg, "e");
		throw new Error(msg);
	}
	return (await res.json()).message; // { file_url, file_name, ... }
}

// Endpoints that answer with a file (report_download): fetch as blob and save.
export async function download(fn, args = {}) {
	const res = await send(METHOD + UI + fn, () => ({
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(args),
	}));
	if (!res.ok) {
		const msg = await errorText(res);
		toast(msg, "e");
		throw new Error(msg);
	}
	const cd = res.headers.get("Content-Disposition") || "";
	const name =
		(cd.match(/filename="?([^";]+)"?/) || [])[1] ||
		`${args.key || "report"}.${args.fmt || "xlsx"}`;
	const url = URL.createObjectURL(await res.blob());
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	a.style.display = "none";
	document.body.appendChild(a); // Firefox ignores clicks on detached links
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 1000); // revoking at once can cancel the save
}

// Report CSV: plain GET navigation, the browser saves the attachment itself (no fetch/blob to block).
export async function downloadReportCsv(name, filters) {
	const q = new URLSearchParams({ name, filters: JSON.stringify(filters) });
	const url = `${METHOD}${UI}report_csv?${q}`;
	if (!embedded()) return window.location.assign(url);
	// embedded: a plain navigation cannot carry the session token, so fetch it and save the blob
	const res = await fetch(url, { headers: { [SESSION_HEADER]: await sessionToken() } });
	if (!res.ok) {
		const msg = await errorText(res);
		toast(msg, "e");
		throw new Error(msg);
	}
	const a = document.createElement("a");
	a.href = URL.createObjectURL(await res.blob());
	a.download = `${name}.csv`;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
