import { DjEngineClient } from "../src/services/dj-engine/client";
const initial = { active: true, stopping: true, path: "/test.wav", startedAt: "test", elapsedMs: 1000, error: null };
async function check() {
  const client = new DjEngineClient();
  const internal = client as unknown as { sessionId: string };
  internal.sessionId = "recording-session";
  let polls = 0;
  Object.assign(client, {
    send: async () => initial,
    refreshSnapshot: async () => ({ recording: ++polls < 2 ? { ...initial, active: false } : { ...initial, active: false, stopping: false } }),
  });
  const finished = await client.stopRecording();
  if (polls !== 2 || finished.stopping || finished.active) throw new Error("Returned before encoder finalization");
  Object.assign(client, {
    refreshSnapshot: async () => { internal.sessionId = "new-session"; return { recording: { ...initial, active: false, stopping: false } }; },
  });
  let rejected = false;
  try { await client.stopRecording(); } catch { rejected = true; }
  if (!rejected) throw new Error("Engine replacement was mistaken for completed recording");
  return { passed: true, checks: 2 };
}
void check().then(result => { document.querySelector('#result')!.textContent = JSON.stringify(result); }, error => { document.querySelector('#result')!.textContent = JSON.stringify({ passed: false, error: String(error) }); });
