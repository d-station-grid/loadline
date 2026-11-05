import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { useEffect, useRef } from "react";

import { dayAt } from "../lib/charts";

// 使う種類だけを登録して、配る JS を小さくする。
echarts.use([
  BarChart,
  LineChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

type Props = {
  option: EChartsOption;
  height?: number;
  /** 描いてある範囲の中を押したとき、その位置の日（YYYY-MM-DD）を知らせる。
   * 横の軸が日付のチャートだけで使う */
  onDayClick?: (day: string) => void;
};

/** option を受け取って描くだけの部品。option の組み立ては lib/charts.ts でやる。 */
export default function Chart({ option, height = 280, onDayClick }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  // 押したときに呼ぶ関数は、描き直さずに差し替える
  const dayClick = useRef(onDayClick);
  useEffect(() => {
    dayClick.current = onDayClick;
  }, [onDayClick]);

  // 作るのと片づけるのは、画面に出たときと消えたときの 1 回ずつ。
  useEffect(() => {
    if (!ref.current) return;
    const instance = echarts.init(ref.current);
    chart.current = instance;
    const resize = () => instance.resize();
    window.addEventListener("resize", resize);
    // 線の点だけでなく、描いてある範囲のどこを押しても、その位置の日を拾う
    instance.getZr().on("click", (e) => {
      const day = dayAt(instance, [e.offsetX, e.offsetY]);
      if (day && dayClick.current) dayClick.current(day);
    });
    return () => {
      window.removeEventListener("resize", resize);
      instance.dispose();
      chart.current = null;
    };
  }, []);

  // 期間や種目を切り替えたら描き直す。notMerge で前の series を残さない。
  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return (
    <div
      ref={ref}
      style={{
        width: "100%",
        height,
        cursor: onDayClick ? "pointer" : undefined,
      }}
    />
  );
}
