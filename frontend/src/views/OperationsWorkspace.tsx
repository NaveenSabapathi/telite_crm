import { useEffect, useState } from "react";
import { Attendance } from "../features/Attendance";
import { Tickets } from "../features/Tickets";
import { Leads } from "../features/Leads";
import { Setup } from "../features/Setup";
import { Dashboard } from "../features/Dashboard";
import { Field } from "../components/Field";
import { useLocation } from "../components/LocationDisclosure";
import { get, post, form } from "../features/client";
export function OperationsWorkspace({ profile, onAdmin, onLogout }: any) {
  const admin = profile.user.role === "COMPANY_ADMIN",
    desktop = admin || profile.user.role === "DISPATCHER";
  const [tab, setTab] = useState(
      admin ? "Dashboard" : desktop ? "Service Tickets" : "Attendance",
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [alerts, setAlerts] = useState<any[]>([]),
    [shift, setShift] = useState<any>(null);
  const { locate, modal, message } = useLocation();
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      if (profile.features.attendance_gps)
        setShift(await get("/attendance/status"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void run(async () => {
      setAlerts((await get("/notifications")).data);
      if (profile.features.attendance_gps)
        setShift(await get("/attendance/status"));
    });
  }, [tab]);
  const tabs = desktop
    ? [
        ...(admin ? ["Dashboard", "Employees", "Setup"] : []),
        "Attendance",
        "Service Tickets",
        ...(admin ? ["Leads (CRM)"] : []),
        "Profile",
      ]
    : ["Attendance", "Service Tickets", "Leads (CRM)", "Profile"];
  const nav = (
    <nav
      aria-label={desktop ? "Company navigation" : "Employee navigation"}
      className={desktop ? "" : "bottom-nav"}
    >
      {tabs.map((t) => (
        <button
          key={t}
          aria-current={tab === t ? "page" : undefined}
          className={tab === t ? "nav active" : "nav"}
          onClick={() => (t === "Employees" ? onAdmin() : setTab(t))}
        >
          {t}
        </button>
      ))}
    </nav>
  );
  return (
    <div className={desktop ? "shell operations" : "employee-app"}>
      {desktop && (
        <aside className="sidebar">
          <div className="brand">
            T
            <span>
              Telite CRM<small>COMPANY OPERATIONS</small>
            </span>
          </div>
          {nav}
          <div className="sidebar-foot">
            <button className="nav" onClick={() => void run(onLogout)}>
              Sign out
            </button>
          </div>
        </aside>
      )}
      <main className={desktop ? "content" : "mobile-content"}>
        <header className="shift-status">
          <div>
            <small>{profile.tenant.name}</small>
            <b>{profile.user.display_name}</b>
            <p>
              {shift
                ? `${shift.work_mode} · ${shift.open ? "Punched in" : "Not punched in"} · ${new Date(shift.scheduled_start).toLocaleTimeString()}`
                : "Work workspace"}
            </p>
            <small>{message}</small>
          </div>
        </header>
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        {busy && <p role="status">Working…</p>}
        <fieldset disabled={busy} className="workflow-body">
          {tab === "Dashboard" && admin && <Dashboard {...{ profile, run }} />}
          {tab === "Setup" && admin && <Setup {...{ run }} />}
          {tab === "Attendance" &&
            (profile.features.attendance_gps ? (
              <Attendance {...{ profile, run, locate }} />
            ) : (
              <p>Attendance is disabled for your company.</p>
            ))}
          {tab === "Service Tickets" &&
            (profile.features.field_service_tickets &&
            ["COMPANY_ADMIN", "DISPATCHER", "ENGINEER"].includes(
              profile.user.role,
            ) ? (
              <Tickets {...{ profile, run, locate }} />
            ) : (
              <p>Service tickets are unavailable for this role or company.</p>
            ))}
          {tab === "Leads (CRM)" &&
            (profile.features.sales_crm &&
            ["COMPANY_ADMIN", "SALES"].includes(profile.user.role) ? (
              <Leads {...{ profile, run, locate }} />
            ) : (
              <p>CRM is unavailable for this role or company.</p>
            ))}
          {tab === "Profile" && (
            <>
              <section className="panel form-panel">
                <h2>Profile</h2>
                <p>
                  {profile.user.display_name} · {profile.user.email}
                </p>
                <p>{profile.user.role.replaceAll("_", " ")}</p>
                <button onClick={() => void run(onLogout)}>Sign out</button>
                <button
                  className="secondary"
                  onClick={() =>
                    void run(async () => {
                      await post("/me/location-consent", {
                        granted: false,
                        policy_version: "foreground-2026-11",
                      });
                    })
                  }
                >
                  Revoke location consent
                </button>
              </section>
              <form
                className="panel form-panel"
                onSubmit={(e) => {
                  const f = form(e);
                  void run(async () => {
                    await post("/me/deletion-requests", {
                      password: f.password,
                    });
                    window.alert(
                      "Deletion request received. Sessions have been revoked. Your administrator will review retained company records and ownership transfer.",
                    );
                    await onLogout();
                  });
                }}
              >
                <h2>Account & data deletion request</h2>
                <p>
                  Request removal of your account and personal data. Your
                  company must review legitimate record retention and transfer
                  assigned work. This action submits a request and revokes
                  current sessions; it does not claim that erasure is complete.
                </p>
                <Field
                  label="Confirm your password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
                <label className="check">
                  <input type="checkbox" required />I want to request account
                  and personal data deletion.
                </label>
                <button>Request account & data deletion</button>
              </form>
              <section className="panel form-panel">
                <h2>Work notifications</h2>
                {alerts.map((a) => (
                  <article key={a.id} className="work-card">
                    <b>{a.title}</b>
                    <p>{a.body}</p>
                  </article>
                ))}
                {!alerts.length && <p>No notifications.</p>}
              </section>
            </>
          )}
        </fieldset>
      </main>
      {!desktop && nav}
      {modal}
    </div>
  );
}
