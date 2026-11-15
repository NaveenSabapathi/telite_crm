import { useEffect, useState } from "react";
import { Field } from "../components/Field";
import { get, post, put } from "./client";
import { call } from "../api";
export function Dashboard({ profile, run }: any) {
  const [data, setData] = useState<any>(null),
    [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  useEffect(() => {
    void run(async () => setData(await get("/dashboard")));
  }, []);
  async function download(format: string) {
    const r = await post("/reports", { month });
    const blob = await call(
      `/api/v1/reports/${r.id}/download?format=${format}`,
      {},
      "tenant",
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `telite-${month}.${format}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <>
      <h2>Today's operations</h2>
      <p>
        {data?.date} · {data?.currency}
      </p>
      {["attendance", "service"].map(
        (section) =>
          data?.[section] && (
            <section key={section}>
              <h3>
                {section === "attendance"
                  ? "Attendance"
                  : "Service performance"}
              </h3>
              <div className="metrics">
                {Object.entries(data[section]).map(([k, v]) => (
                  <article key={k}>
                    <span>{k.replaceAll("_", " ")}</span>
                    <strong>{String(v)}</strong>
                  </article>
                ))}
              </div>
            </section>
          ),
      )}
      {data?.crm && (
        <section className="panel form-panel">
          <h3>CRM pipeline</h3>
          {data.crm.map((s: any) => (
            <article className="work-card" key={s.stage}>
              <b>{s.stage}</b>
              <p>
                {s.count} leads · {data.currency} {s.pipeline}
              </p>
            </article>
          ))}
        </section>
      )}
      <section className="panel form-panel">
        <h2>Monthly reports</h2>
        <Field
          label="Report month"
          type="month"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
        />
        <div className="actions">
          <button onClick={() => void run(() => download("csv"))}>
            Download monthly CSV
          </button>
          <button onClick={() => void run(() => download("pdf"))}>
            Download monthly PDF
          </button>
          {profile.features.monthly_email_reports && (
            <button
              onClick={() =>
                void run(async () => {
                  await post("/reports/test-email", { month });
                  window.alert(
                    "Report queued to your verified administrator email.",
                  );
                })
              }
            >
              Email report now
            </button>
          )}
        </div>
        {profile.features.monthly_email_reports && (
          <div className="actions">
            <button
              onClick={() =>
                void run(async () => {
                  await put("/report-settings", { email_enabled: true });
                  window.alert(
                    "Monthly reports enabled for your verified email.",
                  );
                })
              }
            >
              Subscribe to month-end email
            </button>
            <button
              className="secondary"
              onClick={() =>
                void run(async () => {
                  await put("/report-settings", { email_enabled: false });
                  window.alert("Monthly emails disabled.");
                })
              }
            >
              Unsubscribe
            </button>
          </div>
        )}
        <p>
          Reports include enabled modules only. Recorded payments are unverified
          until reconciled. GPS travel is a straight-line estimate.
        </p>
      </section>
    </>
  );
}
