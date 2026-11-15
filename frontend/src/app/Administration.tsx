import React, { useEffect, useState, FormEvent } from "react";
import { call, login, logout, refresh, clearAccess, Mode } from "../api";
import { OperationsWorkspace } from "../views/OperationsWorkspace";
import { Field } from "../components/Field";
import { PlatformViews } from "../views/PlatformViews";
import { CompanyViews } from "../views/CompanyViews";
type Tenant = {
  id: string;
  name: string;
  slug: string;
  status: string;
  max_active_employees: number;
  storage_quota_bytes: number;
  valid_until: string;
  version: number;
  features: Record<string, boolean>;
  admins: { id: string; email: string; display_name: string }[];
  active_employees: number;
};
type User = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  active: boolean;
  version: number;
  work_mode: string;
  must_reset_password: boolean;
};
const labels: Record<string, string> = {
  attendance_gps: "GPS attendance",
  field_service_tickets: "Field service",
  sales_crm: "Sales CRM",
  amc_tracker: "AMC contracts",
  monthly_email_reports: "Monthly email reports",
  background_location: "Background travel tracking",
};
const initialFlags = {
  attendance_gps: true,
  field_service_tickets: true,
  sales_crm: true,
  amc_tracker: false,
  monthly_email_reports: false,
  background_location: false,
};
export default function Administration() {
  const [mode, setMode] = useState<Mode>(
    localStorage.getItem("portalMode") === "tenant" ? "tenant" : "platform",
  );
  const [signed, setSigned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState("companies");
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selected, setSelected] = useState<Tenant | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [profile, setProfile] = useState<any>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  const [resetToken] = useState(
    () => new URLSearchParams(location.hash.slice(1)).get("token") || "",
  );
  const [resetPurpose] = useState(
    () => new URLSearchParams(location.hash.slice(1)).get("purpose") || "RESET",
  );
  const [resetDone, setResetDone] = useState(false);
  useEffect(() => {
    if (resetToken) history.replaceState(null, "", location.pathname);
  }, []);
  async function work(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function load(m = mode, start = offset, q = search) {
    if (m === "platform") {
      const [list, metrics] = await Promise.all([
        call(
          `/api/v1/platform/tenants?limit=25&offset=${start}&q=${encodeURIComponent(q)}`,
        ),
        call("/api/v1/platform/health"),
      ]);
      setTenants(list.data);
      setNext(list.next_offset);
      setHealth(metrics);
    } else {
      const me = await call("/api/v1/me", {}, m);
      setProfile(me);
      if (me.user.role === "COMPANY_ADMIN")
        setUsers((await call("/api/v1/users?limit=100", {}, m)).data);
    }
  }
  async function signIn(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await work(async () => {
      const body =
        mode === "platform"
          ? {
              email: f.get("email"),
              password: f.get("password"),
              otp: f.get("otp"),
            }
          : {
              slug: f.get("slug"),
              email: f.get("email"),
              password: f.get("password"),
              client_type: "web",
            };
      await login(mode, body);
      await load(mode, 0, "");
      setOffset(0);
      setSearch("");
      setSigned(true);
      setPage(mode === "platform" ? "companies" : "employees");
      localStorage.setItem("portalMode", mode);
    });
  }
  async function openTenant(id: string) {
    await work(async () => {
      setSelected(await call("/api/v1/platform/tenants/" + id));
      setPage("detail");
    });
  }
  async function showAudit() {
    await work(async () => {
      setAudit(
        (
          await call(
            mode === "platform" ? "/api/v1/platform/audit" : "/api/v1/audit",
            {},
            mode,
          )
        ).data,
      );
      setPage("audit");
    });
  }
  async function createCompany(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await work(async () => {
      const body = {
        name: f.get("name"),
        slug: f.get("slug"),
        timezone: "Asia/Kolkata",
        currency: "INR",
        max_active_employees: Number(f.get("cap")),
        storage_quota_bytes: Number(f.get("storage")) * 1073741824,
        valid_until: new Date(
          String(f.get("valid")) + "T23:59:59+05:30",
        ).toISOString(),
        branch: {
          name: "Main office",
          address: f.get("address"),
          lat: Number(f.get("lat")),
          lng: Number(f.get("lng")),
          radius_m: Number(f.get("radius")),
        },
        shift: {
          name: "Day shift",
          start_local: f.get("start"),
          end_local: f.get("end"),
          end_day_offset: f.get("overnight") ? 1 : 0,
          grace_minutes: 15,
          weekdays: [1, 2, 3, 4, 5, 6],
        },
        admin: { email: f.get("email"), display_name: f.get("admin") },
        features: initialFlags,
      };
      await call("/api/v1/platform/tenants", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(body),
      });
      await load(mode, 0, "");
      setOffset(0);
      setSearch("");
      setPage("companies");
      setNotice(
        "Company created. The administrator invitation is queued for email delivery.",
      );
    });
  }
  async function saveCompany(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selected) return;
    const f = new FormData(e.currentTarget);
    await work(async () => {
      await call("/api/v1/platform/tenants/" + selected.id, {
        method: "PATCH",
        headers: { "If-Match": String(selected.version) },
        body: JSON.stringify({
          name: f.get("name"),
          status: f.get("status"),
          max_active_employees: Number(f.get("cap")),
          storage_quota_bytes: Number(f.get("storage")) * 1073741824,
          valid_until: new Date(String(f.get("valid"))).toISOString(),
          reason: f.get("reason"),
        }),
      });
      setSelected(await call("/api/v1/platform/tenants/" + selected.id));
      await load();
      setNotice("Company settings saved.");
    });
  }
  async function saveFlags(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selected) return;
    const f = new FormData(e.currentTarget);
    await work(async () => {
      const features = Object.fromEntries(
        Object.keys(labels).map((k) => [k, f.get(k) === "on"]),
      );
      await call("/api/v1/platform/tenants/" + selected.id + "/features", {
        method: "PUT",
        headers: { "If-Match": String(selected.version) },
        body: JSON.stringify({ features, reason: f.get("reason") }),
      });
      setSelected(await call("/api/v1/platform/tenants/" + selected.id));
      setNotice("Module permissions updated.");
    });
  }
  async function inviteEmployee(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await work(async () => {
      const [branches, shifts] = await Promise.all([
        call("/api/v1/branches", {}, mode),
        call("/api/v1/shifts", {}, mode),
      ]);
      await call(
        "/api/v1/users",
        {
          method: "POST",
          body: JSON.stringify({
            email: f.get("email"),
            display_name: f.get("name"),
            role: f.get("role"),
            work_mode: f.get("work_mode"),
            branch_id: branches.data[0].id,
            shift_id: shifts.data[0].id,
          }),
        },
        mode,
      );
      await load();
      setPage("employees");
      setNotice("Employee invitation queued.");
    });
  }
  if (resetToken && !resetDone)
    return (
      <main className="login">
        <section className="login-card">
          <div className="brand">
            T<span>Telite CRM</span>
          </div>
          <h1>Secure your account</h1>
          <p>
            Create your password to{" "}
            {resetPurpose === "INVITE"
              ? "accept your invitation"
              : "complete account recovery"}
            .
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void work(async () => {
                if (f.get("password") !== f.get("confirm"))
                  throw new Error("Passwords do not match.");
                await call(
                  "/api/v1/auth/" +
                    (resetPurpose === "INVITE"
                      ? "accept-invite"
                      : "reset-password"),
                  {
                    method: "POST",
                    body: JSON.stringify({
                      token: resetToken,
                      new_password: f.get("password"),
                    }),
                  },
                  "tenant",
                  false,
                );
                setResetDone(true);
                setMode("tenant");
                setNotice(
                  "Password saved. Sign in using your company slug and email.",
                );
              });
            }}
          >
            <Field
              label="New password"
              name="password"
              type="password"
              minLength={12}
              maxLength={128}
              required
              autoComplete="new-password"
            />
            <Field
              label="Confirm password"
              name="confirm"
              type="password"
              required
              autoComplete="new-password"
            />
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button disabled={busy}>Save password</button>
          </form>
        </section>
      </main>
    );
  if (!signed)
    return (
      <main className="login">
        <aside className="login-story">
          <div className="eyebrow">HARDWARE SALES & FIELD SERVICE</div>
          <h1>
            A clear view.
            <br />
            Every company.
            <br />
            Every team.
          </h1>
          <p>One secure workspace for the people keeping business running.</p>
          <div className="story-note">
            TELITE SYSTEMS <span>CRM / ADMINISTRATION</span>
          </div>
        </aside>
        <section className="login-card">
          <div className="brand">
            T<span>Telite CRM</span>
          </div>
          <h2>Welcome back</h2>
          <p>Sign in to your administration workspace.</p>
          <div className="tabs">
            <button
              className={mode === "platform" ? "active" : "ghost"}
              onClick={() => {
                clearAccess();
                setMode("platform");
              }}
            >
              Platform admin
            </button>
            <button
              className={mode === "tenant" ? "active" : "ghost"}
              onClick={() => {
                clearAccess();
                setMode("tenant");
              }}
            >
              Company
            </button>
          </div>
          <form onSubmit={signIn}>
            {mode === "tenant" && (
              <Field
                label="Company slug"
                name="slug"
                required
                placeholder="breeze-erode"
              />
            )}
            <Field
              label="Email address"
              name="email"
              type="email"
              required
              autoComplete="username"
            />
            <Field
              label="Password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
            />
            {mode === "platform" && (
              <Field
                label="Authenticator code"
                name="otp"
                pattern="[0-9]{6}"
                inputMode="numeric"
                maxLength={6}
                required
                autoComplete="one-time-code"
              />
            )}
            <button disabled={busy}>
              {busy ? "Signing in…" : "Sign in securely →"}
            </button>
          </form>
          <button
            className="ghost"
            disabled={busy}
            onClick={() =>
              void work(async () => {
                await refresh(mode);
                await load(mode);
                setSigned(true);
                setPage(mode === "platform" ? "companies" : "employees");
              })
            }
          >
            Resume existing session
          </button>
          {mode === "tenant" && (
            <details>
              <summary>Forgot your password?</summary>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const f = new FormData(e.currentTarget);
                  void work(async () => {
                    await call(
                      "/api/v1/auth/forgot-password",
                      {
                        method: "POST",
                        body: JSON.stringify({
                          slug: f.get("slug"),
                          email: f.get("email"),
                        }),
                      },
                      mode,
                      false,
                    );
                    setNotice(
                      "If eligible, a reset link will be emailed to you.",
                    );
                  });
                }}
              >
                <Field label="Company slug" name="slug" required />
                <Field label="Email" name="email" type="email" required />
                <button disabled={busy}>Request reset</button>
              </form>
            </details>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {notice && (
            <p role="status" className="success">
              {notice}
            </p>
          )}
        </section>
      </main>
    );
  const isAdmin = mode === "platform" || profile?.user.role === "COMPANY_ADMIN";
  if (
    mode === "tenant" &&
    (profile?.user.role !== "COMPANY_ADMIN" || page === "operations")
  )
    return (
      <OperationsWorkspace
        profile={profile}
        onAdmin={() => setPage("employees")}
        onLogout={async () => {
          await logout(mode);
          setSigned(false);
          setProfile(null);
        }}
      />
    );
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          T
          <span>
            Telite CRM
            <small>
              {mode === "platform" ? "PLATFORM CONSOLE" : "COMPANY WORKSPACE"}
            </small>
          </span>
        </div>
        <nav>
          {mode === "tenant" && (
            <button className="nav" onClick={() => setPage("operations")}>
              Operations dashboard
            </button>
          )}
          <button
            className={
              page === "companies" || page === "employees"
                ? "nav active"
                : "nav"
            }
            onClick={() => {
              setPage(mode === "platform" ? "companies" : "employees");
              void work(() => load());
            }}
          >
            {mode === "platform" ? "Companies" : "Employees & access"}
          </button>
          {isAdmin && (
            <button
              className={page === "audit" ? "nav active" : "nav"}
              onClick={showAudit}
            >
              Audit activity
            </button>
          )}
        </nav>
        <div className="sidebar-foot">
          {mode === "platform"
            ? "Platform administrator"
            : profile?.tenant.name}
          <button
            className="nav"
            onClick={() =>
              void work(async () => {
                try {
                  await logout(mode);
                } finally {
                  setSigned(false);
                  setSelected(null);
                  setProfile(null);
                  setUsers([]);
                  setTenants([]);
                }
              })
            }
          >
            Sign out ↗
          </button>
        </div>
      </aside>
      <main className="content">
        <header>
          <div>
            <div className="eyebrow">
              {mode === "platform"
                ? "OPERATIONS / PLATFORM"
                : "OPERATIONS / COMPANY"}
            </div>
            <h1>
              {page === "create"
                ? "Onboard a company"
                : page === "detail"
                  ? selected?.name
                  : page === "audit"
                    ? "Audit activity"
                    : page === "invite"
                      ? "Invite employee"
                      : mode === "platform"
                        ? "Company overview"
                        : "Team access"}
            </h1>
            <p>
              {mode === "platform"
                ? "Manage companies, access and subscription limits."
                : "Manage your team’s access to the company workspace."}
            </p>
          </div>
          <span className="badge">
            {mode === "platform"
              ? "SUPER ADMIN"
              : profile?.user.role.replaceAll("_", " ")}
          </span>
        </header>
        {error && (
          <div role="alert" className="error">
            {error}{" "}
            <button
              className="ghost"
              onClick={() =>
                selected ? openTenant(selected.id) : work(() => load())
              }
            >
              Reload
            </button>
          </div>
        )}
        {notice && (
          <div role="status" className="success">
            {notice}
          </div>
        )}
        {busy && (
          <div role="status" className="progress">
            Working…
          </div>
        )}
        <PlatformViews
          {...{
            page,
            health,
            tenants,
            offset,
            next,
            busy,
            search,
            setSearch,
            setOffset,
            work,
            load,
            mode,
            setPage,
            openTenant,
            createCompany,
            selected,
            saveCompany,
            saveFlags,
            labels,
            setNotice,
          }}
        />
        <CompanyViews
          {...{
            page,
            isAdmin,
            users,
            busy,
            work,
            load,
            mode,
            setPage,
            setNotice,
            profile,
            inviteEmployee,
            audit,
          }}
        />
        <footer>
          Telite CRM · Administration{" "}
          <span>Company data stays within its authorized workspace.</span>
        </footer>
      </main>
    </div>
  );
}
