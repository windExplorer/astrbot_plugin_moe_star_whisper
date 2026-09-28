<template>
  <div ref="el" class="echart" :style="{ height: height }"></div>
</template>

<script setup lang="ts">
// ECharts 封装：按需引入（只注册用到的图表与组件），ResizeObserver 自动重绘，
// 卸载时 dispose 防内存泄漏。
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart, RadarChart } from "echarts/charts";
import {
  DataZoomComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  PolarComponent,
  RadarComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  RadarChart,
  DataZoomComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  PolarComponent,
  RadarComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const props = withDefaults(
  defineProps<{ option: Record<string, any>; height?: string; loading?: boolean }>(),
  { height: "260px", loading: false }
);

const el = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;
let observer: ResizeObserver | null = null;

function render() {
  if (!el.value) return;
  if (!chart) {
    chart = echarts.init(el.value, undefined, { renderer: "canvas" });
  }
  chart.setOption(props.option || {}, true);
  if (props.loading) chart.showLoading();
  else chart.hideLoading();
}

onMounted(() => {
  render();
  if (typeof ResizeObserver !== "undefined" && el.value) {
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(el.value);
  }
});

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
  chart?.dispose();
  chart = null;
});

watch(() => props.option, render, { deep: true });
watch(() => props.loading, render);

defineExpose({ resize: () => chart?.resize() });
</script>

<style scoped>
.echart {
  width: 100%;
}
</style>
