import { useEffect, useState } from "react";
import { Field } from "../components/Field";
import { Signature, imageData } from "../components/Signature";
import { get, post, form } from "./client";
export function CustomerFields() {
  return (
    <>
      <Field label="Customer name" name="customer_name" required />
      <Field
        label="Customer phone"
        name="customer_phone"
        minLength={5}
        required
      />
      <Field label="Site address" name="address" required />
      <Field
        label="Site latitude"
        name="site_lat"
        type="number"
        step="any"
        min={-90}
        max={90}
        required
      />
      <Field
        label="Site longitude"
        name="site_lng"
        type="number"
        step="any"
        min={-180}
        max={180}
        required
      />
    </>
  );
}
const next: Record<string, string[]> = {
  ASSIGNED: ["EN_ROUTE"],
  EN_ROUTE: ["ON_SITE"],
  ON_SITE: ["IN_PROGRESS"],
  IN_PROGRESS: ["WAITING_SPARES", "WAITING_APPROVAL", "RESOLVED"],
  WAITING_SPARES: ["IN_PROGRESS"],
  WAITING_APPROVAL: ["IN_PROGRESS"],
};
export function Tickets({ profile, run, locate }: any) {
  const [rows, setRows] = useState<any[]>([]),
    [selected, setSelected] = useState<any>(null),
    [engineers, setEngineers] = useState<any[]>([]),
    [creating, setCreating] = useState(false),
    [signature, setSignature] = useState(""),
    [photo, setPhoto] = useState(""),
    [offset, setOffset] = useState(0);
  const [payments, setPayments] = useState<any[]>([]);
  const manager = ["COMPANY_ADMIN", "DISPATCHER"].includes(profile.user.role);
  async function load() {
    setRows((await get(`/tickets?offset=${offset}`)).data);
    if (manager) setEngineers((await get("/dispatch/employees")).data);
  }
  useEffect(() => {
    void run(load);
  }, [offset]);
  async function refresh() {
    await load();
    if (selected) setSelected(await get("/tickets/" + selected.id));
  }
  return (
    <>
      <section className="panel form-panel">
        <h2>Service tickets</h2>
        {manager && (
          <button onClick={() => setCreating(!creating)}>
            {creating ? "Close intake" : "Create ticket"}
          </button>
        )}
        {rows.map((t) => (
          <button
            className="work-card ticket-card"
            key={t.id}
            onClick={() =>
              void run(async () => {
                setSelected(await get("/tickets/" + t.id));
                setPayments((await get(`/tickets/${t.id}/payments`)).data);
                setSignature("");
                setPhoto("");
              })
            }
          >
            <b>
              #{t.number} · {t.customer_name}
            </b>
            <span>{t.reported_issue}</span>
            <span>
              {t.status.replaceAll("_", " ")} · {t.priority}
            </span>
            <small>
              {t.category} · {t.serial_number}
            </small>
          </button>
        ))}
        {!rows.length && <p>No service tickets assigned.</p>}
        <div className="actions">
          <button disabled={!offset} onClick={() => setOffset(offset - 25)}>
            Previous tickets
          </button>
          <button
            disabled={rows.length < 25}
            onClick={() => setOffset(offset + 25)}
          >
            Next tickets
          </button>
        </div>
      </section>
      {creating && (
        <form
          className="panel form-panel"
          onSubmit={(e) => {
            const f = form(e);
            void run(async () => {
              await post("/tickets", {
                ...f,
                site_lat: Number(f.site_lat),
                site_lng: Number(f.site_lng),
                estimated_cost: String(f.estimated_cost || 0),
                assigned_to: f.assigned_to || null,
                warranty_until: f.warranty_until || null,
              });
              setCreating(false);
              await load();
            });
          }}
        >
          <h2>Hardware intake</h2>
          <CustomerFields />
          <label className="field">
            Hardware category
            <select name="category">
              {[
                "Laptop",
                "Desktop",
                "CCTV",
                "Printer",
                "UPS",
                "Networking",
                "Other",
              ].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <Field label="Brand" name="brand" />
          <Field label="Model" name="model" />
          <Field label="Serial number" name="serial_number" required />
          <label className="field">
            Scan serial barcode (camera image)
            <input
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(e) => {
                const file = e.target.files?.[0],
                  input = e.currentTarget.form?.elements.namedItem(
                    "serial_number",
                  ) as HTMLInputElement;
                if (file)
                  void run(async () => {
                    const Detector = (window as any).BarcodeDetector;
                    if (!Detector)
                      throw new Error(
                        "Camera scanning is unavailable here. Enter the serial number manually.",
                      );
                    const bitmap = await createImageBitmap(file);
                    try {
                      const found = await new Detector().detect(bitmap);
                      if (!found.length)
                        throw new Error(
                          "No barcode found. Enter the serial manually.",
                        );
                      input.value = found[0].rawValue;
                    } finally {
                      bitmap.close();
                    }
                  });
              }}
            />
          </label>
          <Field label="Warranty until" name="warranty_until" type="date" />
          <label className="field">
            Coverage
            <select name="coverage">
              <option>CHARGEABLE</option>
              <option>WARRANTY</option>
              {profile.features.amc_tracker && <option>AMC</option>}
            </select>
          </label>
          <Field
            label="Issue description"
            name="reported_issue"
            required
            minLength={5}
          />
          <Field
            label="Estimated charges"
            name="estimated_cost"
            type="number"
            min={0}
            step="0.01"
            defaultValue={0}
          />
          <label className="field">
            Priority
            <select name="priority">
              {["NORMAL", "HIGH", "URGENT", "LOW"].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Assign engineer
            <select name="assigned_to">
              <option value="">Unassigned</option>
              {engineers.map((u) => (
                <option value={u.id} key={u.id}>
                  {u.display_name}
                </option>
              ))}
            </select>
          </label>
          <button>Save ticket</button>
        </form>
      )}
      {selected && (
        <section className="panel form-panel">
          <button className="ghost" onClick={() => setSelected(null)}>
            Close ticket details
          </button>
          <h2>
            #{selected.number} · {selected.status}
          </h2>
          <p>
            {selected.customer.name} · {selected.customer.phone}
          </p>
          <p>{selected.site.address}</p>
          <p>{selected.reported_issue}</p>
          {manager && ["NEW", "ASSIGNED"].includes(selected.status) && (
            <form
              onSubmit={(e) => {
                const f = form(e);
                void run(async () => {
                  await post(
                    `/tickets/${selected.id}/assign`,
                    {
                      user_id: f.user_id,
                      reason: "Dispatcher assigned service engineer",
                    },
                    selected.version,
                  );
                  await refresh();
                });
              }}
            >
              <label className="field">
                Engineer
                <select name="user_id" required>
                  <option value="">Select engineer</option>
                  {engineers.map((u) => (
                    <option value={u.id} key={u.id}>
                      {u.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <button>Assign engineer</button>
            </form>
          )}
          {selected.assigned_to === profile.user.id &&
            next[selected.status] && (
              <form
                onSubmit={(e) => {
                  const f = form(e);
                  void run(async () => {
                    const status = String(f.status),
                      location = status === "ON_SITE" ? await locate() : null;
                    await post(
                      `/tickets/${selected.id}/transition`,
                      { ...f, location },
                      selected.version,
                    );
                    await refresh();
                  });
                }}
              >
                <label className="field">
                  Next status
                  <select name="status">
                    {next[selected.status].map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                </label>
                <Field label="Work notes" name="note" required minLength={5} />
                <button>Update ticket status</button>
              </form>
            )}
          {["IN_PROGRESS", "WAITING_SPARES"].includes(selected.status) && (
            <form
              onSubmit={(e) => {
                const f = form(e);
                void run(async () => {
                  await post(
                    `/tickets/${selected.id}/parts`,
                    { ...f, quantity: Number(f.quantity) },
                    selected.version,
                  );
                  await refresh();
                });
              }}
            >
              <h3>External spare / vendor RMA log</h3>
              <Field label="Part name" name="name" required />
              <Field
                label="Quantity"
                name="quantity"
                type="number"
                min={1}
                defaultValue={1}
                required
              />
              <Field
                label="Unit cost"
                name="unit_cost"
                type="number"
                min={0}
                step="0.01"
                required
              />
              <Field label="Vendor RMA status" name="vendor_rma_status" />
              <Field label="Part notes" name="note" minLength={5} required />
              <button>Log spare or RMA update</button>
            </form>
          )}
          {selected.status === "RESOLVED" &&
            selected.assigned_to === profile.user.id && (
              <form
                onSubmit={(e) => {
                  const f = form(e);
                  void run(async () => {
                    if (!photo || !signature)
                      throw new Error(
                        "Completion photo and customer signature are required.",
                      );
                    const location = await locate();
                    const p = await post(`/tickets/${selected.id}/evidence`, {
                      kind: "AFTER",
                      image_base64: photo,
                    });
                    const s = await post(`/tickets/${selected.id}/evidence`, {
                      kind: "SIGNATURE",
                      image_base64: signature,
                    });
                    await post(
                      `/tickets/${selected.id}/complete`,
                      {
                        ...f,
                        customer_consent: true,
                        photo_id: p.id,
                        signature_id: s.id,
                        location,
                      },
                      selected.version,
                    );
                    setSignature("");
                    setPhoto("");
                    await refresh();
                  });
                }}
              >
                <h3>Customer closure</h3>
                <Field
                  label="Resolution notes shown to customer"
                  name="resolution_notes"
                  value={selected.resolution_notes || ""}
                  readOnly
                  required
                  minLength={5}
                />
                <label className="field">
                  Completion photo
                  <input
                    type="file"
                    accept="image/jpeg,image/png"
                    capture="environment"
                    required
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      setPhoto("");
                      if (file)
                        void run(async () => setPhoto(await imageData(file)));
                    }}
                  />
                </label>
                {photo && <p role="status">Completion photo ready</p>}
                <Signature onChange={setSignature} />
                <Field
                  label="Customer signer name"
                  name="signer_name"
                  minLength={2}
                  required
                />
                <label className="check">
                  <input type="checkbox" required />
                  Customer acknowledges this resolution and agrees to sign.
                </label>
                <label className="field">
                  Payment collection mode
                  <select name="payment_mode">
                    {["CASH", "UPI", "CREDIT", "WARRANTY"].map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                </label>
                <Field
                  label="Amount collected (unverified)"
                  name="collected_amount"
                  type="number"
                  min={0}
                  step="0.01"
                  defaultValue={0}
                />
                <Field label="Payment reference" name="payment_reference" />
                <button>Complete service ticket</button>
              </form>
            )}
          <h3>Service history</h3>
          {selected.events.map((v: any) => (
            <article key={v.id} className="work-card">
              <b>{v.to_status}</b>
              <p>{v.note}</p>
              <small>
                {new Date(v.occurred_at).toLocaleString()}
                {v.location_id ? " · GPS recorded" : ""}
              </small>
            </article>
          ))}
        </section>
      )}
    </>
  );
}
