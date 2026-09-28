import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import cssInjectedByJs from "vite-plugin-css-injected-by-js";
import { fileURLToPath, URL } from "node:url";

// AstrBot 插件页面的构建约束（在 user_gateway 上踩实，勿改）：
//  1) base 必须是 './'：AstrBot 会重写页面内的相对资源引用并追加 asset_token；
//  2) 单文件产物（inlineDynamicImports）：跨 chunk 的 import 会被 token 重写搞成 401 白屏；
//  3) cssCodeSplit=false + cssInjectedByJs：只加载一个 js，样式内联进去；
//  4) hash 路由：AstrBot 按真实文件路径提供静态资源，history 模式刷新会 404；
//  5) assetsInlineLimit=300KB：运行时才注入的图片拿不到 token 重写，必须内联成 data URI。
export default defineConfig({
  plugins: [vue(), cssInjectedByJs()],
  base: "./",
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "../pages/console",
    emptyOutDir: true,
    chunkSizeWarningLimit: 6000,
    cssCodeSplit: false,
    assetsInlineLimit: 300 * 1024,
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
  server: {
    port: 5176,
  },
});
