import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Standalone prototype: the real UI with demo/api.js instead of the Frappe backend.
// `npm run build:demo` then `node demo/inline.mjs` writes one self-contained HTML file.
const here = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
	plugins: [vue()],
	base: "./",
	define: { "import.meta.env.VITE_DEMO": "true" },
	resolve: { alias: [{ find: /^(\.\.?)\/api$/, replacement: path.join(here, "demo/api.js") }] },
	build: {
		outDir: "demo/dist",
		emptyOutDir: true,
		cssCodeSplit: false,
		assetsInlineLimit: 0,
		rollupOptions: {
			input: "src/main.js",
			output: {
				inlineDynamicImports: true,
				entryFileNames: "app.js",
				assetFileNames: (i) => ((i.names?.[0] || "").endsWith(".css") ? "app.css" : "assets/[name][extname]"),
			},
		},
	},
});
