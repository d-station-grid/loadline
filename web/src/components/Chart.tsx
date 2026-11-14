import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import langJA from "echarts/i18n/langJA-obj.js";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { useEffect, useRef } from "react";

import type { Language } from "../api";
import { useI18n } from "../i18n";
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

// 時間軸の目盛り（月の名前など）とツールチップの日付は、ECharts のロケールで書かれる。
// 英語は ECharts が持っている。日本語は登録する
echarts.registerLocale(
  "JA",
  langJA as Parameters<typeof echarts.registerLocale>[1],
);

/** 画面の言語に対応する ECharts のロケール */
const ECHARTS_LOCALES: Record<Language, string> = { en: "EN", ja: "JA" };

type Props = {
  option: EChartsOption;
  height?: number;
  /** 描いてある範囲の中を押したとき、その位置の日（YYYY-MM-DD）を知らせる。
   * 横の軸が日付のチャートだけで使う */
  onDayClick?: (day: string) => void;
};

/** option を受け取って描くだけの部品。option の組み立ては lib/charts.ts でやる。 */
export default function Chart({ option, height = 280, onDayClick }: Props) {
  const { language } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  // 押したときに呼ぶ関数は、描き直さずに差し替える
  const dayClick = useRef(onDayClick);
  useEffect(() => {
    dayClick.current = onDayClick;
  }, [onDayClick]);

  // 作り直したときに、そのときの option で描くため
  const latestOption = useRef(option);
  useEffect(() => {
    latestOption.current = option;
  }, [option]);

  // 作るのと片づけるのは、画面に出たときと消えたとき。ロケールは作るときにしか渡せないので、
  // 画面の言語が変わったら作り直す
  useEffect(() => {
    if (!ref.current) return;
    const instance = echarts.init(ref.current, undefined, {
      locale: ECHARTS_LOCALES[language],
    });
    chart.current = instance;
    instance.setOption(latestOption.current, { notMerge: true });
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
  }, [language]);

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
