import { Field } from "../components/Field";
import { call } from "../api";
export function CompanyViews({
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
}: any) {
  return (
    <>
      {" "}
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
                  {users.map((u: any) => (
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
              {["ENGINEER", "SALES", "DISPATCHER", "COMPANY_ADMIN"].map((r) => (
                <option key={r}>{r}</option>
              ))}
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
              {audit.map((a: any) => (
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
    </>
  );
}
