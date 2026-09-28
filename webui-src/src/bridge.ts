// AstrBot 插件 Page 的 bridge 访问层（含 sandbox 环境的安全封装）。
//
// ⚠️ 关键环境约束：AstrBot 把插件页塞进 sandbox iframe：
//     <iframe sandbox="allow-scripts allow-forms allow-downloads">
//                                        ^ 没有 allow-same-origin
// 因此 localStorage / sessionStorage / document.cookie 一旦被访问就抛 SecurityError，
// 若这次访问发生在 Vue setup / mount 阶段，整个页面直接白屏。
// 参见 AstrBot 源码 dashboard/src/views/PluginPagePage.vue 的 iframe 属性。
//
// 本插件约定两条：
//   1) 任何持久化都走 storageGet/storageSet（内部 try/catch + 内存兜底）；
//   2) 主题这类环境信息优先读 bridge 的 context（isDark），它由 AstrBot 面板下发。

export interface BridgeContext {
  pluginName?: string;
  displayName?: string;
  pageName?: string;
  pageTitle?: string;
  locale?: string;
  isDark?: boolean;
}

export interface AstrBotPageBridge {
  getContext?(): BridgeContext | null;
  onContext?(handler: (ctx: BridgeContext) => void): () => void;
  apiGet(endpoint: string, params?: Record<string, any>): Promise<any>;
  apiPost(endpoint: string, body?: Record<string, any>): Promise<any>;
}

/** 取 iframe 内的 bridge 实例（由官方 bridge-sdk 注入到 window 上）。 */
export function getBridge(): AstrBotPageBridge | null {
  const w = window as any;
  if (w.AstrBotPluginPage) return w.AstrBotPluginPage as AstrBotPageBridge;
  // 极少数宿主把页面直接内联在主文档里；sandbox iframe 里访问 window.parent 会抛
  // SecurityError，必须捕获。
  try {
    if (w.parent && w.parent !== w && w.parent.AstrBotPluginPage) {
      return w.parent.AstrBotPluginPage as AstrBotPageBridge;
    }
  } catch {
    return null;
  }
  return null;
}

function isUsable(b: AstrBotPageBridge | null | undefined): b is AstrBotPageBridge {
  return Boolean(b && typeof b.apiGet === "function" && typeof b.apiPost === "function");
}

let _ready: Promise<AstrBotPageBridge> | null = null;

/**
 * 等桥接可用再放行（页面刚加载时 bridge 脚本可能尚未执行完）。
 * 结果用模块级 Promise 缓存：整个会话只握手一次；失败允许下次重建。
 */
export function whenBridgeReady(timeoutMs = 4000): Promise<AstrBotPageBridge> {
  if (_ready) return _ready;
  _ready = (async () => {
    const start = Date.now();
    while (true) {
      const b = getBridge();
      if (isUsable(b)) return b;
      if (Date.now() - start > timeoutMs) {
        throw new Error(
          "未检测到 AstrBot 插件 Page 桥接：请从 AstrBot 后台的「插件页」打开本控制台"
        );
      }
      await new Promise((r) => setTimeout(r, 100));
    }
  })().catch((e) => {
    _ready = null;
    throw e;
  });
  return _ready;
}

/** 当前面板下发的 context（可能为 null：bridge 未就绪或页面被独立打开）。 */
export function getContext(): BridgeContext | null {
  try {
    return getBridge()?.getContext?.() || null;
  } catch {
    return null;
  }
}

/** 订阅 context 变化（主题切换等）；已存在 context 时官方实现会立即回调一次。 */
export function onContext(handler: (ctx: BridgeContext) => void): () => void {
  try {
    const off = getBridge()?.onContext?.(handler);
    return typeof off === "function" ? off : () => {};
  } catch {
    return () => {};
  }
}

// ------------------------------------------------------------------ //
// sandbox 安全存储（不可用时退回内存，绝不抛异常）
// ------------------------------------------------------------------ //
const memory = new Map<string, string>();
let lsUsable: boolean | null = null;

function localStorageUsable(): boolean {
  if (lsUsable === null) {
    try {
      window.localStorage.getItem("__probe__");
      lsUsable = true;
    } catch {
      lsUsable = false;
    }
  }
  return lsUsable;
}

export function storageGet(key: string): string | null {
  if (localStorageUsable()) {
    try {
      const v = window.localStorage.getItem(key);
      if (v !== null) return v;
    } catch {
      /* 落到内存 */
    }
  }
  return memory.has(key) ? (memory.get(key) as string) : null;
}

export function storageSet(key: string, value: string): void {
  memory.set(key, value);
  if (!localStorageUsable()) return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* 忽略：内存里已经有了 */
  }
}
