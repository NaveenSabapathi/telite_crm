export type Mode = "platform" | "tenant";
let access = "";
let refreshing: Promise<void> | null = null;
export function clearAccess() {
  access = "";
}
export function cookie(name: string) {
  return (
    document.cookie
      .split("; ")
      .find((x) => x.startsWith(name + "="))
      ?.slice(name.length + 1) || ""
  );
}
const prefix = (mode: Mode) =>
  mode === "platform" ? "/api/v1/platform/auth" : "/api/v1/auth";
export async function login(mode: Mode, body: unknown) {
  const data = await call(
    prefix(mode) + "/login",
    { method: "POST", body: JSON.stringify(body) },
    mode,
    false,
  );
  access = data.access_token;
}
export async function refresh(mode: Mode) {
  if (!refreshing) {
    refreshing = (async () => {
      const r = await fetch(prefix(mode) + "/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": cookie(mode + "_csrf"),
        },
        body: "{}",
      });
      if (!r.ok) {
        clearAccess();
        throw new Error("Your session has ended. Please sign in again.");
      }
      access = (await r.json()).access_token;
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}
export async function logout(mode: Mode) {
  try {
    await call(
      prefix(mode) + "/logout",
      {
        method: "POST",
        body: "{}",
        headers: { "X-CSRF-Token": cookie(mode + "_csrf") },
      },
      mode,
      false,
    );
  } finally {
    clearAccess();
  }
}
export async function call(
  path: string,
  options: RequestInit = {},
  mode: Mode = "platform",
  retry = true,
): Promise<any> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (access) headers.Authorization = "Bearer " + access;
  let response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401 && retry) {
    await refresh(mode);
    return call(path, options, mode, false);
  }
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = body.error?.code || "REQUEST_FAILED";
    const messages: Record<string, string> = {
      VERSION_CONFLICT: "This record changed. Reload it before saving.",
      CONSTRAINT_CONFLICT:
        "This conflicts with an existing record or the employee limit.",
      INVALID_CREDENTIALS: "Check your credentials and authenticator code.",
      INVALID_INPUT: "Check the form fields and try again.",
      LAST_ADMIN_PROTECTED:
        "Assign another administrator before removing the last one.",
      TENANT_INACTIVE:
        "This company is suspended or its subscription has expired.",
      RATE_LIMITED: "Too many attempts. Please try again later.",
      QUOTA_BELOW_CURRENT_USAGE: "The new limit is below current usage.",
    };
    throw new Error(messages[code] || code.replaceAll("_", " "));
  }
  return body;
}
