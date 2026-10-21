import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Production build lands in the app's public folder with fixed file names
// (served at /assets/codsync/frontend/app.js and app.css).
export default defineConfig(({ command }) => ({
	plugins: [vue()],
	base: command === "build" ? "/assets/codsync/frontend/" : "/",
	build: {
		outDir: "../codsync/public/frontend",
		emptyOutDir: true,
		cssCodeSplit: false,
		rollupOptions: {
			input: "src/main.js",
			output: {
				// One inlined bundle: dynamic chunks would import the unversioned
				// "./app.js" for shared symbols, and the dev server caches assets for
				// 12h — an old cached copy then boots a second app with a stale
				// router. Inlining keeps every load behind the versioned app.js?v=.
				inlineDynamicImports: true,
				entryFileNames: "app.js",
				assetFileNames: (info) =>
					(info.names?.[0] || info.name || "").endsWith(".css")
						? "app.css"
						: "assets/[name][extname]",
			},
		},
	},
	server: {
		// browse the dev server at http://codsync.localhost:5173 so the Frappe session cookie (set by
		// http://codsync.localhost:8000, cookies ignore ports) is sent to the proxy
		host: true,
		allowedHosts: ["codsync.localhost"],
		port: 5173,
		proxy: {
			// dev: /api goes to the bench site; log in at http://codsync.localhost:8000/login first, then open
			// http://codsync.localhost:5173/cod-ledger (the Host header makes the proxy hit the right site)
			"/api": {
				target: "http://localhost:8000",
				headers: { Host: "codsync.localhost" },
				changeOrigin: false,
			},
			"/files": { target: "http://localhost:8000", headers: { Host: "codsync.localhost" } },
			"/private": {
				target: "http://localhost:8000",
				headers: { Host: "codsync.localhost" },
			},
		},
	},
}));
