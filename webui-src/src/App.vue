<template>
  <n-config-provider
    :theme="isDark ? darkTheme : null"
    :theme-overrides="overrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <n-message-provider>
      <n-dialog-provider>
        <div class="shell">
          <header class="topbar">
            <div class="brand">
              <span class="logo">🌙</span>
              <div class="titles">
                <b>萌萌星语 · 控制台</b>
                <span class="sub">每日运势签的数据与配置面板</span>
              </div>
            </div>
            <div class="tools">
              <n-tag size="small" :bordered="false" :type="connType">{{ connText }}</n-tag>
              <n-tag size="small" :bordered="false">v{{ version }}</n-tag>
              <n-button size="small" quaternary @click="refreshAll">刷新</n-button>
              <n-button size="small" quaternary @click="toggleTheme">
                {{ isDark ? "🌞 亮色" : "🌙 暗色" }}
              </n-button>
            </div>
          </header>

          <div class="body">
            <aside class="sider" v-if="!isMobile">
              <n-menu
                :value="activeKey"
                :options="menuOptions"
                :indent="18"
                @update:value="go"
              />
            </aside>

            <n-drawer v-model:show="drawerOpen" :width="228" placement="left">
              <n-drawer-content title="导航" :native-scrollbar="false">
                <n-menu
                  :value="activeKey"
                  :options="menuOptions"
                  :indent="18"
                  @update:value="go"
                />
              </n-drawer-content>
            </n-drawer>

            <main class="content">
              <div class="mobile-bar" v-if="isMobile">
                <n-button size="small" @click="drawerOpen = true">☰ 导航</n-button>
                <span class="sub">{{ currentTitle }}</span>
              </div>
              <router-view :key="refreshKey" />
            </main>
          </div>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import {
  NButton,
  NConfigProvider,
  NDialogProvider,
  NDrawer,
  NDrawerContent,
  NMenu,
  NMessageProvider,
  NTag,
  darkTheme,
  dateZhCN,
  zhCN,
} from "naive-ui";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { apiGet, type Overview } from "./api";
import { PLUGIN_VERSION } from "./version";
import { getContext, onContext, storageGet, storageSet } from "./bridge";
import { backendVersion, connState, connError, isDark, setConn } from "./store";

const route = useRoute();
const router = useRouter();

const drawerOpen = ref(false);
const refreshKey = ref(0);
const isMobile = ref(false);

const MENU = [
  { key: "/overview", label: "📊 总览" },
  { key: "/records", label: "🗂 抽签记录" },
  { key: "/stats", label: "📈 数据统计" },
  { key: "/user", label: "🙋 用户查询" },
  { key: "/config", label: "⚙️ 参数配置" },
  { key: "/debug", label: "🧪 调试工具" },
];

const menuOptions = MENU.map((m) => ({ label: m.label, key: m.key }));
const activeKey = computed(() => route.path);
const currentTitle = computed(() => MENU.find((m) => m.key === route.path)?.label || "");
const version = computed(() => backendVersion.value || PLUGIN_VERSION || "dev");

const connType = computed(() =>
  connState.value === "ok" ? "success" : connState.value === "error" ? "error" : "default"
);
const connText = computed(() =>
  connState.value === "ok" ? "已连接" : connState.value === "error" ? "未连接" : "连接中…"
);

const overrides = {
  common: {
    primaryColor: "#E86A8A",
    primaryColorHover: "#F08AA4",
    primaryColorPressed: "#D25577",
    borderRadius: "10px",
  },
};

function go(key: string) {
  drawerOpen.value = false;
  if (key !== route.path) router.push(key);
}

function refreshAll() {
  refreshKey.value += 1;
  ping();
}

// ---------------- 主题 ----------------
function initTheme() {
  const saved = storageGet("msw.theme");
  if (saved === "dark") isDark.value = true;
  else if (saved === "light") isDark.value = false;
  else {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === "dark") isDark.value = true;
    else if (attr === "light") isDark.value = false;
    else isDark.value = Boolean(getContext()?.isDark);
  }
}

function toggleTheme() {
  isDark.value = !isDark.value;
  storageSet("msw.theme", isDark.value ? "dark" : "light");
}

// ---------------- 后端握手 ----------------
async function ping() {
  try {
    const data = await apiGet<Overview>("overview", { days: 3 });
    backendVersion.value = data?.version || "";
    setConn(true);
  } catch (e: any) {
    setConn(false, e?.message || String(e));
  }
}

let media: MediaQueryList | null = null;
function onResize(e: MediaQueryListEvent | MediaQueryList) {
  isMobile.value = e.matches;
}

onMounted(() => {
  initTheme();
  ping();
  media = window.matchMedia("(max-width: 820px)");
  onResize(media);
  media.addEventListener("change", onResize);
  onContext((ctx) => {
    if (!storageGet("msw.theme") && typeof ctx?.isDark === "boolean") {
      isDark.value = ctx.isDark;
    }
  });
});

onBeforeUnmount(() => {
  media?.removeEventListener("change", onResize);
});

watch(isDark, (v) => {
  document.documentElement.classList.toggle("msw-dark", v);
});
</script>

<style>
:root {
  --msw-bg: linear-gradient(180deg, #faf6f4, #f4f2fa);
  --msw-panel: #ffffff;
  --msw-line: #eeecf2;
  --msw-text: #4a4a60;
  --msw-sub: #9696a8;
  --msw-accent: #e86a8a;
}
html.msw-dark,
html[data-theme="dark"] {
  --msw-bg: linear-gradient(180deg, #1c1a26, #201d2c);
  --msw-panel: #262336;
  --msw-line: #35314a;
  --msw-text: #e8e4f2;
  --msw-sub: #a49fb8;
  --msw-accent: #f08aa4;
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  background: var(--msw-bg);
  color: var(--msw-text);
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  min-height: 100vh;
}
</style>

<style scoped>
.shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  background: var(--msw-panel);
  border-bottom: 1px solid var(--msw-line);
  position: sticky;
  top: 0;
  z-index: 5;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.logo {
  font-size: 24px;
  line-height: 1;
}
.titles {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.titles b {
  font-size: 16px;
}
.sub {
  color: var(--msw-sub);
  font-size: 12px;
}
.tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.sider {
  width: 186px;
  flex: 0 0 186px;
  border-right: 1px solid var(--msw-line);
  background: var(--msw-panel);
  padding-top: 10px;
}
.content {
  flex: 1;
  min-width: 0;
  padding: 16px 18px 40px;
}
.mobile-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
@media (max-width: 820px) {
  .content {
    padding: 12px 12px 32px;
  }
}
</style>
