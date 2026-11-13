import { describe, expect, it } from "vitest";

import {
  bytes,
  describeLimits,
  explain,
  helpFor,
  isDownload,
  named,
  orderFamilies,
  scalar,
  typed,
  words
} from "../../src/fdstoolkit/ui/static/app.js";

describe("named", () => {
  it("keeps the chosen name when it already carries the wanted suffix", () => {
    // Arrange
    const expected = "demo.fds";

    // Act
    const result = named("demo.fds", "disk.fds");

    // Assert
    expect(result).toBe(expected);
  });

  it("swaps a suffix the command does not produce", () => {
    // Arrange
    const expected = "recipe.fds";

    // Act
    const result = named("recipe.json", "disk.fds");

    // Assert
    expect(result).toBe(expected);
  });

  it("adds the suffix when the chosen name carries none", () => {
    // Arrange
    const expected = "dump.fds";

    // Act
    const result = named("dump", "disk.fds");

    // Assert
    expect(result).toBe(expected);
  });

  it("falls back to the schema default when nothing was chosen", () => {
    // Arrange
    const expected = "disk.fds";

    // Act
    const result = named("", "disk.fds");

    // Assert
    expect(result).toBe(expected);
  });

  it("keeps the chosen name when the default carries no suffix", () => {
    // Arrange
    const expected = "demo.fds";

    // Act
    const result = named("demo.fds", "");

    // Assert
    expect(result).toBe(expected);
  });
});

describe("bytes", () => {
  it("reports small sizes in bytes", () => {
    // Arrange
    const expected = "512 B";

    // Act
    const result = bytes(512);

    // Assert
    expect(result).toBe(expected);
  });

  it("reports a two-side image in kibibytes", () => {
    // Arrange
    const expected = "127.9 KiB";

    // Act
    const result = bytes(131000);

    // Assert
    expect(result).toBe(expected);
  });
});

describe("scalar", () => {
  it("names an absent value rather than printing null", () => {
    // Arrange
    const expected = "none";

    // Act
    const result = scalar(null);

    // Assert
    expect(result).toBe(expected);
    expect(scalar(undefined)).toBe("none");
  });

  it("spells booleans out", () => {
    // Arrange
    const expected = "yes";

    // Act
    const result = scalar(true);

    // Assert
    expect(result).toBe(expected);
    expect(scalar(false)).toBe("no");
  });

  it("passes numbers and text through", () => {
    // Arrange
    const expected = "0";

    // Act
    const result = scalar(0);

    // Assert
    expect(result).toBe(expected);
    expect(scalar("clean")).toBe("clean");
  });
});

describe("words", () => {
  it("turns a field name into something readable", () => {
    // Arrange
    const expected = "bad blocks";

    // Act
    const result = words("bad_blocks");

    // Assert
    expect(result).toBe(expected);
  });
});

describe("isDownload", () => {
  it("accepts an entry carrying bytes, a size and a name", () => {
    // Arrange
    const expected = true;

    // Act
    const result = isDownload({ data: "AA==", size: 1, name: "a.fds" });

    // Assert
    expect(result).toBe(expected);
  });

  it("refuses a list of disk files, which carry no bytes", () => {
    // Arrange
    const expected = false;

    // Act
    const result = isDownload({ name: "GAME", size: 4096 });

    // Assert
    expect(result).toBe(expected);
  });

  it("refuses nothing at all", () => {
    // Arrange
    const expected = false;

    // Act
    const result = isDownload(null);

    // Assert
    expect(result).toBe(expected);
  });
});

describe("explain", () => {
  it("passes a plain message through", () => {
    // Arrange
    const expected = "that image is not a disk";

    // Act
    const result = explain("that image is not a disk");

    // Assert
    expect(result).toBe(expected);
  });

  it("names the field a validation error came from", () => {
    // Arrange
    const expected = "bad blocks: Input should be greater than 0";

    // Act
    const detail = [{ loc: ["body", "bad_blocks"], msg: "Input should be greater than 0" }];

    // Assert
    expect(explain(detail)).toBe(expected);
  });

  it("joins several validation errors", () => {
    // Arrange
    const expected = "sides: too big. passes: too small";

    // Act
    const detail = [
      { loc: ["body", "sides"], msg: "too big" },
      { loc: ["body", "passes"], msg: "too small" }
    ];

    // Assert
    expect(explain(detail)).toBe(expected);
  });

  it("keeps a message that names no field", () => {
    // Arrange
    const expected = "unreadable";

    // Act
    const result = explain([{ msg: "unreadable" }]);

    // Assert
    expect(result).toBe(expected);
  });

  it("falls back to the raw object when the shape is unknown", () => {
    // Arrange
    const expected = '{"odd":true}';

    // Act
    const result = explain({ odd: true });

    // Assert
    expect(result).toBe(expected);
  });
});

describe("describeLimits", () => {
  it("states a range when both ends are known", () => {
    // Arrange
    const expected = "Between 1 and 8.";

    // Act
    const result = describeLimits({ minimum: 1, maximum: 8 });

    // Assert
    expect(result).toBe(expected);
  });

  it("states a floor alone", () => {
    // Arrange
    const expected = "0 or more.";

    // Act
    const result = describeLimits({ minimum: 0, maximum: null });

    // Assert
    expect(result).toBe(expected);
  });

  it("states a ceiling alone", () => {
    // Arrange
    const expected = "65535 or less.";

    // Act
    const result = describeLimits({ minimum: null, maximum: 65535 });

    // Assert
    expect(result).toBe(expected);
  });

  it("states an exact length when both lengths agree", () => {
    // Arrange
    const expected = "Exactly 3 characters.";

    // Act
    const result = describeLimits({ min_length: 3, max_length: 3 });

    // Assert
    expect(result).toBe(expected);
  });

  it("states a maximum length", () => {
    // Arrange
    const expected = "Up to 8 characters.";

    // Act
    const result = describeLimits({ max_length: 8 });

    // Assert
    expect(result).toBe(expected);
  });

  it("says nothing when the field is unbounded", () => {
    // Arrange
    const expected = "";

    // Act
    const result = describeLimits({});

    // Assert
    expect(result).toBe(expected);
  });
});

describe("typed", () => {
  it("sends a choice on a whole-number field as a number", () => {
    // Arrange
    const expected = 2;

    // Act
    const result = typed("choice", "2", true);

    // Assert
    expect(result).toBe(expected);
  });

  it("keeps a choice on a text field as text", () => {
    // Arrange
    const expected = "release";

    // Act
    const result = typed("choice", "release", false);

    // Assert
    expect(result).toBe(expected);
  });

  it("sends a number field as a number", () => {
    // Arrange
    const expected = 3;

    // Act
    const result = typed("number", "3", false);

    // Assert
    expect(result).toBe(expected);
  });

  it("keeps a text field as text", () => {
    // Arrange
    const expected = "12";

    // Act
    const result = typed("text", "12", false);

    // Assert
    expect(result).toBe(expected);
  });

  it("leaves an empty value out of the request", () => {
    // Arrange
    const value = "";

    // Act
    const result = typed("choice", value, true);

    // Assert
    expect(result).toBeUndefined();
  });
});

describe("orderFamilies", () => {
  it("keeps the order the catalogue declares", () => {
    // Arrange
    const expected = ["inspect", "check", "hardware"];

    // Act
    const result = 
      orderFamilies(["hardware", "check", "inspect"], ["inspect", "check", "hardware"])
    ;

    // Assert
    expect(result).toEqual(expected);
  });

  it("puts a family the catalogue does not name last", () => {
    // Arrange
    const expected = ["inspect", "other"];

    // Act
    const result = orderFamilies(["other", "inspect"], ["inspect"]);

    // Assert
    expect(result).toEqual(expected);
  });

  it("falls back to alphabetical order with no declared order", () => {
    // Arrange
    const expected = ["check", "repair"];

    // Act
    const result = orderFamilies(["repair", "check"], []);

    // Assert
    expect(result).toEqual(expected);
  });
});

describe("helpFor", () => {
  it("prefers the help a command gives its own field", () => {
    // Arrange
    const expected = "read each side";

    // Act
    const result = helpFor("dump", { name: "passes" });

    // Assert
    expect(result).toContain(expected);
  });

  it("falls back to the help the field shares", () => {
    // Arrange
    const expected = "run all four patterns";

    // Act
    const result = helpFor("surface", { name: "passes" });

    // Assert
    expect(result).toContain(expected);
  });
});
