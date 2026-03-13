import { useEffect, useMemo, useRef, useState } from "react";
import Editor, { DiffEditor } from "@monaco-editor/react";

import "./app.css";
import {
  agent,
  applyMany,
  diffFile,
  getModels,
  getSettings,
  getWorkspace,
  listDir,
  readFile,
  detectProjects,
  runClose,
  runList,
  runLogs,
  runStart,
  generatePrd,
  setWorkspace,
  updateSettings,
  writeFile,
  type AgentChange,
  type SettingsInfo,
} from "./api";

type TreeItem = { name: string; path: string; type: "dir" | "file" };

type Tab = { path: string; content: string; dirty: boolean };

function basename(p: string) {
  const parts = p.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? p;
}

export default function App() {
  const [ws, setWs] = useState<string | null>(null);
  const [wsDefault, setWsDefault] = useState<string | null>(null);

  // Knowledge base status (UIAgent.md)
  const [kbStatus, setKbStatus] = useState<"unindexed" | "indexing" | "ready">("unindexed");
  const [treePath, setTreePath] = useState<string>(".");
  const dirInputRef = useRef<HTMLInputElement | null>(null);

  // resizable panes
  const [leftW, setLeftW] = useState(280);
  const [rightW, setRightW] = useState(420);
  const [bottomH, setBottomH] = useState(260);
  const [tree, setTree] = useState<TreeItem[]>([]);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTab, setActiveTab] = useState<string | null>(null);

  // Omni-bar (UIAgent.md)
  const [omniOpen, setOmniOpen] = useState(false);
  const [omniText, setOmniText] = useState("");
  const omniRef = useRef<HTMLInputElement | null>(null);

  const [agentInput, setAgentInput] = useState("");
  const [agentLog, setAgentLog] = useState("Waiting…");
  const [hasPrd, setHasPrd] = useState(false);

  // Blueprint (plan) area (UIAgent.md)
  type BlueprintStatus = "todo" | "doing" | "done" | "error";
  type BlueprintItem = { id: string; label: string; status: BlueprintStatus };

  const [blueprint, setBlueprint] = useState<string>("- (unplanned)\n");
  const [blueprintChecks, setBlueprintChecks] = useState<BlueprintItem[]>([
    { id: "discover", label: "Discovery: scan context", status: "todo" },
    { id: "draft", label: "Blueprint: propose changes", status: "todo" },
    { id: "execute", label: "Execution: apply changes", status: "todo" },
    { id: "validate", label: "Validation: refresh + check logs", status: "todo" },
  ]);

  // Blueprint editor (Modify Plan)
  const [planOpen, setPlanOpen] = useState(false);
  const [planText, setPlanText] = useState("");

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<SettingsInfo | null>(null);

  const [prdOpen, setPrdOpen] = useState(false);
  const [prdBusy, setPrdBusy] = useState(false);
  const [prdName, setPrdName] = useState("my-product");
  const [prdGoal, setPrdGoal] = useState("");
  const [prdRefUrl, setPrdRefUrl] = useState("");
  const [prdBaseDir, setPrdBaseDir] = useState("");
  const [prdMsg, setPrdMsg] = useState<string>("");

  // Monaco diff editor refs for surgical highlight
  const diffEditorRef = useRef<any>(null);
  const diffDecoRef = useRef<string[]>([]);
  const [runOut, setRunOut] = useState<string>("");
  const runPollRef = useRef<number | null>(null);

  const [projects, setProjects] = useState<Array<{ root: string; name: string; has_dev: boolean }>>([]);
  const [selectedProject, setSelectedProject] = useState<string>(".");
  const [runs, setRuns] = useState<Array<{ id: string; project_root: string; url: string; running: boolean }>>([]);
  const [activeRunId, setActiveRunId] = useState<string>("");
  const [previewUrl, setPreviewUrl] = useState<string>("");

  const [groqModels, setGroqModels] = useState<string[]>([
    // Coding-friendly defaults
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
  ]);

  const [openaiModels, setOpenaiModels] = useState<string[]>([
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-4.1",
    "codex-5.4",
    "codex-5.3",
  ]);

  const [geminiModels, setGeminiModels] = useState<string[]>([
    "gemini-1.5-flash",
    "gemini-1.5-pro",
  ]);

  const modelHints: Record<string, string> = {
    "llama-3.1-8b-instant": "recommended (fast coding)",
    "llama-3.1-70b-versatile": "recommended (best quality)",
    "gpt-4o-mini": "recommended (fast coding)",
    "gpt-4.1": "recommended (best quality)",
    "codex-5.4": "recommended (best coding)",
    "codex-5.3": "recommended (best coding)",
    "gemini-1.5-flash": "recommended (fast coding)",
    "gemini-1.5-pro": "recommended (best quality)",
  };
  const [settingsDraft, setSettingsDraft] = useState({
    default_workspace: "" as string,
    stt_provider: "groq" as string,
    llm_provider: "openai" as string,
    tts_provider: "pyttsx3" as string,
    groq_whisper_model: "whisper-large-v3-turbo" as string,
    groq_chat_model: "llama-3.1-8b-instant" as string,
    openai_chat_model: "gpt-4o-mini" as string,
    gemini_chat_model: "gemini-1.5-flash" as string,
    groq_api_key: "" as string,
    openai_api_key: "" as string,
    gemini_api_key: "" as string,
    elevenlabs_api_key: "" as string,
  });
  const [settingsMsg, setSettingsMsg] = useState<string>("");

  // Agent apply/confirm
  const [pendingChanges, setPendingChanges] = useState<Array<{ path: string; content: string }>>([]);

  // Review & Commit overlay (UIAgent.md)
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewOriginal, setReviewOriginal] = useState<string>("");
  const [reviewProposed, setReviewProposed] = useState<string>("");
  const [reviewDiff, setReviewDiff] = useState<string>("");
  const [reviewPath, setReviewPath] = useState<string>("");

  async function selectReviewFile(path: string) {
    setReviewPath(path);
    const proposed = pendingChanges.find((c) => c.path === path)?.content ?? "";
    setReviewProposed(proposed);
    try {
      const orig = await readFile(path);
      setReviewOriginal(orig.content);
    } catch {
      setReviewOriginal(path === active?.path ? active.content : "");
    }
    try {
      const d = await diffFile(path, proposed);
      setReviewDiff(d.diff);
    } catch {
      setReviewDiff("");
    }
  }


  const active = useMemo(() => tabs.find((t) => t.path === activeTab) ?? null, [tabs, activeTab]);
  const pendingForActive = useMemo(() => {
    if (!active?.path) return null;
    return pendingChanges.find((c) => c.path === active.path) ?? null;
  }, [pendingChanges, active?.path]);

  // apply surgical highlight decorations when showing diff
  useEffect(() => {
    const de = diffEditorRef.current;
    if (!de) return;
    try {
      const modified = de.getModifiedEditor?.();
      if (!modified) return;

      const changes = de.getLineChanges?.() || [];
      const decorations = (changes as any[])
        .flatMap((c) => {
          const start = c.modifiedStartLineNumber;
          const end = c.modifiedEndLineNumber;
          if (!start || !end) return [];
          // if only deletions (end==0), skip
          if (end === 0) return [];
          return [{
            range: {
              startLineNumber: start,
              startColumn: 1,
              endLineNumber: end,
              endColumn: 1,
            },
            options: {
              isWholeLine: true,
              className: "surgicalLine",
            },
          }];
        });

      diffDecoRef.current = modified.deltaDecorations(diffDecoRef.current, decorations);
    } catch {
      // ignore
    }
  }, [pendingForActive?.path, pendingForActive?.content]);

  // Omni-bar shortcut: Ctrl/Cmd + K
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isK = (e.key || "").toLowerCase() === "k";
      if (!isK) return;
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      setOmniOpen(true);
      window.setTimeout(() => omniRef.current?.focus(), 0);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function kbLabel() {
    if (kbStatus === "unindexed") return "🔴 Unindexed";
    if (kbStatus === "indexing") return "🟡 Indexing…";
    return "🟢 Knowledge Base Ready";
  }

  function startDrag(kind: "left" | "right" | "bottom", e: React.MouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startY = e.clientY;
    const initLeft = leftW;
    const initRight = rightW;
    const initBottom = bottomH;

    function onMove(ev: MouseEvent) {
      if (kind === "left") {
        const w = Math.max(200, Math.min(520, initLeft + (ev.clientX - startX)));
        setLeftW(w);
      }
      if (kind === "right") {
        const w = Math.max(280, Math.min(720, initRight - (ev.clientX - startX)));
        setRightW(w);
      }
      if (kind === "bottom") {
        const h = Math.max(180, Math.min(520, initBottom - (ev.clientY - startY)));
        setBottomH(h);
      }
    }

    function onUp() {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    }

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  async function refreshTree(path = treePath) {
    const data = await listDir(path);
    setTree(data.items);
    setHasPrd(data.items.some((i) => i.name === "PRD.md"));
  }

  async function executePrd() {
    try {
      const res = await readFile("PRD.md");
      const fullInstruction = `Tolong implementasikan Product Requirements Document (PRD) berikut menjadi kode aplikasi yang fungsional. 

Tugas utamanya:
1. Buat/update file-file kode yang dibutuhkan (seperti src/App.tsx, src/app.css, dll).
2. Implementasikan fitur dan styling sesuai spek di bawah.
3. JANGAN melakukan perubahan pada file PRD.md itu sendiri.

--- ISI PRD ---
${res.content}`;

      setAgentInput(fullInstruction);
      setAgentLog("Mengirim instruksi PRD ke agent...");

      // Gunakan timeout kecil supaya state agentInput ter-update sebelum runAgent jalan
      setTimeout(() => {
        runAgent();
      }, 100);
    } catch (e) {
      setAgentLog("Gagal baca PRD.md: " + String(e));
    }
  }

  async function pickWorkspace() {
    // web: use folder picker (webkitdirectory)
    dirInputRef.current?.click();
  }

  async function handleDirPick(files: FileList | null) {
    if (!files || files.length === 0) return;

    // best-effort infer top folder name from webkitRelativePath
    const rel = (files[0] as any).webkitRelativePath as string | undefined;
    const top = rel ? rel.split("/")[0] : "";

    // browser cannot provide absolute path; ask user to confirm
    const guess = wsDefault ? `${wsDefault.replace(/\/$/, "")}/${top}` : top || (ws ?? "");
    const p = window.prompt("Open Folder (absolute path)", guess);
    if (!p) return;

    setKbStatus("indexing");
    const res = await setWorkspace(p);
    setWs(res.path);
    setTreePath(".");
    await refreshTree(".");

    try {
      const d = await detectProjects();
      setProjects(d.projects);
      const first = d.projects.find((pp) => pp.has_dev)?.root ?? d.projects[0]?.root ?? ".";
      setSelectedProject(first);
    } catch {
      setProjects([]);
    } finally {
      setKbStatus("ready");
    }
  }

  async function openItem(item: TreeItem) {
    if (item.type === "dir") {
      setTreePath(item.path);
      await refreshTree(item.path);
      return;
    }

    await openPath(item.path);
  }

  async function openPath(path: string) {
    const existing = tabs.find((t) => t.path === path);
    if (existing) {
      setActiveTab(existing.path);
      return;
    }

    const f = await readFile(path);
    const t: Tab = { path, content: f.content, dirty: false };
    setTabs((prev) => [...prev, t]);
    setActiveTab(path);
  }

  async function saveActive() {
    if (!active) return;
    await writeFile(active.path, active.content);
    setTabs((prev) => prev.map((t) => (t.path === active.path ? { ...t, dirty: false } : t)));
    setAgentLog((l) => l + `\n[save] ${active.path}`);
  }

  useEffect(() => {
    (async () => {
      const info = await getWorkspace();
      setWs(info.path);
      setWsDefault(info.default);
      if (info.path) {
        setKbStatus("indexing");
        await refreshTree(".");
        // detect runnable projects
        try {
          const d = await detectProjects();
          setProjects(d.projects);
          // pick first with dev
          const first = d.projects.find((p) => p.has_dev)?.root ?? d.projects[0]?.root ?? ".";
          setSelectedProject(first);
        } catch {
          // ignore
        }
        try {
          const rl = await runList();
          setRuns(rl.items.map((x) => ({ id: x.id, project_root: x.project_root, url: x.url, running: x.running })));
        } catch {
          // ignore
        } finally {
          setKbStatus("ready");
        }
      }
    })().catch((e) => {
      setAgentLog(String(e));
    });
  }, []);

  // poll logs for active run
  useEffect(() => {
    if (!activeRunId) return;
    if (runPollRef.current) window.clearInterval(runPollRef.current);

    const tick = async () => {
      try {
        const l = await runLogs(activeRunId, 200);
        setRunOut(l.logs.join("\n"));
      } catch {
        // ignore
      }
    };

    tick();
    runPollRef.current = window.setInterval(tick, 1000);
    return () => {
      if (runPollRef.current) window.clearInterval(runPollRef.current);
      runPollRef.current = null;
    };
  }, [activeRunId]);


  // Agent status: 'idle' | 'thinking' | 'error'
  const [agentStatus, setAgentStatus] = useState<"idle" | "thinking" | "error">("idle");

  async function runAgent() {
    if (!active?.path) throw new Error("Open a file first (active_file required)");
    setAgentStatus("thinking");
    setAgentLog("Menunggu respons agent...");

    // Phase 2: Blueprint (Drafting)
    setBlueprint(`## Blueprint\n\n- Target: \`${active?.path ?? "(no active file)"}\`\n- Intent: ${agentInput.trim() || "(empty)"}\n\n### Steps\n- [ ] Discovery: scan context\n- [ ] Propose patch (may touch multiple files)\n- [ ] Review diffs\n- [ ] Execute changes\n- [ ] Validate (refresh + logs)\n`);
    setBlueprintChecks((prev) => prev.map((x) => (x.id === "draft" ? { ...x, status: "done" } : x)));

    try {
      const res = await agent(agentInput, active?.path ?? null, null);
      setAgentLog(`${res.log}\n${res.spoken ? `spoken=${res.spoken}` : ""}`.trim());

      // Normalize to pending ops
      const ops = (res.changes || []).map((c) => ({ path: c.path, content: c.new_content }));
      setPendingChanges(ops);

      // Review: default to active file change if present, else first change
      const pick: AgentChange | null =
        (active?.path ? res.changes.find((c) => c.path === active.path) : null) ??
        res.changes[0] ??
        null;

      if (pick) {
        // initialize review selection
        setReviewPath(pick.path);
        const original = pick.path === active.path ? active.content : "";
        setReviewOriginal(original);
        setReviewProposed(pick.new_content);
        setReviewDiff(pick.diff || "");
      }

      // update blueprint with file list
      const files = res.changes.map((c) => `- \`${c.path}\``).join("\n");
      setBlueprint((bp) => `${bp}\n### Files to change\n${files}\n`);

      // open Review & Commit overlay
      setReviewOpen(true);
      setAgentStatus("idle");
    } catch (e) {
      setAgentLog(String(e));
      setAgentStatus("error");
    }
  }

  async function applyPending() {
    if (pendingChanges.length === 0) return;

    // apply all changes
    await applyMany(pendingChanges, true);

    // refresh open tabs if they match
    for (const change of pendingChanges) {
      setTabs((prev) => prev.map((t) => (t.path === change.path ? { ...t, content: change.content, dirty: false } : t)));
    }

    const n = pendingChanges.length;

    // --- AUTO-PILOT LOGIC ---
    try {
      // 1. Cari file utama (prioritas src/App.tsx > App.tsx > src/main.tsx > dst)
      const priorities = ["src/App.tsx", "App.tsx", "src/main.tsx", "src/index.tsx", "index.html"];
      let mainFile = "";
      for (const p of priorities) {
        if (pendingChanges.some((c) => c.path.endsWith(p))) {
          mainFile = pendingChanges.find((c) => c.path.endsWith(p))?.path || "";
          break;
        }
      }
      if (!mainFile && pendingChanges.length > 0) {
        mainFile = pendingChanges[0].path;
      }

      // 2. Deteksi folder project baru
      const firstPath = pendingChanges[0].path;
      const folderMatch = firstPath.split("/")[0];
      if (folderMatch && !firstPath.startsWith("src/") && !firstPath.startsWith("public/")) {
        // Sepertinya ada subfolder baru (scaffold mode)
        setTreePath(folderMatch);
        await refreshTree(folderMatch);

        // 3. Masukin PRD.md ke folder tersebut jika ada
        if (hasPrd) {
          try {
            const prdData = await readFile("PRD.md");
            await writeFile(`${folderMatch}/PRD.md`, prdData.content);
            setAgentLog((l) => l + `\n[docs] PRD.md copied to ${folderMatch}/`);
          } catch (e) {
            console.error("Failed to copy PRD", e);
          }
        }
      } else {
        await refreshTree(treePath);
      }

      // 4. Buka file utama di editor
      if (mainFile) {
        await openPath(mainFile);
      }

      // 5. Scan ulang project biar tombol Preview nyala
      const d = await detectProjects();
      setProjects(d.projects);
      if (d.projects.length > 0 && selectedProject === ".") {
        setSelectedProject(d.projects[0].root);
      }
    } catch (e) {
      console.error("Auto-pilot failed", e);
    }
    // ------------------------

    setPendingChanges([]);
    setReviewOpen(false);
    setBlueprintChecks((prev) => prev.map((x) => (x.id === "execute" ? { ...x, status: "done" } : x)));
    setAgentLog((l) => l + `\n[apply] Applied ${n} file(s)`);
  }

  function rejectPending() {
    setPendingChanges([]);
    setReviewOpen(false);
  }

  function closeTab(path: string) {
    setTabs((prev) => prev.filter((t) => t.path !== path));
    if (activeTab === path) {
      // pick another tab if possible
      const others = tabs.filter((t) => t.path !== path);
      setActiveTab(others[others.length - 1]?.path ?? null);
    }
  }

  async function openSettingsPanel() {
    setSettingsMsg("");
    setSettingsOpen(true);
    try {
      const s = await getSettings();
      setSettings(s);
      setSettingsDraft((d) => ({
        ...d,
        default_workspace: s.default_workspace ?? "",
        stt_provider: s.stt_provider,
        llm_provider: s.llm_provider,
        tts_provider: s.tts_provider,
        groq_whisper_model: s.groq_whisper_model,
        groq_chat_model: s.groq_chat_model ?? "llama-3.1-8b-instant",
        openai_chat_model: s.openai_chat_model,
        gemini_chat_model: s.gemini_chat_model,
        // keep secret inputs blank by default (behavior A)
        groq_api_key: "",
        openai_api_key: "",
        gemini_api_key: "",
        elevenlabs_api_key: "",
      }));
    } catch (e) {
      setSettingsMsg(String(e));
    }
  }

  async function refreshGroqModels() {
    setSettingsMsg("");
    try {
      const res = await getModels("groq");
      if (res.models?.length) {
        setGroqModels(res.models);
        const best = pickBestGroq(res.models);
        if (best) setSettingsDraft((d) => ({ ...d, groq_chat_model: best }));
      }
      setSettingsMsg(`Groq models refreshed (${res.models.length}). Auto‑recommended updated.`);
    } catch (e) {
      setSettingsMsg(String(e));
    }
  }

  function pickBestOpenAI(models: string[]): string | null {
    const priority = ["codex-5.4", "codex-5.3", "gpt-4.1", "gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"];
    for (const p of priority) {
      const found = models.find((m) => m === p || m.startsWith(p));
      if (found) return found;
    }
    return models[0] ?? null;
  }

  function pickBestGroq(models: string[]): string | null {
    const priority = ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"];
    for (const p of priority) {
      const found = models.find((m) => m.startsWith(p));
      if (found) return found;
    }
    return models[0] ?? null;
  }

  function pickBestGemini(models: string[]): string | null {
    const priority = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0", "gemini-3.0", "gemini-3.1"];
    for (const p of priority) {
      const found = models.find((m) => m.startsWith(p));
      if (found) return found;
    }
    return models[0] ?? null;
  }

  async function refreshOpenAIModels() {
    setSettingsMsg("");
    try {
      const res = await getModels("openai");
      if (res.models?.length) {
        setOpenaiModels(res.models);
        const best = pickBestOpenAI(res.models);
        if (best) setSettingsDraft((d) => ({ ...d, openai_chat_model: best }));
      }
      setSettingsMsg(`OpenAI models refreshed (${res.models.length}). Auto‑recommended updated.`);
    } catch (e) {
      setSettingsMsg(String(e));
    }
  }

  async function refreshGeminiModels() {
    setSettingsMsg("");
    try {
      const res = await getModels("gemini");
      if (res.models?.length) {
        setGeminiModels(res.models);
        const best = pickBestGemini(res.models);
        if (best) setSettingsDraft((d) => ({ ...d, gemini_chat_model: best }));
      }
      setSettingsMsg(`Gemini models refreshed (${res.models.length}). Auto‑recommended updated.`);
    } catch (e) {
      setSettingsMsg(String(e));
    }
  }

  async function openPrd() {
    setPrdMsg("");
    setPrdBusy(false);
    setPrdRefUrl("");
    setPrdOpen(true);

    try {
      const s = await getSettings();
      setSettings(s);
      const base = s.default_workspace ?? ws ?? "";
      setPrdBaseDir(base);
    } catch {
      setPrdBaseDir(ws ?? "");
    }
  }

  async function generatePrdFile() {
    if (prdBusy) return;
    setPrdBusy(true);
    setPrdMsg("");

    // progress messages in blueprint
    function upsertTask(id: string, label: string, status: BlueprintStatus) {
      setBlueprintChecks((prev) => {
        const i = prev.findIndex((x) => x.id === id);
        if (i === -1) return [...prev, { id, label, status }];
        const next = [...prev];
        next[i] = { ...next[i], label, status };
        return next;
      });
    }

    try {
      const base = prdBaseDir.trim();
      if (!base) throw new Error("Base folder is required (absolute path)");

      setBlueprint("# PRD Mode\n\nGenerating Product Requirements Document…\n");
      setBlueprintChecks([]);

      upsertTask("ws", "Set workspace", "doing");
      const res = await setWorkspace(base);
      setWs(res.path);
      setTreePath(".");
      await refreshTree(".");
      upsertTask("ws", "Set workspace", "done");

      upsertTask("prd", "Generate PRD (no code)", "doing");
      setPrdMsg("Generating PRD… (this may take a while)");
      const out = await generatePrd(prdName.trim() || "product", prdGoal.trim() || "", prdRefUrl.trim() || undefined);
      upsertTask("prd", "Generate PRD (no code)", "done");

      const filePath = `PRD.md`;
      upsertTask("write", "Write PRD.md", "doing");
      await writeFile(filePath, out.prd_markdown);
      await readFile(filePath);
      upsertTask("write", "Write PRD.md", "done");

      await refreshTree(".");
      await openPath(filePath);

      // Stop agent here (user requested)
      setPrdOpen(false);
      setPrdMsg("PRD.md created. Review it in the editor; use the main Instruction area to execute the app changes.");
    } catch (e) {
      upsertTask("error", "PRD generation failed", "error");
      setPrdMsg(String(e));
      setAgentLog(String(e));
    } finally {
      setPrdBusy(false);
    }
  }

  async function saveSettings() {
    setSettingsMsg("");
    try {
      const changed = await updateSettings({
        default_workspace: settingsDraft.default_workspace,
        stt_provider: settingsDraft.stt_provider,
        llm_provider: settingsDraft.llm_provider,
        tts_provider: settingsDraft.tts_provider,
        groq_whisper_model: settingsDraft.groq_whisper_model,
        groq_chat_model: settingsDraft.groq_chat_model,
        openai_chat_model: settingsDraft.openai_chat_model,
        gemini_chat_model: settingsDraft.gemini_chat_model,
        // Behavior A: backend ignores blank secrets
        groq_api_key: settingsDraft.groq_api_key,
        openai_api_key: settingsDraft.openai_api_key,
        gemini_api_key: settingsDraft.gemini_api_key,
        elevenlabs_api_key: settingsDraft.elevenlabs_api_key,
      });
      const s = await getSettings();
      setSettings(s);
      setSettingsDraft((d) => ({
        ...d,
        groq_api_key: "",
        openai_api_key: "",
        gemini_api_key: "",
        elevenlabs_api_key: "",
      }));
      setSettingsMsg(`Saved. Changed: ${changed.changed.join(", ") || "(none)"}`);

      // reflect default workspace in the open-folder prompt
      setWsDefault(s.default_workspace);
    } catch (e) {
      setSettingsMsg(String(e));
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">Voice IDE</div>
        <div className="spacer" />
        <button className="btn" onClick={() => setOmniOpen(true)} title="Command (Ctrl/Cmd+K)">
          Command…
        </button>
        <button className="btn" onClick={pickWorkspace}>
          Open Folder…
        </button>
        <input
          ref={dirInputRef}
          type="file"
          multiple
          style={{ display: "none" }}
          onChange={(e) => handleDirPick(e.target.files)}
          {...({ webkitdirectory: "true", directory: "true" } as any)}
        />
        <button className="btn" onClick={() => refreshTree(treePath)} disabled={!ws}>
          Refresh
        </button>
        <button className="btn primary" onClick={saveActive} disabled={!active || !active.dirty}>
          Save
        </button>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            className="btn"
            style={{ maxWidth: 180 }}
            value={selectedProject}
            disabled={!ws || projects.length === 0}
            onChange={(e) => setSelectedProject(e.target.value)}
            title="Select project"
          >
            {projects.length === 0 ? <option value=".">No project</option> : null}
            {projects.map((p) => (
              <option key={p.root} value={p.root}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            className="btn primary"
            disabled={!ws}
            onClick={async () => {
              try {
                // VALIDASI: Jika tidak ada project terdeteksi
                if (projects.length === 0 || selectedProject === ".") {
                  alert("⚠️ Peringatan: Project belum terdeteksi di folder ini. Pastikan file seperti package.json sudah ada, atau tunggu Agent selesai membuat project.");
                  return;
                }

                // Cek apakah sudah ada run yang aktif untuk folder ini
                const existing = runs.find(r => r.project_root === selectedProject && r.running);
                if (existing) {
                  setPreviewUrl(existing.url);
                  setActiveRunId(existing.id);
                } else {
                  setAgentLog("Starting dev server for preview... mohon tunggu sebentar.");
                  const r = await runStart(selectedProject);
                  setActiveRunId(r.id);
                  
                  // Kasih jeda sedikit biar server bener-bener up (mencegah download file mentah)
                  setTimeout(() => {
                    setPreviewUrl(r.url);
                  }, 1500);

                  // Update daftar runs
                  const rl = await runList();
                  setRuns(rl.items.map((x) => ({ id: x.id, project_root: x.project_root, url: x.url, running: x.running })));
                }
              } catch (e) {
                setAgentLog("Preview failed: " + String(e));
                alert("Gagal memulai preview: " + String(e));
              }
            }}
            title={!ws ? "Set workspace first" : "Open Web Preview"}
          >
            Preview
          </button>
        </div>

        <button className="btn" onClick={openPrd} title="Plan (PRD)">
          Plan (PRD)…
        </button>
        <button className="btn" onClick={openSettingsPanel} title="Settings">
          Settings
        </button>
        <div className="pill">Mode: Type</div>
      </header>

      <div className="main">
        <aside className="pane left" style={{ width: leftW }}>
          <div className="paneTitle">Files</div>
          {!ws ? (
            <div className="hint">
              No workspace. Click <b>Open Folder…</b>
            </div>
          ) : (
            <>
              <div className="crumb">
                <span className="mono">{ws}</span>
                <span className="mono"> / {treePath}</span>
              </div>
              <div className="list">
                {treePath !== "." && (
                  <div
                    className="item dir"
                    onClick={() => {
                      const up = treePath.split("/").slice(0, -1).join("/") || ".";
                      setTreePath(up);
                      refreshTree(up);
                    }}
                  >
                    ..
                  </div>
                )}
                {tree.map((it) => (
                  <div key={it.path} className={`item ${it.type}`} onClick={() => openItem(it)}>
                    <span className="tag">{it.type === "dir" ? "DIR" : "FILE"}</span>
                    <span className="name">{it.name}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Knowledge Base Status LED */}
          <div className="kbStatus" title="Knowledge Base Status">
            <span className={`kbLed ${kbStatus}`} />
            <span className="kbText">{kbLabel()}</span>
          </div>
        </aside>

        <div className="splitter v" onMouseDown={(e) => startDrag("left", e)} />

        <section className="pane center">
          <div className="tabs">
            {tabs.map((t) => (
              <div
                key={t.path}
                className={`tab ${t.path === activeTab ? "active" : ""}`}
                onClick={() => setActiveTab(t.path)}
              >
                <span>
                  {basename(t.path)}
                  {t.dirty ? " •" : ""}
                </span>
                <button
                  className="tabClose"
                  title="Close"
                  onClick={(e) => {
                    e.stopPropagation();
                    closeTab(t.path);
                  }}
                >
                  ×
                </button>
              </div>
            ))}
            {tabs.length === 0 && <div className="hint">Open a file to start editing.</div>}
          </div>

          <div className="editorWrap">
            {active ? (
              pendingForActive ? (
                <DiffEditor
                  height="100%"
                  original={active.content}
                  modified={pendingForActive.content}
                  theme="vs-dark"
                  onMount={(editor) => {
                    diffEditorRef.current = editor;
                  }}
                  options={{
                    readOnly: true,
                    renderSideBySide: true,
                    minimap: { enabled: false },
                    fontSize: 13,
                    wordWrap: "on",
                  }}
                />
              ) : (
                <Editor
                  height="100%"
                  defaultLanguage="typescript"
                  value={active.content}
                  theme="vs-dark"
                  onChange={(v) => {
                    const next = v ?? "";
                    setTabs((prev) => prev.map((t) => (t.path === active.path ? { ...t, content: next, dirty: true } : t)));
                  }}
                  options={{
                    fontSize: 13,
                    minimap: { enabled: false },
                    smoothScrolling: true,
                    wordWrap: "on",
                  }}
                />
              )
            ) : (
              <div className="hint">No file selected.</div>
            )}
          </div>

        </section>

        <div className="splitter v" onMouseDown={(e) => startDrag("right", e)} />

        {/* Agent Brain (Right Sidebar) */}
        <aside className="pane right" style={{ width: rightW }}>
          <div className="paneTitle">Agent Brain</div>
          <div className="consoleBody">
            <div className="brainSection">
              <div className="brainTitle" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                Instruction
                <span className={`status-dot ${agentStatus}`} title={agentStatus} />
              </div>
              <textarea
                className="textarea"
                placeholder='e.g. "button itu kayaknya harus agak di besarin deh dan warnanya harus lebih sesuai tema"'
                value={agentInput}
                onChange={(e) => setAgentInput(e.target.value)}
              />
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
                <button className="btn primary" onClick={runAgent} disabled={!agentInput.trim()}>
                  Run
                </button>
                {hasPrd && (
                  <button className="btn" onClick={executePrd}>
                    Execute PRD.md
                  </button>
                )}
              </div>
            </div>


            <div className="brainSection">
              <div className="brainTitle">Thoughts</div>
              <pre className="pre" style={{ maxHeight: 160, overflow: "auto" }}>{agentLog}</pre>
            </div>

            <div className="brainSection">
              <div className="brainTitle">Blueprint</div>
              <div className="blueprint">
                <pre className="pre" style={{ maxHeight: 180, overflow: "auto" }}>{blueprint}</pre>
                <div className="checklist">
                  {blueprintChecks.map((c) => (
                    <div key={c.id} className={`checkItem ${c.status}`}>
                      <span className="checkIcon" aria-hidden>
                        {c.status === "done" ? "✅" : c.status === "doing" ? "⏳" : c.status === "error" ? "❌" : "⬜"}
                      </span>
                      <span className="checkLabel">{c.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="brainSection">
              <div className="brainTitle">Terminal / Activity</div>
              {activeRunId ? (
                <>
                  <div className="hint" style={{ padding: "0 0 8px" }}>
                    Showing logs for run: <span className="mono">{activeRunId}</span>
                  </div>
                  <pre className="pre" style={{ maxHeight: 220, overflow: "auto" }}>{runOut || "(no output yet)"}</pre>
                </>
              ) : (
                <div className="hint">No active run selected. Click a running URL in the status bar.</div>
              )}

              <div className="brainTitle" style={{ marginTop: 10 }}>Errors</div>
              <pre className="pre" style={{ maxHeight: 160, overflow: "auto" }}>
                {(() => {
                  const lines = (runOut || "").split("\n");
                  const errs = lines.filter((l) => /\b(error|failed|exception)\b/i.test(l) || l.includes("[ERROR]") || l.includes("✘"));
                  return errs.slice(-60).join("\n") || "(no errors detected)";
                })()}
              </pre>
            </div>
          </div>
        </aside>
      </div>

      {previewUrl ? (
        <div className="modalOverlay" onClick={() => setPreviewUrl("")}>
          <div className="modal modalPreview" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">Preview</div>
              <div className="spacer" />
              <a className="btn" href={previewUrl} target="_blank" rel="noreferrer">
                Open in new tab
              </a>
              <button className="btn" onClick={() => setPreviewUrl("")}>
                Close
              </button>
            </div>
            <div className="modalBody" style={{ padding: 0 }}>
              <iframe className="previewFrame" src={previewUrl} />
            </div>
          </div>
        </div>
      ) : null}

      {/* Omni-bar */}
      {omniOpen ? (
        <div className="modalOverlay" onClick={() => setOmniOpen(false)}>
          <div className="omni" onClick={(e) => e.stopPropagation()}>
            <input
              ref={omniRef}
              className="omniInput"
              placeholder='Type a command… (e.g. "make the save button bigger")'
              value={omniText}
              onChange={(e) => setOmniText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setOmniOpen(false);
                if (e.key === "Enter") {
                  const cmd = omniText.trim();
                  if (!cmd) return;
                  setAgentInput(cmd);
                  setOmniOpen(false);
                  setOmniText("");
                  // Phase 1: Discovery
                  setBlueprintChecks((prev) => prev.map((x) => (x.id === "discover" ? { ...x, status: "done" } : x)));
                }
              }}
            />
            <div className="omniSuggest">
              <div className="omniHint">Suggestions</div>
              <button className="omniChip" onClick={() => setOmniText("Increase padding + contrast for topbar buttons")}>UI polish</button>
              <button className="omniChip" onClick={() => setOmniText("Add keyboard shortcuts for Save and Refresh")}>Shortcuts</button>
              <button className="omniChip" onClick={() => setOmniText("Refactor this component into smaller components")}>Refactor</button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Blueprint editor (Modify Plan) */}
      {planOpen ? (
        <div className="modalOverlay" onClick={() => setPlanOpen(false)}>
          <div className="plan" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">Blueprint Editor</div>
              <div className="spacer" />
              <button className="btn" onClick={() => setPlanOpen(false)}>
                Close
              </button>
              <button
                className="btn primary"
                onClick={() => {
                  setBlueprint(planText);
                  setPlanOpen(false);
                }}
              >
                Save Blueprint
              </button>
            </div>
            <div className="planBody">
              <div className="diffTitle">Markdown Plan</div>
              <textarea
                className="textarea"
                style={{ minHeight: 340 }}
                value={planText}
                onChange={(e) => setPlanText(e.target.value)}
              />
              <div className="diffTitle" style={{ marginTop: 10 }}>
                Checklist
              </div>
              <div className="checklist">
                {blueprintChecks.map((c) => (
                  <div key={c.id} className={`checkItem ${c.status}`}>
                    <span className="checkIcon" aria-hidden>
                      {c.status === "done" ? "✅" : c.status === "doing" ? "⏳" : c.status === "error" ? "❌" : "⬜"}
                    </span>
                    <span className="checkLabel">{c.label}</span>
                  </div>
                ))}
              </div>
              <div className="hint" style={{ padding: "10px 0 0" }}>
                Tip: press <b>Ctrl/Cmd + K</b> to enter a new command after adjusting the blueprint.
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Review & Commit overlay */}
      {reviewOpen ? (
        <div className="modalOverlay" onClick={() => setReviewOpen(false)}>
          <div className="review" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">Review & Commit</div>
              <div className="spacer" />
              <div className="pill mono">{reviewPath}</div>
              <button className="btn" onClick={rejectPending}>Reject</button>
              <button
                className="btn"
                onClick={() => {
                  setReviewOpen(false);
                  setPlanText(blueprint);
                  setPlanOpen(true);
                }}
              >
                Modify Plan
              </button>
              <button className="btn primary" onClick={applyPending}>
                Execute Changes
              </button>
            </div>

            <div className="reviewBody">
              <div className="reviewGrid">
                <div className="reviewFiles">
                  <div className="diffTitle">Files ({pendingChanges.length})</div>
                  <div className="reviewFileList">
                    {pendingChanges.map((c) => (
                      <button
                        key={c.path}
                        className={`reviewFile ${c.path === reviewPath ? "active" : ""}`}
                        onClick={() => selectReviewFile(c.path)}
                      >
                        {c.path}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="reviewDiffs">
                  <div className="diffCols">
                    <div className="diffCol">
                      <div className="diffTitle">Original</div>
                      <pre className="pre diff original">{reviewOriginal}</pre>
                    </div>
                    <div className="diffCol">
                      <div className="diffTitle">Proposed</div>
                      <pre className="pre diff proposed">{reviewProposed}</pre>
                    </div>
                  </div>
                  <div className="diffUnified">
                    <div className="diffTitle">Unified diff</div>
                    <pre className="pre diff">{reviewDiff || "(diff unavailable)"}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {prdOpen ? (
        <div className="modalOverlay" onClick={() => setPrdOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">Product Requirements (PRD)</div>
              <div className="spacer" />
              <button className="btn" onClick={() => setPrdOpen(false)}>
                Close
              </button>
            </div>

            <div className="modalBody">
              <div className="grid2">
                <div>
                  <div className="label">Base folder (absolute)</div>
                  <input
                    className="input"
                    value={prdBaseDir}
                    placeholder={wsDefault ?? "/home/eight/projects"}
                    onChange={(e) => setPrdBaseDir(e.target.value)}
                  />
                  <div className="hint" style={{ padding: "6px 0 0" }}>
                    PRD.md will be written into this workspace root.
                  </div>
                </div>
                <div>
                  <div className="label">Product name</div>
                  <input className="input" value={prdName} onChange={(e) => setPrdName(e.target.value)} />
                </div>
              </div>

              <div className="label" style={{ marginTop: 12 }}>
                Reference URL (optional)
              </div>
              <input
                className="input"
                placeholder="https://example.com (extract design DNA)"
                value={prdRefUrl}
                onChange={(e) => setPrdRefUrl(e.target.value)}
              />

              <div className="label" style={{ marginTop: 12 }}>
                What do you want to build?
              </div>
              <textarea
                className="textarea"
                placeholder="Describe the product goals, users, and key features"
                value={prdGoal}
                onChange={(e) => setPrdGoal(e.target.value)}
              />

              <div className="modalActions" style={{ justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <button className="btn primary" onClick={generatePrdFile} disabled={prdBusy}>
                  {prdBusy ? "Working…" : "Generate PRD.md"}
                </button>
                <div className="hint" style={{ padding: 0 }}>
                  This mode only writes PRD.md and stops. Use the main page (Instruction + Agent) to execute the full app.
                </div>
              </div>

              {prdMsg ? <div className="msg">{prdMsg}</div> : null}
            </div>
          </div>
        </div>
      ) : null}

      {settingsOpen ? (
        <div
          className="modalOverlay"
          onClick={() => {
            setSettingsOpen(false);
          }}
        >
          <div
            className="modal"
            onClick={(e) => {
              e.stopPropagation();
            }}
          >
            <div className="modalHeader">
              <div className="modalTitle">Settings</div>
              <div className="spacer" />
              <button className="btn" onClick={() => setSettingsOpen(false)}>
                Close
              </button>
            </div>

            <div className="modalBody">
              <div className="grid2">
                <div>
                  <div className="label">DEFAULT_WORKSPACE</div>
                  <input
                    className="input"
                    value={settingsDraft.default_workspace}
                    placeholder="(empty = show dialog)"
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, default_workspace: e.target.value }))}
                  />
                </div>
                <div>
                  <div className="label">STT_PROVIDER</div>
                  <select
                    className="input"
                    value={settingsDraft.stt_provider}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, stt_provider: e.target.value }))}
                  >
                    <option value="groq">groq</option>
                    <option value="openai">openai</option>
                    <option value="whispercpp">whispercpp</option>
                  </select>
                  <div className="hint" style={{ padding: "6px 0 0" }}>
                    STT = Speech-to-Text (voice → text). Choose provider you have a key for.
                  </div>
                </div>

                <div>
                  <div className="label">LLM_PROVIDER</div>
                  <select
                    className="input"
                    value={settingsDraft.llm_provider}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, llm_provider: e.target.value }))}
                  >
                    <option value="groq">groq</option>
                    <option value="openai">openai</option>
                    <option value="gemini">gemini</option>
                  </select>
                  {settingsDraft.llm_provider === "groq" ? (
                    <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
                      <button className="btn" onClick={refreshGroqModels} type="button">
                        Refresh models
                      </button>
                      <div className="hint" style={{ padding: 0 }}>
                        uses GROQ_API_KEY
                      </div>
                    </div>
                  ) : settingsDraft.llm_provider === "openai" ? (
                    <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
                      <button className="btn" onClick={refreshOpenAIModels} type="button">
                        Refresh models
                      </button>
                      <div className="hint" style={{ padding: 0 }}>
                        uses OPENAI_API_KEY
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
                      <button className="btn" onClick={refreshGeminiModels} type="button">
                        Refresh models
                      </button>
                      <div className="hint" style={{ padding: 0 }}>
                        uses GEMINI_API_KEY
                      </div>
                    </div>
                  )}
                </div>

                <div>
                  <div className="label">TTS_PROVIDER</div>
                  <select
                    className="input"
                    value={settingsDraft.tts_provider}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, tts_provider: e.target.value }))}
                  >
                    <option value="pyttsx3">pyttsx3 (local)</option>
                    <option value="elevenlabs">elevenlabs</option>
                  </select>
                  <div className="hint" style={{ padding: "6px 0 0" }}>
                    TTS = Text-to-Speech (text → voice). ElevenLabs needs API key.
                  </div>
                </div>

                <div>
                  <div className="label">Model (Coding)</div>
                  {settingsDraft.llm_provider === "groq" ? (
                    <select
                      className="input"
                      value={settingsDraft.groq_chat_model}
                      onChange={(e) => setSettingsDraft((d) => ({ ...d, groq_chat_model: e.target.value }))}
                    >
                      {groqModels.map((m) => (
                        <option key={m} value={m}>
                          {m}{modelHints[m] ? ` — ${modelHints[m]}` : ""}
                        </option>
                      ))}
                      <option value="__custom__">Custom…</option>
                    </select>
                  ) : settingsDraft.llm_provider === "openai" ? (
                    <select
                      className="input"
                      value={settingsDraft.openai_chat_model}
                      onChange={(e) => setSettingsDraft((d) => ({ ...d, openai_chat_model: e.target.value }))}
                    >
                      {openaiModels.map((m) => (
                        <option key={m} value={m}>
                          {m}{modelHints[m] ? ` — ${modelHints[m]}` : ""}
                        </option>
                      ))}
                      <option value="__custom__">Custom…</option>
                    </select>
                  ) : (
                    <select
                      className="input"
                      value={settingsDraft.gemini_chat_model}
                      onChange={(e) => setSettingsDraft((d) => ({ ...d, gemini_chat_model: e.target.value }))}
                    >
                      {geminiModels.map((m) => (
                        <option key={m} value={m}>
                          {m}{modelHints[m] ? ` — ${modelHints[m]}` : ""}
                        </option>
                      ))}
                      <option value="__custom__">Custom…</option>
                    </select>
                  )}
                  {settingsDraft.llm_provider === "groq" && settingsDraft.groq_chat_model === "__custom__" ? (
                    <input
                      className="input"
                      style={{ marginTop: 8 }}
                      placeholder="Type Groq model id"
                      onChange={(e) => setSettingsDraft((d) => ({ ...d, groq_chat_model: e.target.value }))}
                    />
                  ) : null}
                  {settingsDraft.llm_provider === "openai" && settingsDraft.openai_chat_model === "__custom__" ? (
                    <input
                      className="input"
                      style={{ marginTop: 8 }}
                      placeholder="Type OpenAI model id"
                      onChange={(e) => setSettingsDraft((d) => ({ ...d, openai_chat_model: e.target.value }))}
                    />
                  ) : null}
                  {settingsDraft.llm_provider === "gemini" && settingsDraft.gemini_chat_model === "__custom__" ? (
                    <input
                      className="input"
                      style={{ marginTop: 8 }}
                      placeholder="Type Gemini model id"
                      onChange={(e) => setSettingsDraft((d) => ({ ...d, gemini_chat_model: e.target.value }))}
                    />
                  ) : null}
                </div>

                <div>
                  <div className="label">GROQ_WHISPER_MODEL</div>
                  <select
                    className="input"
                    value={settingsDraft.groq_whisper_model}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, groq_whisper_model: e.target.value }))}
                  >
                    <option value="whisper-large-v3-turbo">whisper-large-v3-turbo (fast)</option>
                    <option value="whisper-large-v3">whisper-large-v3 (accurate)</option>
                  </select>
                  <div className="hint" style={{ padding: "6px 0 0" }}>
                    Whisper model for Groq STT.
                  </div>
                </div>


                <div>
                  <div className="label">API Key (Groq)</div>
                  <input
                    className="input"
                    type="password"
                    value={settingsDraft.groq_api_key}
                    placeholder={settings?.has_groq_key ? "(already set) leave blank to keep" : "paste GROQ_API_KEY"}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, groq_api_key: e.target.value }))}
                  />
                </div>

                <div>
                  <div className="label">API Key (OpenAI)</div>
                  <input
                    className="input"
                    type="password"
                    value={settingsDraft.openai_api_key}
                    placeholder={settings?.has_openai_key ? "(already set) leave blank to keep" : "paste OPENAI_API_KEY"}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, openai_api_key: e.target.value }))}
                  />
                </div>

                <div>
                  <div className="label">API Key (Gemini)</div>
                  <input
                    className="input"
                    type="password"
                    value={settingsDraft.gemini_api_key}
                    placeholder={settings?.has_gemini_key ? "(already set) leave blank to keep" : "paste GEMINI_API_KEY"}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, gemini_api_key: e.target.value }))}
                  />
                </div>

                <div>
                  <div className="label">API Key (ElevenLabs)</div>
                  <input
                    className="input"
                    type="password"
                    value={settingsDraft.elevenlabs_api_key}
                    placeholder={settings?.has_elevenlabs_key ? "(already set) leave blank to keep" : "paste ELEVENLABS_API_KEY"}
                    onChange={(e) => setSettingsDraft((d) => ({ ...d, elevenlabs_api_key: e.target.value }))}
                  />
                </div>
              </div>

              {settingsMsg ? <div className="msg">{settingsMsg}</div> : null}

              <div className="modalActions">
                <button className="btn primary" onClick={saveSettings}>
                  Save settings
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <footer className="statusbar">
        <span className="mono">Workspace:</span> <span className="mono">{ws ?? "(none)"}</span>
        <span className="dot" />
        <span className="mono">Running:</span>
        {runs.length === 0 ? (
          <span className="mono">(none)</span>
        ) : (
          <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {runs.map((r) => (
              <span key={r.id} className="runChip" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                <a
                  href={r.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mono"
                  style={{ color: "var(--text)" }}
                  onClick={() => setActiveRunId(r.id)}
                >
                  {r.project_root} → {r.url}
                </a>
                <button
                  className="btn"
                  style={{ padding: "4px 8px", borderRadius: 999 }}
                  onClick={() => setPreviewUrl(r.url)}
                  title="Preview"
                >
                  Preview
                </button>
                <button
                  className="btn"
                  style={{ padding: "4px 8px", borderRadius: 999 }}
                  onClick={async () => {
                    await runClose(r.id);
                    const rl = await runList();
                    setRuns(rl.items.map((x) => ({ id: x.id, project_root: x.project_root, url: x.url, running: x.running })));
                    if (activeRunId === r.id) setActiveRunId("");
                    if (previewUrl === r.url) setPreviewUrl("");
                  }}
                  title="Close"
                >
                  Close
                </button>
              </span>
            ))}
          </span>
        )}
        <span className="dot" />
        <span className="mono">Backend:</span> <span className="mono">localhost:8787</span>
      </footer>
    </div>
  );
}
