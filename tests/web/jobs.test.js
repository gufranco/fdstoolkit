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
    expect(isJobRoute("/api/jobs/write")).toBe(true);
    expect(isJobRoute("/api/info")).toBe(false);
  });
});

describe("jobView", () => {
  it("lists every step so far where a screen reader hears it", () => {
    const view = jobView(running, () => {});

    expect([...view.querySelectorAll(".steps li")].map((node) => node.textContent)).toEqual([
      "reading side 0"
    ]);
    expect(view.querySelector(".steps").getAttribute("aria-live")).toBe("polite");
  });

  it("warns that closing the page leaves a side half written", () => {
    const view = jobView(running, () => {});

    expect(view.querySelector(".quiet")).not.toBeNull();
  });

  it("asks for the disk to be turned over and passes the answer on", () => {
    let answers = [];
    const view = jobView(
      { ...running, state: "waiting", prompt: "turn the disk over" },
      (id, yes) => {
        answers = [...answers, [id, yes]];
      }
    );

    const prompt = view.querySelector(".turn");
    prompt.querySelector(".run").click();

    expect(prompt.getAttribute("role")).toBe("alert");
    expect(prompt.querySelector(".prompt").textContent).toBe("turn the disk over");
    expect(answers).toEqual([["j1", true]]);
    expect(prompt.querySelector(".run").disabled).toBe(true);
  });

  it("passes a refusal to turn the disk on as a no", () => {
    let answers = [];
    const view = jobView({ ...running, state: "waiting", prompt: "turn" }, (id, yes) => {
      answers = [...answers, [id, yes]];
    });

    view.querySelector(".turn .plain").click();

    expect(answers).toEqual([["j1", false]]);
  });

  it("shows why a job stopped", () => {
    const view = jobView({ ...running, state: "failed", error: "the drive stalled" }, () => {});

    expect(view.querySelector(".banner").className).toContain("bad");
    expect(view.querySelector(".reason").textContent).toBe("the drive stalled");
    expect(view.querySelector(".quiet")).toBeNull();
  });
});

describe("follow", () => {
  it("renders the result as soon as the job is done", async () => {
    const out = document.createElement("div");
    const done = { ...running, state: "done", result: { headline: "written", ok: true } };

    await follow(done, out, { fetchJob: () => Promise.reject(new Error("not asked")) });

    expect(out.querySelector(".banner").textContent).toBe("written");
  });

  it("keeps asking until the job ends", async () => {
    const out = document.createElement("div");
    let seen = [];
    const later = { ...running, state: "failed", error: "stopped" };

    const last = await follow(running, out, {
      fetchJob: (id) => {
        seen = [...seen, id];
        return Promise.resolve(later);
      }
    });

    expect(seen).toEqual(["j1"]);
    expect(last.state).toBe("failed");
    expect(out.querySelector(".reason").textContent).toBe("stopped");
  });

  it("stops following once it has asked as many times as it may", async () => {
    const out = document.createElement("div");

    const last = await follow(running, out, { fetchJob: () => Promise.resolve(running), polls: 1 });

    expect(last.state).toBe("running");
    expect(out.querySelector(".banner").className).toContain("warn");
  });
});

describe("confirmErase", () => {
  it("starts on cancel and answers no when cancelled", async () => {
    const answered = confirmErase("write");
    const dialog = document.querySelector("dialog");

    expect(document.activeElement.textContent).toBe(dialog.querySelector(".plain").textContent);
    dialog.querySelector(".plain").click();

    await expect(answered).resolves.toBe(false);
    expect(document.querySelector("dialog")).toBeNull();
  });

  it("answers yes when the erase is confirmed", async () => {
    const answered = confirmErase("surface");

    document.querySelector("dialog .danger").click();

    await expect(answered).resolves.toBe(true);
  });

  it("answers no when escape closes it", async () => {
    const answered = confirmErase("write");

    document.querySelector("dialog").dispatchEvent(new Event("cancel", { cancelable: true }));

    await expect(answered).resolves.toBe(false);
  });

  it("is labelled by its own title and text", () => {
    confirmErase("write");
    const dialog = document.querySelector("dialog");

    expect(document.getElementById(dialog.getAttribute("aria-labelledby"))).not.toBeNull();
    expect(document.getElementById(dialog.getAttribute("aria-describedby"))).not.toBeNull();
  });
});

describe("stopping a job", () => {
  const measuring = { ...running, command: "calibrate", writes: false, stoppable: true };

  it("offers a stop while a stoppable job runs and passes it on", () => {
    let stopped = [];
    const view = jobView(measuring, () => {}, (id) => {
      stopped = [...stopped, id];
    });

    const button = view.querySelector(".dialog-actions .plain");
    button.click();

    expect(button.textContent).toBe("Stop");
    expect(button.disabled).toBe(true);
    expect(stopped).toEqual(["j1"]);
  });

  it("says the stop is coming once it was asked for", () => {
    const view = jobView({ ...measuring, stopping: true }, () => {});

    expect(view.querySelector(".dialog-actions")).toBeNull();
    expect(view.textContent).toContain("Stopping after the read in progress.");
  });

  it("offers no stop for a job that cannot stop", () => {
    const view = jobView(running, () => {});

    expect(view.querySelector(".dialog-actions")).toBeNull();
  });
});

describe("the calibration prompt", () => {
  it("names the step rather than the disk", () => {
    const view = jobView(
      { ...running, command: "calibrate", state: "waiting", prompt: "turn one step" },
      () => {}
    );

    expect(view.querySelector(".turn .run").textContent).toBe("Turned it, read again");
  });
});
