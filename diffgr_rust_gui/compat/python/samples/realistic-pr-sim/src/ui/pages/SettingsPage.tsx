import React from "react";
import { Toast } from "../components/Toast.js";

export function SettingsPage() {
  const [enableAnalytics, setEnableAnalytics] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [toast, setToast] = React.useState<null | { variant: "success" | "error"; message: string }>(null);

  const save = async () => {
    setSaving(true);
    try {
      // Pretend to persist settings.
      await new Promise((r) => window.setTimeout(r, 150));
      setToast({ variant: "success", message: "Saved" });
    } catch {
      setToast({ variant: "error", message: "Save failed" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <h1>Settings</h1>
      <label>
        <input
          type="checkbox"
          checked={enableAnalytics}
          onChange={(e) => setEnableAnalytics(e.target.checked)}
        />
        Enable analytics
      </label>
      <div>
        <button type="button" onClick={save} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </button>
      </div>

      {toast ? <Toast variant={toast.variant} message={toast.message} onClose={() => setToast(null)} /> : null}
    </section>
  );
}

