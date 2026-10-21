import { createRouter, createWebHistory } from "vue-router";

// meta.pg is the page class (pg-<name>) the design CSS is scoped with; meta.nav highlights the sidebar item
const page = (name, path, comp, nav, extra = {}) => ({
	name,
	path,
	component: comp,
	meta: { pg: extra.pg || name, nav, title: extra.title || name },
});

export default createRouter({
	history: createWebHistory("/cod-ledger"),
	routes: [
		page("overview", "/", () => import("./pages/Overview.vue"), "overview"),
		page("orders", "/orders", () => import("./pages/Orders.vue"), "orders"),
		page("detail", "/orders/:id", () => import("./pages/OrderDetail.vue"), "orders"),
		page("shipments", "/shipments", () => import("./pages/Shipments.vue"), "shipments"),
		page(
			"recon",
			"/reconciliation",
			() => import("./pages/Reconciliation.vue"),
			"reconciliation"
		),
		page(
			"settlements",
			"/settlements",
			() => import("./pages/Settlements.vue"),
			"settlements"
		),
		page(
			"settlement-import",
			"/settlements/import",
			() => import("./pages/SettlementImport.vue"),
			"settlements",
			{ pg: "settlements" }
		),
		page(
			"settlement",
			"/settlements/:batch",
			() => import("./pages/SettlementDetail.vue"),
			"settlements",
			{ pg: "settlements" }
		),
		page("exceptions", "/exceptions", () => import("./pages/Exceptions.vue"), "exceptions"),
		page("couriers", "/couriers", () => import("./pages/Couriers.vue"), "couriers"),
		page("reports", "/reports", () => import("./pages/Reports.vue"), "reports"),
		page("settings", "/settings", () => import("./pages/Settings.vue"), "settings"),
		{ path: "/:rest(.*)*", redirect: "/" },
	],
	scrollBehavior: () => ({ top: 0 }),
});
