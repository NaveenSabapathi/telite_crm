import { useRef, useState } from "react";
import { post } from "../features/client";
export function useLocation() {
  const [visible, setVisible] = useState(false);
  const [message, setMessage] = useState(
    "Location requested only for work actions",
  );
  const pending = useRef<{
    resolve: (v: any) => void;
    reject: (e: Error) => void;
  } | null>(null);
  const locate = () =>
    new Promise<any>((resolve, reject) => {
      pending.current = { resolve, reject };
      setVisible(true);
    });
  async function agree() {
    try {
      await post("/me/location-consent", {
        granted: true,
        policy_version: "foreground-2026-11",
      });
      setVisible(false);
      setMessage("Getting a fresh GPS fix…");
      if (!navigator.geolocation)
        throw new Error("Location is unavailable on this device.");
      navigator.geolocation.getCurrentPosition(
        (position) => {
          let installation = sessionStorage.getItem("telite-installation");
          if (!installation) {
            installation = crypto.randomUUID();
            sessionStorage.setItem("telite-installation", installation);
          }
          setMessage("GPS fix captured for this action");
          pending.current?.resolve({
            client_event_id: crypto.randomUUID(),
            lat: position.coords.latitude,
            lng: position.coords.longitude,
            accuracy_meters: position.coords.accuracy,
            captured_at: new Date(position.timestamp).toISOString(),
            installation_id: installation,
            platform: "web",
          });
          pending.current = null;
        },
        () => {
          setMessage(
            "Location unavailable — check device permission and retry.",
          );
          pending.current?.reject(
            new Error(
              "Location permission denied or GPS unavailable. Your form is preserved.",
            ),
          );
          pending.current = null;
        },
        { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 },
      );
    } catch (e) {
      setVisible(false);
      pending.current?.reject(e as Error);
      pending.current = null;
    }
  }
  const modal = visible ? (
    <div className="modal-scrim">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="location-title"
        className="disclosure"
      >
        <h2 id="location-title">Location for work check-ins</h2>
        <p>
          Telite CRM collects your foreground location when you punch
          attendance, arrive at or complete a customer job, or record a sales
          visit. Your company administrator can view these work locations and
          timestamps.
        </p>
        <p>
          No background location is collected. You can decline; other screens
          remain available. Contact your administrator for a reviewed attendance
          or service exception.
        </p>
        <button onClick={() => void agree()}>Agree and continue</button>
        <button
          className="secondary"
          onClick={() => {
            setVisible(false);
            pending.current?.reject(
              new Error("Location declined. Other features remain available."),
            );
            pending.current = null;
          }}
        >
          Not now
        </button>
      </section>
    </div>
  ) : null;
  return { locate, modal, message };
}
