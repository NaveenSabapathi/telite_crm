import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
function seed() {
  const backend = path.resolve("../backend");
  return JSON.parse(
    execFileSync(
      process.env.E2E_PYTHON || "python",
      [path.join(backend, "tests/browser_operations_seed.py")],
      { env: { ...process.env, PYTHONPATH: backend }, encoding: "utf8" },
    ),
  );
}
async function login(
  page: any,
  email: string,
  password = "Operations-Test-Password-42",
) {
  await page.goto("/");
  await page.getByRole("button", { name: "Company", exact: true }).click();
  await page
    .getByLabel("Company slug", { exact: true })
    .first()
    .fill("alpha-company");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in securely" }).click();
}
test("mobile attendance disclosure, geolocation, assigned ticket closure and profile", async ({
  page,
  context,
}) => {
  seed();
  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({
    latitude: 11.3,
    longitude: 77.7,
    accuracy: 5,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "engineer@example.com");
  await expect(
    page.getByRole("navigation", { name: "Employee navigation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Punch in", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "No background location",
  );
  await page.getByRole("button", { name: "Not now", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("declined");
  await page.getByRole("button", { name: "Punch in", exact: true }).click();
  await page.getByRole("button", { name: "Agree and continue" }).click();
  await expect(
    page.getByRole("button", { name: "Punch out", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Service Tickets", exact: true })
    .click();
  await page.getByRole("button", { name: /#1 · Hardware customer/ }).click();
  for (const status of ["EN_ROUTE", "ON_SITE", "IN_PROGRESS", "RESOLVED"]) {
    await page.getByLabel("Next status").selectOption(status);
    await page
      .getByLabel("Work notes", { exact: true })
      .fill("Adapter replaced and load tested");
    await page.getByRole("button", { name: "Update ticket status" }).click();
    if (status === "ON_SITE")
      await page.getByRole("button", { name: "Agree and continue" }).click();
    await expect(
      page.getByRole("heading", { name: "#1 · " + status, exact: true }),
    ).toBeVisible();
  }
  await page
    .getByLabel("Completion photo", { exact: true })
    .setInputFiles({
      name: "after.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKUlEQVR4nO3NMQEAAAjDMMC/52ECvlRA00nqs3m9AwAAAAAAAAAAgMMWx/EDPS4YA2MAAAAASUVORK5CYII=",
        "base64",
      ),
    });
  await expect(page.getByText("Completion photo ready", { exact: true })).toBeVisible();
  const pad = page.getByLabel("Customer signature pad");
  await pad.scrollIntoViewIfNeeded();
  const box = (await pad.boundingBox())!;
  await page.mouse.move(box.x + 20, box.y + 30);
  await page.mouse.down();
  await page.mouse.move(box.x + 120, box.y + 90, { steps: 8 });
  await page.mouse.up();
  await page.getByLabel("Customer signer name").fill("Test Customer");
  await page.getByLabel("Customer acknowledges").check();
  await page.getByLabel("Payment collection mode").selectOption("WARRANTY");
  await page.getByRole("button", { name: "Complete service ticket" }).click();
  await page.getByRole("button", { name: "Agree and continue" }).click();
  await expect(
    page.getByRole("heading", { name: "#1 · COMPLETED", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/employee-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Profile", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Account & data deletion request" }),
  ).toBeVisible();
});
test("company dashboard report downloads and sales conversion", async ({
  page,
}) => {
  seed();
  await login(page, "owner@example.com", "Tenant-Test-Password-42");
  await page.getByRole("button", { name: "Operations dashboard" }).click();
  await expect(
    page.getByRole("heading", { name: "Today's operations" }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download monthly CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  await page.getByRole("button", { name: "Leads (CRM)", exact: true }).click();
  await page.getByRole("button", { name: "Create lead", exact: true }).click();
  for (const [label, value] of [
    ["Customer name", "New customer"],
    ["Customer phone", "9999999999"],
    ["Site address", "Erode office"],
    ["Site latitude", "11.3"],
    ["Site longitude", "77.7"],
    ["Requirement", "Install four CCTV cameras"],
  ])
    await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Save lead", exact: true }).click();
  await page.getByRole("button", { name: /New customer/ }).click();
  await page.getByLabel("Pipeline stage").selectOption("WON");
  await page.getByLabel("Stage change reason").fill("Customer accepted offer");
  await page.getByLabel("Won value", { exact: true }).fill("12000");
  await page.getByRole("button", { name: "Update lead stage" }).click();
  page.once("dialog", (d) => d.accept());
  await page
    .getByRole("button", { name: "Convert won lead to service ticket" })
    .click();
  await page
    .getByRole("button", { name: "Service Tickets", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /#2 · New customer/ }),
  ).toBeVisible();
});
