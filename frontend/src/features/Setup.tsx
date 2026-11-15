import { useEffect, useState } from "react";
import { Field } from "../components/Field";
import { get, post, patch, form } from "./client";
export function Setup({ run }: any) {
  const [data, setData] = useState<any>({ branches: [], shifts: [] }),
    [users, setUsers] = useState<any[]>([]);
  async function load() {
    setData(await get("/workforce/settings"));
    setUsers((await get("/users?limit=100")).data);
  }
  useEffect(() => {
    void run(load);
  }, []);
  return (
    <>
      <h2>Office geofences & shifts</h2>
      {[...data.branches, null].map((b: any, i: number) => (
        <form
          className="panel form-panel"
          key={"b" + i + ":" + b?.version}
          onSubmit={(e) => {
            const f = form(e);
            void run(async () => {
              const body = {
                ...f,
                lat: Number(f.lat),
                lng: Number(f.lng),
                radius_m: Number(f.radius_m),
              };
              if (b) await patch("/branches/" + b.id, body, b.version);
              else await post("/branches", body);
              await load();
            });
          }}
        >
          <h3>{b ? b.name : "Add branch"}</h3>
          <Field
            label="Branch name"
            name="name"
            defaultValue={b?.name}
            required
          />
          <Field
            label="Office address"
            name="address"
            defaultValue={b?.address}
            required
          />
          <Field
            label="Office latitude"
            name="lat"
            type="number"
            step="any"
            defaultValue={b?.lat}
            required
          />
          <Field
            label="Office longitude"
            name="lng"
            type="number"
            step="any"
            defaultValue={b?.lng}
            required
          />
          <Field
            label="Geofence radius (metres)"
            name="radius_m"
            type="number"
            min={25}
            max={5000}
            defaultValue={b?.radius_m || 150}
          />
          <button>{b ? "Save branch" : "Add branch"}</button>
        </form>
      ))}
      {[...data.shifts, null].map((s: any, i: number) => (
        <form
          className="panel form-panel"
          key={"s" + i + ":" + s?.version}
          onSubmit={(e) => {
            const f = form(e);
            void run(async () => {
              const body = {
                ...f,
                end_day_offset: Number(f.end_day_offset),
                grace_minutes: Number(f.grace_minutes),
                weekdays: String(f.weekdays).split(",").map(Number),
              };
              if (s) await patch("/shifts/" + s.id, body, s.version);
              else await post("/shifts", body);
              await load();
            });
          }}
        >
          <h3>{s ? s.name : "Add shift"}</h3>
          <Field
            label="Shift name"
            name="name"
            defaultValue={s?.name}
            required
          />
          <Field
            label="Shift start"
            name="start_local"
            type="time"
            defaultValue={s?.start_local || "09:30"}
            required
          />
          <Field
            label="Shift end"
            name="end_local"
            type="time"
            defaultValue={s?.end_local || "18:30"}
            required
          />
          <label className="field">
            End day
            <select name="end_day_offset" defaultValue={s?.end_day_offset || 0}>
              <option value="0">Same day</option>
              <option value="1">Following day</option>
            </select>
          </label>
          <Field
            label="Grace period minutes"
            name="grace_minutes"
            type="number"
            min={0}
            max={120}
            defaultValue={s?.grace_minutes ?? 15}
          />
          <Field
            label="ISO weekdays (Monday=1, comma separated)"
            name="weekdays"
            defaultValue={s?.weekdays.join(",") || "1,2,3,4,5,6"}
            required
          />
          <button>{s ? "Save shift" : "Add shift"}</button>
        </form>
      ))}
      <form
        className="panel form-panel"
        onSubmit={(e) => {
          const f = form(e),
            user = users.find((u) => u.id === f.user_id);
          void run(async () => {
            await patch(
              `/users/${user.id}/schedule`,
              {
                branch_id: f.branch_id,
                shift_id: f.shift_id,
                reason: f.reason,
              },
              user.version,
            );
            await load();
          });
        }}
      >
        <h3>Employee branch & shift</h3>
        <label className="field">
          Employee
          <select name="user_id" required>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Branch
          <select name="branch_id" required>
            {data.branches.map((b: any) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Shift
          <select name="shift_id" required>
            {data.shifts.map((s: any) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <Field
          label="Schedule change reason"
          name="reason"
          minLength={5}
          required
        />
        <button>Save employee schedule</button>
      </form>
    </>
  );
}
