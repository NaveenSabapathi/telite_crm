import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
function fixture(...args: string[]) {
  const backend = path.resolve("../backend");
  return JSON.parse(
    execFileSync(
      process.env.E2E_PYTHON || "python",
      [path.join(backend, "tests/browser_seed.py"), ...args],
      { env: { ...process.env, PYTHONPATH: backend }, encoding: "utf8" },
    ),
  );
}
test("platform provisioning, flags, invitation and tenant employee management", async ({
  page,
}) => {
  const seed = fixture("bootstrap");
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  await page.getByLabel("Email address").fill("browser-admin@example.com");
  await page
    .getByLabel("Password", { exact: true })
    .fill("Browser-Platform-Test-42");
  await page.getByLabel("Authenticator code").fill(seed.otp);
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(
    page.getByRole("heading", { name: "Company overview" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add company" }).click();
  await page.getByLabel("Company name").fill("Breeze Test Company");
  await page.getByLabel("Unique slug").fill("breeze-browser-test");
  await page.getByLabel("Subscription valid through").fill("2030-11-14");
  await page.getByLabel("Office address").fill("Erode test office");
  await page.getByLabel("Latitude", { exact: true }).fill("11.341");
  await page.getByLabel("Longitude").fill("77.717");
  await page.getByLabel("Full name").fill("Test Owner");
  await page.getByLabel("Invitation email").fill("owner@example.com");
  await page.getByRole("button", { name: "Create & queue invitation" }).click();
  await expect(
    page.getByRole("cell", { name: "Breeze Test Company breeze-browser-test" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Manage →" }).click();
  await expect(
    page.getByRole("heading", { name: "Enabled modules" }),
  ).toBeVisible();
  await page.getByLabel("Sales CRM", { exact: true }).uncheck();
  await page
    .getByLabel("Reason for change")
    .nth(1)
    .fill("Browser test disable sales");
  await page.getByRole("button", { name: "Update modules" }).click();
  await expect(page.getByText("Module permissions updated.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/platform-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "test-results/platform-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out" }).click();
  const invite = fixture("invitation", "breeze-browser-test");
  await page.goto("/#token=" + invite.token + "&purpose=INVITE");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Secure your account" }),
  ).toBeVisible();
  await page
    .getByLabel("New password", { exact: true })
    .fill("Browser-Tenant-Test-42");
  await page.getByLabel("Confirm password").fill("Browser-Tenant-Test-42");
  await page.getByRole("button", { name: "Save password" }).click();
  await expect(
    page.getByText(
      "Password saved. Sign in using your company slug and email.",
    ),
  ).toBeVisible();
  await page
    .getByLabel("Company slug", { exact: true })
    .first()
    .fill("breeze-browser-test");
  await page.getByLabel("Email address").fill("owner@example.com");
  await page
    .getByLabel("Password", { exact: true })
    .fill("Browser-Tenant-Test-42");
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(
    page.getByRole("heading", { name: "Team access" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Invite employee" }).click();
  await page.getByLabel("Full name").fill("Field Engineer");
  await page.getByLabel("Email", { exact: true }).fill("engineer@example.com");
  await page.getByRole("button", { name: "Queue invitation" }).click();
  await expect(
    page.getByRole("cell", { name: "Field Engineer engineer@example.com" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Audit activity" }).click();
  await expect(
    page.getByRole("cell", { name: "EMPLOYEE INVITED" }),
  ).toBeVisible();
});
