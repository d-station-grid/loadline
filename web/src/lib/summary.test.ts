import { expect, test } from "vitest";

import type { Form } from "../api";
import {
  FORM_LABEL,
  formatChange,
  formatHours,
  formatLoad,
  formatOneDecimal,
  rangeOf,
  RANGES,
} from "./summary";

test("期間は 1W・1M・3M・6M で、1、4、13、26 週", () => {
  expect(RANGES.map((r) => [r.label, r.weeks])).toEqual([
    ["1W", 1],
    ["1M", 4],
    ["3M", 13],
    ["6M", 26],
  ]);
  expect(rangeOf("3m").span).toBe("3 months");
});

test("小数 1 桁で、0 に近い負の値を -0.0 と出さない", () => {
  expect(formatOneDecimal(54.64)).toBe("54.6");
  expect(formatOneDecimal(-0.04)).toBe("0.0");
});

test("差は増えたら + を付け、丸めて 0 なら符号を付けない", () => {
  expect(formatChange(5)).toBe("+5.0");
  expect(formatChange(-1.24)).toBe("-1.2");
  expect(formatChange(0.04)).toBe("0.0");
  expect(formatChange(-0.04)).toBe("0.0");
  expect(formatChange(0)).toBe("0.0");
});

test("Form の一言は 4 つの区分すべてにある", () => {
  const forms: Form[] = ["fatigued", "fresh", "steady", "not_enough_data"];

  expect(forms.map((f) => FORM_LABEL[f])).toEqual([
    "Tired — ease off",
    "Fresh — fatigue has cleared",
    "Balanced",
    "Not enough data to judge",
  ]);
});

test("時間は時間の小数 1 桁、負荷は整数に桁区切り、分からない負荷は –", () => {
  expect(formatHours(275400)).toBe("76.5");
  expect(formatHours(0)).toBe("0.0");
  expect(formatLoad(6224.6)).toBe("6,225");
  expect(formatLoad(0)).toBe("0");
  expect(formatLoad(null)).toBe("–");
});
