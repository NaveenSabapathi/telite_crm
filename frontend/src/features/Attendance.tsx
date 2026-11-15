import { useEffect, useState } from "react";
import { Field } from "../components/Field";
import { get, post, form } from "./client";
export function Attendance({
  profile,
  run,
  locate,
}: {
  profile: any;
  run: (fn: () => Promise<void>) => Promise<void>;
  locate: () => Promise<any>;
}) {
  const [status, setStatus] = useState<any>(null),
    [rows, setRows] = useState<any[]>([]),
    [leaves, setLeaves] = useState<any[]>([]);
  const load = async () => {
    const [s, a, l] = await Promise.all([
      get("/attendance/status"),
      get("/attendance"),
      get("/leave-requests"),
    ]);
    setStatus(s);
    setRows(a.data);
    setLeaves(l.data);
  };
  useEffect(() => {
    void run(load);
  }, []);
  return (
    <>
      <section className="panel form-panel">
        <h2>Attendance</h2>
        <p>
          {status?.branch} · {status?.work_mode}
        </p>
        <p>
          Shift:{" "}
          {status
            ? new Date(status.scheduled_start).toLocaleTimeString()
            : "Loading…"}{" "}
          – {status ? new Date(status.scheduled_end).toLocaleTimeString() : ""}
        </p>
        <strong>
          {status?.open ? "Shift in progress" : "Ready for your shift"}
        </strong>
        <div className="actions">
          <button
            disabled={!status}
            onClick={() =>
              void run(async () => {
                const location = await locate();
                if (status.open)
                  await post(
                    `/attendance/${status.open.id}/punch-out`,
                    { location },
                    status.open.version,
                  );
                else
                  await post("/attendance/punch-in", {
                    location,
                    work_mode: status.work_mode,
                  });
                await load();
              })
            }
          >
            {status?.open ? "Punch out" : "Punch in"}
          </button>
        </div>
      </section>
      <section className="panel form-panel">
        <h2>Recent attendance</h2>
        {rows.map((r) => (
          <article className="work-card" key={r.id}>
            <b>
              {r.display_name} · {r.shift_date}
            </b>
            <p>
              {r.status} ·{" "}
              {r.late_minutes > 0 ? `LATE (${r.late_minutes} min)` : "On time"}{" "}
              · {r.work_mode}
            </p>
          </article>
        ))}
        {!rows.length && <p>No attendance recorded.</p>}
      </section>
      <form
        className="panel form-panel"
        onSubmit={(e) => {
          const f = form(e);
          void run(async () => {
            await post("/leave-requests", {
              ...f,
              starts_at: new Date(String(f.starts_at)).toISOString(),
              ends_at: new Date(String(f.ends_at)).toISOString(),
            });
            await load();
          });
        }}
      >
        <h2>Leave & permission request</h2>
        <Field label="From" name="starts_at" type="datetime-local" required />
        <Field label="Until" name="ends_at" type="datetime-local" required />
        <label className="field">
          Request type
          <select name="kind">
            {["ANNUAL", "SICK", "HALF_DAY", "PERMISSION", "ON_DUTY"].map(
              (v) => (
                <option key={v}>{v}</option>
              ),
            )}
          </select>
        </label>
        <Field label="Reason" name="reason" minLength={5} required />
        <button>Submit request</button>
      </form>
      <section className="panel form-panel">
        <h2>Leave requests</h2>
        {leaves.map((l) => (
          <article className="work-card" key={l.id}>
            <b>
              {l.display_name} · {l.kind}
            </b>
            <p>
              {l.reason} · {l.status}
            </p>
            <p>
              {new Date(l.starts_at).toLocaleString()} –{" "}
              {new Date(l.ends_at).toLocaleString()}
            </p>
            {profile.user.role === "COMPANY_ADMIN" &&
              l.status === "PENDING" &&
              l.user_id !== profile.user.id && (
                <div className="actions">
                  {["APPROVED", "REJECTED"].map((decision) => (
                    <button
                      key={decision}
                      onClick={() =>
                        void run(async () => {
                          await post(
                            `/leave-requests/${l.id}/decision`,
                            {
                              decision,
                              reason: `Administrator ${decision.toLowerCase()} request`,
                            },
                            l.version,
                          );
                          await load();
                        })
                      }
                    >
                      {decision === "APPROVED" ? "Approve" : "Reject"}
                    </button>
                  ))}
                </div>
              )}
          </article>
        ))}
      </section>
    </>
  );
}
