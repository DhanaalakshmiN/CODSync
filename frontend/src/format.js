// Formatters: Rs with en-IN grouping, dates as in the design, relative times.
const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const int = new Intl.NumberFormat("en-IN");
const MONTHS = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];

export const MINUS = "−";
export const rs = (n, dec = true) => {
	if (n === null || n === undefined || n === "") return "—";
	const v = Number(n);
	const s = "₹" + (dec ? inr : inr0).format(Math.abs(v));
	return v < 0 ? MINUS + s : s;
};
// signed with plus, e.g. "+₹0.50"
export const rsSigned = (n) => (Number(n) > 0 ? "+" : "") + rs(n);
export const num = (n) => (n === null || n === undefined ? "—" : int.format(n));
export const kg = (n) => (n === null || n === undefined || n === "" ? "—" : `${Number(n)} kg`);

export function parse(d) {
	if (!d) return null;
	if (d instanceof Date) return d;
	return new Date(String(d).replace(" ", "T"));
}
export const dShort = (d) => {
	const x = parse(d);
	return x ? `${x.getDate()} ${MONTHS[x.getMonth()]}` : "—";
};
export const dFull = (d) => {
	const x = parse(d);
	return x ? `${x.getDate()} ${MONTHS[x.getMonth()]} ${x.getFullYear()}` : "—";
};
const hm = (x) =>
	`${String(x.getHours()).padStart(2, "0")}:${String(x.getMinutes()).padStart(2, "0")}`;
export const dTime = (d) => {
	const x = parse(d);
	return x ? `${dFull(x)}, ${hm(x)}` : "—";
};
export const dShortTime = (d) => {
	const x = parse(d);
	return x ? `${x.getDate()} ${MONTHS[x.getMonth()]}, ${hm(x)}` : "—";
};
export function ago(d) {
	const x = parse(d);
	if (!x) return "never";
	const s = Math.max(0, (Date.now() - x.getTime()) / 1000);
	if (s < 90) return "just now";
	if (s < 3600) return `${Math.round(s / 60)} min ago`;
	if (s < 86400) return `${Math.round(s / 3600)}h ago`;
	return `${Math.round(s / 86400)}d ago`;
}
export const initials = (name) =>
	(name || "")
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((w) => w[0])
		.join("")
		.toUpperCase();

// Badge kinds used across the design
export const deliveryKind = (s) =>
	({
		Delivered: "ok",
		"In transit": "info",
		"Out for delivery": "info",
		"Pickup scheduled": "info",
		"RTO initiated": "mis",
	}[s] || "");
export const codKind = (s) => ({ Settled: "ok", Collected: "info" }[s] || "");
export const reconKind = (s) =>
	({ Reconciled: "ok", Pending: "pend", Mismatch: "mis", Exception: "exc" }[s] || "");
export const excKind = (t) =>
	({
		"Unexpected deduction": "mis",
		"Amount mismatch": "mis",
		"Missing settlement": "exc",
		"Unknown AWB": "exc",
		"Tracking mismatch": "pend",
		"Missing AWB": "pend",
	}[t] || "");
export const batchKind = (s) =>
	({ Reconciled: "ok", Mismatch: "mis", "Pending review": "pend" }[s] || "");

// ISO date (YYYY-MM-DD) N days ago, for the Date chip presets
export const daysAgoIso = (n) => {
	const d = new Date();
	d.setDate(d.getDate() - n);
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
		d.getDate()
	).padStart(2, "0")}`;
};

// Save rows as a CSV file in the browser (Export buttons)
export function saveCsv(name, columns, rows) {
	const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
	const body = [
		columns.map((c) => esc(c.label)).join(","),
		...rows.map((r) => columns.map((c) => esc(r[c.key])).join(",")),
	].join("\n");
	const url = URL.createObjectURL(new Blob([body], { type: "text/csv" }));
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	a.click();
	URL.revokeObjectURL(url);
}
