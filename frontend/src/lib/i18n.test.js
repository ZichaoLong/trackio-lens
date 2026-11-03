import { describe, expect, it } from "vitest";
import { get } from "svelte/store";
import { locale, setLocale, t, translate } from "./i18n.js";

describe("interface language", () => {
  it("switches reactively and preserves unknown text and parameter values", () => {
    setLocale("zh-CN");
    expect(get(t)("Settings")).toBe("设置");
    expect(get(t)("Read {y} by {x}", {y: "train/loss", x: "step"})).toBe("按 step 读取 train/loss");
    expect(get(t)("custom-metric/训练损失")).toBe("custom-metric/训练损失");
    setLocale("invalid");
    expect(get(locale)).toBe("zh-CN");
    setLocale("en");
    expect(get(t)("Settings")).toBe("Settings");
    expect(translate("en", "Read {y} by {x}", {y: "loss", x: "step"})).toBe("Read loss by step");
  });
});
