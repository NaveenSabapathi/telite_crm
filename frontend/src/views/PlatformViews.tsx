import { Field } from "../components/Field";
import { call } from "../api";
export function PlatformViews({
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
}: any) {
  return (
    <>
      {" "}
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
              <button onClick={() => setPage("create")}>＋ Add company</button>
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
                  {tenants.map((t: any) => (
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
            <Field label="Company name" name="name" required maxLength={150} />
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
                  <span>{String(label)}</span>
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
              {selected.admins.map((a: any) => (
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
    </>
  );
}
