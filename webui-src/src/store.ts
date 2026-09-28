// 极简全局状态（不引 pinia：页面只有主题/版本/连接态三个跨页共享量）。
import { ref } from "vue";

/** 暗色主题（图表配色需要它，故放全局）。 */
export const isDark = ref(false);

/** 后端返回的插件版本（metadata.yaml，唯一版本来源）。 */
export const backendVersion = ref("");

/** 与后端的握手状态：idle 未尝试 / ok 正常 / error 失败。 */
export const connState = ref<"idle" | "ok" | "error">("idle");
export const connError = ref("");

export function setConn(ok: boolean, message = "") {
  connState.value = ok ? "ok" : "error";
  connError.value = ok ? "" : message;
}
