export type WorkspaceInfo = { path: string | null; default: string | null };

export type SettingsInfo = {
  default_workspace: string | null;
  stt_provider: string;
  llm_provider: string;
  tts_provider: string;
  groq_whisper_model: string;
  groq_chat_model: string;
  openai_chat_model: string;
  gemini_chat_model: string;
  has_groq_key: boolean;
  has_openai_key: boolean;
  has_gemini_key: boolean;
  has_elevenlabs_key: boolean;
};

export type SettingsUpdate = Partial<{
  default_workspace: string | null;
  stt_provider: string;
  llm_provider: string;
  tts_provider: string;
  groq_whisper_model: string;
  groq_chat_model: string;
  openai_chat_model: string;
  gemini_chat_model: string;
  groq_api_key: string;
  openai_api_key: string;
  gemini_api_key: string;
  elevenlabs_api_key: string;
}>;

const BASE = "http://localhost:8787";

export async function getWorkspace(): Promise<WorkspaceInfo> {
  const r = await fetch(`${BASE}/api/workspace`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function setWorkspace(path: string): Promise<{ ok: boolean; path: string }> {
  const r = await fetch(`${BASE}/api/workspace`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function listDir(path: string): Promise<{ items: Array<{ name: string; path: string; type: "dir" | "file" }> }> {
  const r = await fetch(`${BASE}/api/fs/list`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function readFile(path: string): Promise<{ content: string }> {
  const r = await fetch(`${BASE}/api/fs/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function writeFile(path: string, content: string): Promise<{ ok: boolean }> {
  const r = await fetch(`${BASE}/api/fs/write`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function getSettings(): Promise<SettingsInfo> {
  const r = await fetch(`${BASE}/api/settings`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function getModels(provider: string): Promise<{ provider: string; models: string[] }> {
  const r = await fetch(`${BASE}/api/models?provider=${encodeURIComponent(provider)}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function updateSettings(patch: SettingsUpdate): Promise<{ ok: boolean; changed: string[] }> {
  const r = await fetch(`${BASE}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function generatePrd(
  name: string,
  goal: string,
  ref_url?: string
): Promise<{ ok: boolean; spoken: string; prd_markdown: string; log: string }> {
  const r = await fetch(`${BASE}/api/agent/prd`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, goal, ref_url }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function applyMany(
  ops: Array<{ path: string; content: string }>,
  overwrite = false
): Promise<{ ok: boolean; count: number }> {
  const r = await fetch(`${BASE}/api/fs/apply_many`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ops, overwrite }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function diffFile(path: string, new_content: string): Promise<{ diff: string }> {
  const r = await fetch(`${BASE}/api/fs/diff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, new_content }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function detectProjects(): Promise<{ ok: boolean; projects: Array<{ root: string; name: string; has_dev: boolean }> }> {
  const r = await fetch(`${BASE}/api/run/detect`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function runStart(project_root: string, port?: number): Promise<{ ok: boolean; id: string; pid: number; url: string; project_root: string }> {
  const r = await fetch(`${BASE}/api/run/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_root, port }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function runList(): Promise<{ ok: boolean; items: Array<{ id: string; project_root: string; port: number; url: string; pid: number | null; running: boolean }> }> {
  const r = await fetch(`${BASE}/api/run/list`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function runLogs(id: string, limit = 300): Promise<{ ok: boolean; id: string; pid: number | null; running: boolean; logs: string[] }> {
  const r = await fetch(`${BASE}/api/run/logs?id=${encodeURIComponent(id)}&limit=${limit}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function runStop(id: string): Promise<{ ok: boolean }> {
  const r = await fetch(`${BASE}/api/run/stop?id=${encodeURIComponent(id)}`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function runClose(id: string): Promise<{ ok: boolean }> {
  const r = await fetch(`${BASE}/api/run/close?id=${encodeURIComponent(id)}`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type AgentChange = { path: string; new_content: string; diff: string };

export async function agent(
  input: string,
  active_file?: string | null,
  selection?: string | null
): Promise<{ spoken: string; log: string; changes: AgentChange[] }> {
  const r = await fetch(`${BASE}/api/agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input, mode: "type", active_file, selection }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
