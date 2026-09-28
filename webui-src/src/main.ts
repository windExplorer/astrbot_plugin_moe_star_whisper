import { createApp } from "vue";
import { createRouter, createWebHashHistory } from "vue-router";
import App from "./App.vue";

// hash 路由：AstrBot 按真实文件路径提供静态资源，history 模式刷新会 404。
// 视图同步 import（构建产物单文件，无需懒加载）。
import OverviewView from "./views/OverviewView.vue";
import RecordsView from "./views/RecordsView.vue";
import StatsView from "./views/StatsView.vue";
import UserView from "./views/UserView.vue";
import ConfigView from "./views/ConfigView.vue";
import DebugView from "./views/DebugView.vue";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/overview" },
    { path: "/overview", name: "overview", component: OverviewView },
    { path: "/records", name: "records", component: RecordsView },
    { path: "/stats", name: "stats", component: StatsView },
    { path: "/user", name: "user", component: UserView },
    { path: "/config", name: "config", component: ConfigView },
    { path: "/debug", name: "debug", component: DebugView },
    { path: "/:pathMatch(.*)*", redirect: "/overview" },
  ],
});

createApp(App).use(router).mount("#app");
