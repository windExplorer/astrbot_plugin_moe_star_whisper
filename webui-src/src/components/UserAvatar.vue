<template>
  <img
    v-if="!failed && url"
    class="avatar"
    :src="url"
    :style="boxStyle"
    :alt="name || uid"
    loading="lazy"
    referrerpolicy="no-referrer"
    @error="failed = true"
  />
  <span v-else class="avatar fallback" :style="[boxStyle, { background: color }]">{{ initial }}</span>
</template>

<script setup lang="ts">
// 头像：优先用 fortunes 里存的头像 URL 快照，缺失时按 QQ 号拼 qlogo 接口；
// 加载失败（非 QQ 平台 / 图片 404）退回首字母色块，绝不留白框。
import { computed, ref, watch } from "vue";

const props = withDefaults(
  defineProps<{ uid?: string; src?: string; name?: string; size?: number }>(),
  { uid: "", src: "", name: "", size: 40 }
);

const failed = ref(false);
watch(
  () => [props.src, props.uid],
  () => {
    failed.value = false;
  }
);

const url = computed(() => {
  if (props.src) return props.src;
  const uid = String(props.uid || "").trim();
  return /^\d{5,12}$/.test(uid) ? `https://q4.qlogo.cn/headimg_dl?dst_uin=${uid}&spec=100` : "";
});

const boxStyle = computed(() => ({
  width: props.size + "px",
  height: props.size + "px",
  borderRadius: "50%",
  flex: "0 0 auto",
}));

const initial = computed(() => {
  const n = String(props.name || props.uid || "?").trim();
  return n ? n.slice(0, 1).toUpperCase() : "?";
});

const color = computed(() => {
  const s = String(props.uid || props.name || "x");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return `hsl(${h}, 52%, 62%)`;
});
</script>

<style scoped>
.avatar {
  display: block;
  object-fit: cover;
  background: rgba(120, 100, 140, 0.12);
}
.fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
</style>
