import { useEffect, useState } from "react";
import { Field } from "../components/Field";
import { CustomerFields } from "./Tickets";
import { get, post, form } from "./client";
export function Leads({ profile, run, locate }: any) {
  const [rows, setRows] = useState<any[]>([]),
    [selected, setSelected] = useState<any>(null),
    [reps, setReps] = useState<any[]>([]),
    [creating, setCreating] = useState(false),
    [offset, setOffset] = useState(0);
  async function load() {
    setRows((await get(`/leads?offset=${offset}`)).data);
    if (profile.user.role === "COMPANY_ADMIN")
      setReps((await get("/sales/employees")).data);
  }
  useEffect(() => {
    void run(load);
  }, [offset]);
  async function refresh() {
    await load();
    if (selected) setSelected(await get("/leads/" + selected.id));
  }
  return (
    <>
      <section className="panel form-panel">
        <h2>Leads (CRM)</h2>
        <button onClick={() => setCreating(!creating)}>
          {creating ? "Close new lead" : "Create lead"}
        </button>
        {rows.map((l) => (
          <button
            className="work-card ticket-card"
            key={l.id}
            onClick={() =>
              void run(async () => setSelected(await get("/leads/" + l.id)))
            }
          >
            <b>{l.customer_name}</b>
            <span>{l.requirement}</span>
            <span>
              {l.stage === "SURVEY_DONE" ? "SITE VISIT" : l.stage} ·{" "}
              {l.currency} {l.estimated_value}
            </span>
            {l.next_followup_at && (
              <small>
                Follow-up {new Date(l.next_followup_at).toLocaleString()}
              </small>
            )}
          </button>
        ))}
        {!rows.length && <p>No leads yet.</p>}
        <div className="actions">
          <button disabled={!offset} onClick={() => setOffset(offset - 25)}>
            Previous leads
          </button>
          <button
            disabled={rows.length < 25}
            onClick={() => setOffset(offset + 25)}
          >
            Next leads
          </button>
        </div>
      </section>
      {creating && (
        <form
          className="panel form-panel"
          onSubmit={(e) => {
            const f = form(e);
            void run(async () => {
              await post("/leads", {
                ...f,
                site_lat: Number(f.site_lat),
                site_lng: Number(f.site_lng),
                assigned_to: f.assigned_to || null,
                next_followup_at: f.next_followup_at
                  ? new Date(String(f.next_followup_at)).toISOString()
                  : null,
              });
              setCreating(false);
              await load();
            });
          }}
        >
          <h2>New sales opportunity</h2>
          <CustomerFields />
          <Field
            label="Requirement"
            name="requirement"
            minLength={5}
            required
          />
          <Field
            label="Estimated value"
            name="estimated_value"
            type="number"
            min={0}
            step="0.01"
            defaultValue={0}
          />
          <Field
            label="Next follow-up"
            name="next_followup_at"
            type="datetime-local"
          />
          <label className="field">
            Lead source
            <select name="source">
              {[
                "PHONE",
                "WALK_IN",
                "WHATSAPP",
                "INDIAMART_WEB",
                "REFERRAL",
                "FIELD_VISIT",
              ].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          {reps.length > 0 && (
            <label className="field">
              Sales representative
              <select name="assigned_to">
                <option value="">Myself</option>
                {reps.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button>Save lead</button>
        </form>
      )}
      {selected && (
        <section className="panel form-panel">
          <button className="ghost" onClick={() => setSelected(null)}>
            Close lead details
          </button>
          <h2>{selected.requirement}</h2>
          <p>{selected.stage}</p>
          {!["WON", "LOST"].includes(selected.stage) && (
            <>
              <form
                onSubmit={(e) => {
                  const f = form(e);
                  void run(async () => {
                    await post(
                      `/leads/${selected.id}/stage`,
                      {
                        ...f,
                        won_value:
                          f.stage === "WON" ? String(f.won_value) : null,
                      },
                      selected.version,
                    );
                    await refresh();
                  });
                }}
              >
                <label className="field">
                  Pipeline stage
                  <select name="stage">
                    {[
                      "CONTACTED",
                      "SURVEY_DONE",
                      "QUOTE_SENT",
                      "NEGOTIATION",
                      "WON",
                      "LOST",
                    ].map((x) => (
                      <option value={x} key={x}>
                        {x === "SURVEY_DONE" ? "SITE VISIT" : x}
                      </option>
                    ))}
                  </select>
                </label>
                <Field
                  label="Stage change reason"
                  name="reason"
                  minLength={5}
                  required
                />
                <Field
                  label="Won value"
                  name="won_value"
                  type="number"
                  min={0}
                  step="0.01"
                  defaultValue={selected.estimated_value}
                />
                <button>Update lead stage</button>
              </form>
              {profile.user.role === "COMPANY_ADMIN" && (
                <form
                  onSubmit={(e) => {
                    const f = form(e);
                    void run(async () => {
                      await post(
                        `/leads/${selected.id}/assign`,
                        {
                          ...f,
                          reason: "Administrator assigned sales representative",
                        },
                        selected.version,
                      );
                      await refresh();
                    });
                  }}
                >
                  <label className="field">
                    Reassign sales representative
                    <select name="user_id" required>
                      <option value="">Select representative</option>
                      {reps.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.display_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button>Assign lead</button>
                </form>
              )}
            </>
          )}
          {selected.stage === "WON" &&
            profile.features.field_service_tickets && (
              <button
                onClick={() =>
                  void run(async () => {
                    const result = await post(
                      `/leads/${selected.id}/convert`,
                      {
                        reported_issue: `Installation: ${selected.requirement}`,
                      },
                      selected.version,
                    );
                    await refresh();
                    window.alert(
                      `Installation ticket #${result.number} is ready for dispatch.`,
                    );
                  })
                }
              >
                Convert won lead to service ticket
              </button>
            )}
          <form
            onSubmit={(e) => {
              const f = form(e);
              void run(async () => {
                const location = f.visit ? await locate() : null;
                await post(
                  `/leads/${selected.id}/activities`,
                  {
                    note: f.note,
                    next_followup_at: f.next_followup_at
                      ? new Date(String(f.next_followup_at)).toISOString()
                      : null,
                    location,
                  },
                  selected.version,
                );
                await refresh();
              });
            }}
          >
            <h3>Follow-up activity</h3>
            <Field label="Follow-up notes" name="note" required />
            <Field
              label="Next follow-up date"
              name="next_followup_at"
              type="datetime-local"
            />
            <label className="check">
              <input type="checkbox" name="visit" />
              Record a GPS site visit
            </label>
            <button>Log follow-up</button>
          </form>
          <h3>Activity history</h3>
          {selected.activities.map((a: any) => (
            <article key={a.id} className="work-card">
              <b>{a.kind}</b>
              <p>{a.note}</p>
              <small>{new Date(a.occurred_at).toLocaleString()}</small>
            </article>
          ))}
        </section>
      )}
    </>
  );
}
