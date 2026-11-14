import { render } from "@testing-library/react";
import { expect, test } from "vitest";

import { I18nProvider } from "./I18nProvider";

test("画面の言語に合わせて <html lang> を変える", () => {
  const { rerender } = render(
    <I18nProvider language="ja" setLanguage={() => {}}>
      <p>本文</p>
    </I18nProvider>,
  );
  expect(document.documentElement.lang).toBe("ja");

  rerender(
    <I18nProvider language="en" setLanguage={() => {}}>
      <p>body</p>
    </I18nProvider>,
  );
  expect(document.documentElement.lang).toBe("en");
});
