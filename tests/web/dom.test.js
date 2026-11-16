import { describe, expect, it } from "vitest";

import { banner, element } from "../../src/fdstoolkit/ui/static/dom.js";

describe("dom", () => {
  it("builds an element with the properties given", () => {
    // Arrange
    const properties = { className: "chip", textContent: "side 0" };

    // Act
    const node = element("span", properties);

    // Assert
    expect([node.tagName, node.className, node.textContent]).toEqual(["SPAN", "chip", "side 0"]);
  });

  it("builds a banner of the kind given", () => {
    // Arrange
    const message = "the disk reads back as written";

    // Act
    const node = banner("good", message);

    // Assert
    expect([node.className, node.textContent]).toEqual(["banner good", message]);
  });
});
