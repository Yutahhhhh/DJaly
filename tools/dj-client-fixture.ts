// Browser-side IPC failure regression; no native host or user data is used.
import { DjEngineClient } from "../src/services/dj-engine/client";
async function check() {
  const client = new DjEngineClient();
  const internal = client as unknown as { sessionId: string };
  internal.sessionId = "old";
  let reply!: (value: unknown) => void;
  let calls = 0;
  Object.assign(window, { __TAURI_INTERNALS__: { invoke: () => { calls++; return new Promise(resolve => { reply = resolve; }); } } });
  const old = client.send("mixer.master.gain", { gain: 1 }).catch(error => error);
  internal.sessionId = "new";
  reply({ ok: false, error: { code: "session_mismatch", message: "old reply", retryable: false } });
  await old;
  if (client.getState().sessionInvalidated) throw new Error("Old reply invalidated new connection");
  calls = 0;
  const first = client.refreshSnapshot();
  const second = client.refreshSnapshot();
  if (first !== second) throw new Error("Refreshes were not single-flight");
  const settled = Promise.allSettled([first, second]);
  await new Promise(resolve => setTimeout(resolve, 0));
  if (calls !== 1) throw new Error(`Expected one snapshot IPC, got ${calls}`);
  reply({ ok: true, data: {} }); // Invalid response must free the buffer too.
  await settled;
  const retry = client.refreshSnapshot().catch(error => error);
  await new Promise(resolve => setTimeout(resolve, 0));
  if (calls !== 2) throw new Error("Failed snapshot stranded subsequent refresh");
  reply({ ok: true, data: {} });
  await retry;
  return { passed: true, checks: 3 };
}
void check().then(result => { document.querySelector("#result")!.textContent = JSON.stringify(result); }, error => { document.querySelector("#result")!.textContent = JSON.stringify({ passed: false, error: String(error) }); });
