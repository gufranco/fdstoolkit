import { afterEach, describe, expect, it } from "vitest";

import { confirmErase, follow, isJobRoute, jobView } from "../../src/fdstoolkit/ui/static/app.js";

const running = {
  id: "j1",
  command: "write",
  writes: true,
  state: "running",
  steps: ["reading side 0"],
  prompt: "",
  result: null,
  error: ""
};

afterEach(() => {
  document.body.replaceChildren();
});

describe("isJobRoute", () => {
  it("recognises the routes that run on the drive", () => {
    // Arrange
    const expected = true;

    // Act
    const result = isJobRoute("/api/jobs/write");

    // Assert
    expect(result).toBe(expected);
    expect(isJobRoute("/api/info")).toBe(false);
  });
});

describe("jobView", () => {
  it("lists every step so far where a screen reader hears it", () => {
    // Arrange
    const expected = [
      "reading side 0"
    ];

    // Act
    const view = jobView(running, () => {});

    // Assert
    expect([...view.querySelectorAll(".steps li")].map((node) => node.textContent)).toEqual(expected);
    expect(view.querySelector(".steps").getAttribute("aria-live")).toBe("polite");
  });

  it("marks the command's own output as English for screen readers", () => {
    // Arrange
    const expected = "en";

    // Act
    const view = jobView(
      { ...running, state: "failed", error: "the device stopped answering" },
      () => {}
    );

    // Assert
    expect(view.querySelector(".steps").lang).toBe(expected);
    expect(view.querySelector(".reason").lang).toBe("en");
  });

  it("says the command output is shown as the command line prints it", () => {
    // Arrange
    const onAnswer = () => {};

    // Act
    const view = jobView(running, onAnswer);

    // Assert
    expect(view.querySelector(".output-language")).not.toBeNull();
  });

  it("marks a turn prompt as English", () => {
    // Arrange
    const expected = "en";

    // Act
    const view = jobView({ ...running, state: "waiting", prompt: "turn the disk over" }, () => {});

    // Assert
    expect(view.querySelector(".prompt").lang).toBe(expected);
  });

  it("warns that closing the page leaves a side half written", () => {
    // Arrange
    const onAnswer = () => {};

    // Act
    const view = jobView(running, onAnswer);

    // Assert
    expect(view.querySelector(".quiet")).not.toBeNull();
  });

  it("asks for the disk to be turned over and passes the answer on", () => {
    // Arrange
    let answers = [];
    const view = jobView(
      { ...running, state: "waiting", prompt: "turn the disk over" },
      (id, yes) => {
        answers = [...answers, [id, yes]];
      }
    );
    const prompt = view.querySelector(".turn");

    // Act
    prompt.querySelector(".run").click();

    // Assert
    expect(prompt.getAttribute("role")).toBe("alert");
    expect(prompt.querySelector(".prompt").textContent).toBe("turn the disk over");
    expect(answers).toEqual([["j1", true]]);
    expect(prompt.querySelector(".run").disabled).toBe(true);
  });

  it("passes a refusal to turn the disk on as a no", () => {
    // Arrange
    let answers = [];
    const view = jobView({ ...running, state: "waiting", prompt: "turn" }, (id, yes) => {
      answers = [...answers, [id, yes]];
    });

    // Act
    view.querySelector(".turn .plain").click();

    // Assert
    expect(answers).toEqual([["j1", false]]);
  });

  it("shows why a job stopped", () => {
    // Arrange
    const expected = "bad";

    // Act
    const view = jobView({ ...running, state: "failed", error: "the drive stalled" }, () => {});

    // Assert
    expect(view.querySelector(".banner").className).toContain(expected);
    expect(view.querySelector(".reason").textContent).toBe("the drive stalled");
    expect(view.querySelector(".quiet")).toBeNull();
  });

  it("still offers the disk's contents read before a failed write", () => {
    // Arrange
    const kept = { name: "before.fds", data: "AQ==", size: 1 };

    // Act
    const view = jobView({ ...running, state: "failed", error: "refused", kept }, () => {});

    // Assert
    expect(view.querySelector(".download").getAttribute("download")).toBe("before.fds");
  });

  it("offers nothing extra when a failed job kept no file", () => {
    // Arrange
    const failed = { ...running, state: "failed", error: "refused" };

    // Act
    const view = jobView(failed, () => {});

    // Assert
    expect(view.querySelector(".download")).toBeNull();
  });
});

describe("follow", () => {
  it("renders the result as soon as the job is done", async () => {
    // Arrange
    const out = document.createElement("div");
    const done = { ...running, state: "done", result: { headline: "written", ok: true } };

    // Act
    await follow(done, out, { fetchJob: () => Promise.reject(new Error("not asked")) });

    // Assert
    expect(out.querySelector(".banner").textContent).toBe("written");
  });

  it("keeps asking until the job ends", async () => {
    // Arrange
    const out = document.createElement("div");
    let seen = [];
    const later = { ...running, state: "failed", error: "stopped" };

    // Act
    const last = await follow(running, out, {
      fetchJob: (id) => {
        seen = [...seen, id];
        return Promise.resolve(later);
      }
    });

    // Assert
    expect(seen).toEqual(["j1"]);
    expect(last.state).toBe("failed");
    expect(out.querySelector(".reason").textContent).toBe("stopped");
  });

  it("stops following once it has asked as many times as it may", async () => {
    // Arrange
    const out = document.createElement("div");

    // Act
    const last = await follow(running, out, { fetchJob: () => Promise.resolve(running), polls: 1 });

    // Assert
    expect(last.state).toBe("running");
    expect(out.querySelector(".banner").className).toContain("warn");
  });
});

describe("confirmErase", () => {
  it("starts on cancel and answers no when cancelled", async () => {
    // Arrange
    const answered = confirmErase("write");
    const dialog = document.querySelector("dialog");
    const focused = document.activeElement.textContent;

    // Act
    dialog.querySelector(".plain").click();

    // Assert
    expect(focused).toBe(dialog.querySelector(".plain").textContent);
    await expect(answered).resolves.toBe(false);
    expect(document.querySelector("dialog")).toBeNull();
  });

  it("answers yes when the erase is confirmed", async () => {
    // Arrange
    const answered = confirmErase("surface");

    // Act
    document.querySelector("dialog .danger").click();

    // Assert
    await expect(answered).resolves.toBe(true);
  });

  it("answers no when escape closes it", async () => {
    // Arrange
    const answered = confirmErase("write");

    // Act
    document.querySelector("dialog").dispatchEvent(new Event("cancel", { cancelable: true }));

    // Assert
    await expect(answered).resolves.toBe(false);
  });

  it("is labelled by its own title and text", () => {
    // Arrange
    confirmErase("write");

    // Act
    const dialog = document.querySelector("dialog");

    // Assert
    expect(document.getElementById(dialog.getAttribute("aria-labelledby"))).not.toBeNull();
    expect(document.getElementById(dialog.getAttribute("aria-describedby"))).not.toBeNull();
  });
});

describe("stopping a job", () => {
  const measuring = { ...running, command: "calibrate", writes: false, stoppable: true };

  it("offers a stop while a stoppable job runs and passes it on", () => {
    // Arrange
    let stopped = [];
    const view = jobView(measuring, () => {}, (id) => {
      stopped = [...stopped, id];
    });
    const button = view.querySelector(".dialog-actions .plain");

    // Act
    button.click();

    // Assert
    expect(button.textContent).toBe("Stop");
    expect(button.disabled).toBe(true);
    expect(stopped).toEqual(["j1"]);
  });

  it("says the stop is coming once it was asked for", () => {
    // Arrange
    const stopping = { ...measuring, stopping: true };

    // Act
    const view = jobView(stopping, () => {});

    // Assert
    expect(view.querySelector(".dialog-actions")).toBeNull();
    expect(view.textContent).toContain("Stopping after the read in progress.");
  });

  it("offers no stop for a job that cannot stop", () => {
    // Arrange
    const onAnswer = () => {};

    // Act
    const view = jobView(running, onAnswer);

    // Assert
    expect(view.querySelector(".dialog-actions")).toBeNull();
  });
});

describe("the calibration prompt", () => {
  it("names the step rather than the disk", () => {
    // Arrange
    const expected = "Turned it, read again";

    // Act
    const view = jobView(
      { ...running, command: "calibrate", state: "waiting", prompt: "turn one step" },
      () => {}
    );

    // Assert
    expect(view.querySelector(".turn .run").textContent).toBe(expected);
  });
});
