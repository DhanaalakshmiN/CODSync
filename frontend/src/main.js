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

createApp(App).use(router).mount("#app");
