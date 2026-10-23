import { createApp } from "vue";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles/cod_ledger.css";
import "./styles/extras.css";
import App from "./App.vue";
import router from "./router";
import { connectShop, embedded } from "./api";

const mount = () => createApp(App).use(router).mount("#app");

if (embedded()) {
	// Inside Shopify: connect the shop first, then show the app
	connectShop().then(mount, (e) => {
		document.getElementById("app").innerHTML =
			'<p style="font-family:sans-serif;padding:24px">Could not connect to Shopify: ' +
			String(e.message || e).replace(/</g, "&lt;") +
			"</p>";
	});
} else {
	mount();
}
