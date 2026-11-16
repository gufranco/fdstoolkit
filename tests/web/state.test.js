import { afterEach, describe, expect, it } from "vitest";

import { label, state, t, update } from "../../src/fdstoolkit/ui/static/state.js";

describe("state", () => {
  afterEach(() => {
    update({ language: "en" });
  });

  it("translates a key in the language chosen", () => {
    // Arrange
    update({ language: "ja" });

    // Act
    const text = t("confirm.cancel");

    // Assert
    expect([state.language, text]).toEqual(["ja", "キャンセル"]);
  });

  it("falls back to English for a language it does not carry", () => {
    // Arrange
    update({ language: "xx" });

    // Act
    const text = t("confirm.cancel");

    // Assert
    expect(text).toBe("Cancel");
  });

  it("offers the fallback when a key has no translation", () => {
    // Arrange
    const fallback = "Not translated.";

    // Act
    const text = label("summary.nothing-like-this", fallback);

    // Assert
    expect(text).toBe(fallback);
  });
});
