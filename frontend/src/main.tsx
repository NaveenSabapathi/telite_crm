import React, { useEffect, useState, FormEvent } from "react";
import { createRoot } from "react-dom/client";
import { call, login, logout, refresh, clearAccess, Mode } from "./api";
import "./style.css";
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
function Field({
  label,
  ...props
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} />
    </label>
  );
}
function App() {
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
        {page === "companies" && (
          <>
            <section className="metrics">
              <article>
                <span>Companies</span>
                <strong>{health?.tenants ?? "—"}</strong>
                <small>Registered on the platform</small>
              </article>
              <article>
                <span>Active subscriptions</span>
                <strong>{health?.active ?? "—"}</strong>
                <small>Enabled and within validity</small>
              </article>
              <article>
                <span>Database</span>
                <strong className="status-text">Available</strong>
                <small>Platform connection verified</small>
              </article>
            </section>
            <section className="panel">
              <div className="toolbar">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    setOffset(0);
                    void work(() => load(mode, 0, search));
                  }}
                >
                  <input
                    aria-label="Search companies"
                    placeholder="Search company or slug…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <button className="secondary" disabled={busy}>
                    Search
                  </button>
                </form>
                <button onClick={() => setPage("create")}>
                  ＋ Add company
                </button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Company</th>
                      <th>Status</th>
                      <th>Employee limit</th>
                      <th>Valid until</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {tenants.map((t) => (
                      <tr key={t.id}>
                        <td>
                          <b>{t.name}</b>
                          <small>{t.slug}</small>
                        </td>
                        <td>
                          <span
                            className={
                              "badge " +
                              (t.status === "ACTIVE" &&
                              new Date(t.valid_until) > new Date()
                                ? "good"
                                : "muted")
                            }
                          >
                            {t.status === "ACTIVE" &&
                            new Date(t.valid_until) <= new Date()
                              ? "EXPIRED"
                              : t.status}
                          </span>
                        </td>
                        <td>{t.max_active_employees}</td>
                        <td>{new Date(t.valid_until).toLocaleDateString()}</td>
                        <td>
                          <button
                            className="ghost"
                            onClick={() => openTenant(t.id)}
                          >
                            Manage →
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!tenants.length && (
                  <div className="empty">
                    <h3>No companies yet</h3>
                    <p>
                      Add a company to send its first administrator invitation.
                    </p>
                  </div>
                )}
              </div>
              <div className="pagination">
                <button
                  className="secondary"
                  disabled={offset === 0 || busy}
                  onClick={() => {
                    setOffset(offset - 25);
                    void work(() => load(mode, offset - 25));
                  }}
                >
                  Previous
                </button>
                <span>Page {offset / 25 + 1}</span>
                <button
                  className="secondary"
                  disabled={next === null || busy}
                  onClick={() => {
                    setOffset(next!);
                    void work(() => load(mode, next!));
                  }}
                >
                  Next
                </button>
              </div>
            </section>
          </>
        )}
        {page === "create" && (
          <form className="panel form-panel" onSubmit={createCompany}>
            <h2>Company details</h2>
            <div className="grid">
              <Field
                label="Company name"
                name="name"
                required
                maxLength={150}
              />
              <Field
                label="Unique slug"
                name="slug"
                required
                pattern="[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"
                placeholder="breeze-erode"
              />
              <Field
                label="Employee limit"
                name="cap"
                type="number"
                min={1}
                max={10000}
                defaultValue={25}
                required
              />
              <Field
                label="Storage quota (GiB)"
                name="storage"
                type="number"
                min={1}
                max={10240}
                defaultValue={10}
                required
              />
              <Field
                label="Subscription valid through (India time)"
                name="valid"
                type="date"
                required
              />
              <Field label="Office address" name="address" required />
            </div>
            <h2>Office & shift</h2>
            <p>
              Use verified office coordinates. Defaults: India timezone, INR,
              Monday–Saturday.
            </p>
            <div className="grid">
              <Field
                label="Latitude"
                name="lat"
                type="number"
                step="any"
                min={-90}
                max={90}
                required
              />
              <Field
                label="Longitude"
                name="lng"
                type="number"
                step="any"
                min={-180}
                max={180}
                required
              />
              <Field
                label="Geofence radius (metres)"
                name="radius"
                type="number"
                min={25}
                max={5000}
                defaultValue={150}
                required
              />
              <Field
                label="Shift starts"
                name="start"
                type="time"
                defaultValue="09:30"
                required
              />
              <Field
                label="Shift ends"
                name="end"
                type="time"
                defaultValue="18:30"
                required
              />
              <label className="check">
                <input name="overnight" type="checkbox" />
                Ends the following day
              </label>
            </div>
            <h2>First administrator</h2>
            <div className="grid">
              <Field label="Full name" name="admin" required />
              <Field
                label="Invitation email"
                name="email"
                type="email"
                required
              />
            </div>
            <p className="hint">
              Attendance, field service and CRM start enabled. Configure other
              modules after creation. Invitations reserve one employee slot.
            </p>
            <div className="actions">
              <button disabled={busy}>Create & queue invitation</button>
              <button
                type="button"
                className="secondary"
                onClick={() => setPage("companies")}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
        {page === "detail" && selected && (
          <div className="detail-grid">
            <form
              key={selected.id + ":" + selected.version}
              className="panel form-panel"
              onSubmit={saveCompany}
            >
              <h2>Subscription & access</h2>
              <p>
                {selected.slug} · {selected.active_employees} active/invited
                employees
              </p>
              <Field
                label="Company name"
                name="name"
                defaultValue={selected.name}
                required
              />
              <label className="field">
                <span>Status</span>
                <select name="status" defaultValue={selected.status}>
                  <option>ACTIVE</option>
                  <option>SUSPENDED</option>
                </select>
              </label>
              <Field
                label="Employee limit"
                name="cap"
                type="number"
                min={1}
                defaultValue={selected.max_active_employees}
                required
              />
              <Field
                label="Storage quota (GiB)"
                name="storage"
                type="number"
                step="any"
                min={0.001}
                defaultValue={selected.storage_quota_bytes / 1073741824}
                required
              />
              <Field
                label="Validity timestamp (with timezone)"
                name="valid"
                defaultValue={selected.valid_until}
                required
              />
              <Field
                label="Reason for change"
                name="reason"
                minLength={5}
                required
              />
              <p className="hint">
                Suspension immediately revokes employee sessions.
              </p>
              <button disabled={busy}>Save settings</button>
            </form>
            <div>
              <form
                key={"flags" + selected.version}
                className="panel form-panel"
                onSubmit={saveFlags}
              >
                <h2>Enabled modules</h2>
                {Object.entries(labels).map(([key, label]) => (
                  <label className="toggle" key={key}>
                    <span>{label}</span>
                    <input
                      type="checkbox"
                      name={key}
                      defaultChecked={selected.features[key]}
                    />
                  </label>
                ))}
                <p className="hint">
                  AMC requires field service. Background tracking requires
                  attendance and remains unavailable until the Android release
                  gate is met.
                </p>
                <Field
                  label="Reason for change"
                  name="reason"
                  minLength={5}
                  required
                />
                <button disabled={busy}>Update modules</button>
              </form>
              <section className="panel form-panel">
                <h2>Administrator recovery</h2>
                {selected.admins.map((a) => (
                  <div className="admin-row" key={a.id}>
                    <div>
                      <b>{a.display_name}</b>
                      <small>{a.email}</small>
                    </div>
                    <button
                      disabled={busy}
                      className="secondary"
                      onClick={() => {
                        const reason = prompt(
                          "Reason for password reset (at least 5 characters):",
                        );
                        if (reason && reason.length >= 5)
                          void work(async () => {
                            await call(
                              `/api/v1/platform/tenants/${selected.id}/reset-admin`,
                              {
                                method: "POST",
                                body: JSON.stringify({
                                  admin_user_id: a.id,
                                  reason,
                                }),
                              },
                            );
                            setNotice(
                              "Reset email queued. Existing sessions have been revoked.",
                            );
                          });
                      }}
                    >
                      Reset access
                    </button>
                  </div>
                ))}
              </section>
            </div>
          </div>
        )}
        {page === "employees" && (
          <section className="panel">
            <div className="toolbar">
              <h2>{profile?.tenant.name}</h2>
              {isAdmin && (
                <button onClick={() => setPage("invite")}>
                  ＋ Invite employee
                </button>
              )}
            </div>
            {isAdmin ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Employee</th>
                      <th>Role</th>
                      <th>Access</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td>
                          <b>{u.display_name}</b>
                          <small>{u.email}</small>
                        </td>
                        <td>{u.role.replaceAll("_", " ")}</td>
                        <td>
                          <span className="badge">
                            {!u.active
                              ? "DISABLED"
                              : u.must_reset_password
                                ? "INVITED"
                                : "ACTIVE"}
                          </span>
                        </td>
                        <td>
                          {u.active && u.must_reset_password && (
                            <button
                              className="ghost"
                              disabled={busy}
                              onClick={() =>
                                void work(async () => {
                                  await call(
                                    `/api/v1/users/${u.id}/reissue-invite`,
                                    {
                                      method: "POST",
                                      body: JSON.stringify({
                                        reason:
                                          "Administrator requested invitation resend",
                                      }),
                                    },
                                    mode,
                                  );
                                  setNotice(
                                    "New invitation queued; previous links are invalid.",
                                  );
                                })
                              }
                            >
                              Resend invite
                            </button>
                          )}
                          <button
                            className="ghost"
                            disabled={busy}
                            onClick={() => {
                              const reason = prompt(
                                "Reason for changing access (at least 5 characters):",
                              );
                              if (reason && reason.length >= 5)
                                void work(async () => {
                                  await call(
                                    "/api/v1/users/" + u.id,
                                    {
                                      method: "PATCH",
                                      headers: {
                                        "If-Match": String(u.version),
                                      },
                                      body: JSON.stringify({
                                        display_name: u.display_name,
                                        role: u.role,
                                        active: !u.active,
                                        work_mode: u.work_mode,
                                        reason,
                                      }),
                                    },
                                    mode,
                                  );
                                  await load();
                                  setNotice("Employee access updated.");
                                });
                            }}
                          >
                            {u.active ? "Disable" : "Enable"}
                          </button>
                          <select
                            aria-label={"Role for " + u.display_name}
                            value={u.role}
                            disabled={busy}
                            onChange={(e) => {
                              const role = e.target.value;
                              const reason = prompt(
                                "Reason for role change (at least 5 characters):",
                              );
                              if (reason && reason.length >= 5)
                                void work(async () => {
                                  await call(
                                    "/api/v1/users/" + u.id,
                                    {
                                      method: "PATCH",
                                      headers: {
                                        "If-Match": String(u.version),
                                      },
                                      body: JSON.stringify({
                                        display_name: u.display_name,
                                        role,
                                        active: u.active,
                                        work_mode: u.work_mode,
                                        reason,
                                      }),
                                    },
                                    mode,
                                  );
                                  await load();
                                  setNotice(
                                    "Role updated. Employee sessions were revoked.",
                                  );
                                });
                            }}
                          >
                            {[
                              "COMPANY_ADMIN",
                              "DISPATCHER",
                              "ENGINEER",
                              "SALES",
                            ].map((r) => (
                              <option key={r}>{r}</option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="hint">
                  Showing up to 100 employees. Larger rosters are available
                  through the paginated API.
                </p>
              </div>
            ) : (
              <div className="empty">
                <h3>Welcome, {profile?.user.display_name}</h3>
                <p>
                  Your account is active. Attendance, tickets and sales screens
                  arrive in Phase 3.
                </p>
              </div>
            )}
          </section>
        )}
        {page === "invite" && (
          <form className="panel form-panel narrow" onSubmit={inviteEmployee}>
            <h2>Employee invitation</h2>
            <Field label="Full name" name="name" required />
            <Field label="Email" name="email" type="email" required />
            <label className="field">
              <span>Role</span>
              <select name="role">
                {["ENGINEER", "SALES", "DISPATCHER", "COMPANY_ADMIN"].map(
                  (r) => (
                    <option key={r}>{r}</option>
                  ),
                )}
              </select>
            </label>
            <label className="field">
              <span>Work mode</span>
              <select name="work_mode">
                <option>FIELD</option>
                <option>OFFICE</option>
              </select>
            </label>
            <p className="hint">
              Uses the company’s first configured branch and shift. Invitation
              links expire after 24 hours.
            </p>
            <button disabled={busy}>Queue invitation</button>
          </form>
        )}
        {page === "audit" && (
          <section className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id}>
                    <td>{new Date(a.occurred_at).toLocaleString()}</td>
                    <td>{a.action.replaceAll("_", " ")}</td>
                    <td>
                      <code>{a.target_tenant_id || a.entity_id || "—"}</code>
                    </td>
                    <td>{a.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!audit.length && <p className="empty">No activity recorded.</p>}
          </section>
        )}
        <footer>
          Telite CRM · Phase 2 administration{" "}
          <span>Company data stays within its authorized workspace.</span>
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
