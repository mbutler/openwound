import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type Desk, type ProjectSummary, type Status, type Trace } from "./api";
import { Correspondences } from "./Correspondences";
import { Explain } from "./Explain";
import { Instrument } from "./Instrument";
import { Weather } from "./Weather";

type Place = "instrument" | "weather" | "archive";

const EXPLAINED = "openwound.explained";

function readFlag(): boolean {
  try {
    return window.localStorage.getItem(EXPLAINED) === "yes";
  } catch {
    return true;
  }
}

function writeFlag(): void {
  try {
    window.localStorage.setItem(EXPLAINED, "yes");
  } catch {
    // Browser storage is a convenience here, not a record.
  }
}

export function App() {
  const projectRef = useRef<string | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [desk, setDesk] = useState<Desk | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [place, setPlace] = useState<Place>("instrument");
  const [error, setError] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [archive, setArchive] = useState<File | null>(null);
  const [weatherSeed, setWeatherSeed] = useState<{ text: string; keep: number }>({ text: "", keep: 6 });
  const [explainOpen, setExplainOpen] = useState(() => !readFlag());
  const [lastTrace, setLastTrace] = useState<Trace | null>(null);

  projectRef.current = desk?.project.id ?? null;

  async function reloadDesk(): Promise<void> {
    const active = await api<Status>("/api/v1/status");
    setStatus(active);
    if (!active.project_id) {
      setDesk(null);
      return;
    }
    setDesk(await api<Desk>("/api/v1/desk"));
  }

  async function reload(): Promise<void> {
    const listed = await api<{ projects: ProjectSummary[]; active_project_id: string | null }>("/api/v1/projects");
    setProjects(listed.projects);
    await reloadDesk();
  }

  useEffect(() => {
    void reload().catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void api<Status>("/api/v1/status")
        .then(setStatus)
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  async function createProject(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/v1/projects", { method: "POST", body: JSON.stringify({ title: newTitle.trim() || "Untitled" }) });
      setNewTitle("");
      setCreating(false);
      await reload();
      setPlace("instrument");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function openProject(projectId: string) {
    if (projectId === projectRef.current) return;
    setError("");
    try {
      await api("/api/v1/projects/open", { method: "POST", body: JSON.stringify({ project_id: projectId }) });
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function importProject(event: FormEvent) {
    event.preventDefault();
    if (!archive) return;
    setError("");
    try {
      const encoded = await readFile(archive);
      const imported = await api<ProjectSummary>("/api/v1/projects/import", {
        method: "POST",
        body: JSON.stringify({ content_base64: encoded }),
      });
      setArchive(null);
      await reload();
      await openProject(imported.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const live = status?.live ?? null;
  const pulseClass = !live ? "pulse" : live.state === "ready" ? "pulse ready" : live.state === "unavailable" ? "pulse unavailable" : "pulse loading";
  const pulseLabel = !live
    ? "checking the model"
    : live.state === "ready"
      ? "TinyStories ready"
      : live.state === "unavailable"
        ? "checkpoint not available"
        : "loading the model";

  return (
    <div className="shell">
      <header className="top">
        <p className="mark">Openwound</p>
        <nav className="places" aria-label="Places">
          <button type="button" aria-current={place === "instrument" ? "true" : undefined} onClick={() => setPlace("instrument")}>
            Instrument
          </button>
          <button type="button" aria-current={place === "weather" ? "true" : undefined} onClick={() => setPlace("weather")}>
            Weather
          </button>
          <button type="button" aria-current={place === "archive" ? "true" : undefined} onClick={() => setPlace("archive")}>
            Archive
          </button>
        </nav>
        <div className="spacer" />
        {creating ? (
          <form onSubmit={(event) => void createProject(event)} className="row">
            <input
              value={newTitle}
              placeholder="Project title"
              autoFocus
              onChange={(event) => setNewTitle(event.target.value)}
              style={{ padding: "0.45rem 0.6rem" }}
            />
            <button type="submit">Create</button>
            <button type="button" className="quiet-button" onClick={() => setCreating(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <label className="row" style={{ gap: "0.4rem" }}>
            <span className="quiet" style={{ fontSize: "0.85rem" }}>
              Project
            </span>
            <select
              value={desk?.project.id ?? ""}
              onChange={(event) => {
                if (event.target.value === "__new") setCreating(true);
                else void openProject(event.target.value);
              }}
            >
              {!desk && <option value="">Choose a project</option>}
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.title}
                </option>
              ))}
              <option value="__new">New project…</option>
            </select>
          </label>
        )}
        <button type="button" className="quiet-button" onClick={() => setExplainOpen(true)}>
          How it reads
        </button>
        <span className={pulseClass}>
          <i aria-hidden="true" />
          {pulseLabel}
        </span>
      </header>

      {error && (
        <p className="error" style={{ margin: "0.6rem 2rem" }}>
          {error}
        </p>
      )}

      {!desk && (
        <div className="page stack">
          <h1>Begin a project</h1>
          <p className="quiet" style={{ maxWidth: "52ch" }}>
            A project holds every passage you keep, with the one it came from. Create one, or import an archive.
          </p>
          <form onSubmit={(event) => void createProject(event)} className="row">
            <input value={newTitle} placeholder="Project title" onChange={(event) => setNewTitle(event.target.value)} style={{ padding: "0.45rem 0.6rem" }} />
            <button type="submit" className="primary">
              Create project
            </button>
          </form>
          <form onSubmit={(event) => void importProject(event)} className="row">
            <input type="file" accept=".zip,application/zip" onChange={(event) => setArchive(event.target.files?.[0] ?? null)} />
            <button type="submit" disabled={!archive}>
              Import project archive
            </button>
          </form>
        </div>
      )}

      {desk && place === "instrument" && (
        <Instrument
          key={desk.project.id}
          desk={desk}
          live={live}
          onDeskChange={reloadDesk}
          onTrace={setLastTrace}
          onRunWeather={(text, keep) => {
            setWeatherSeed({ text, keep });
            setPlace("weather");
          }}
        />
      )}
      {desk && place === "weather" && (
        <Weather
          key={desk.project.id}
          initialText={weatherSeed.text || desk.draft.text}
          initialKeep={weatherSeed.keep}
          live={live}
          onKept={reloadDesk}
          onAdopt={(text) => {
            void api("/api/v1/draft", { method: "PUT", body: JSON.stringify({ text }) })
              .then(reloadDesk)
              .then(() => setPlace("instrument"))
              .catch((reason: Error) => setError(reason.message));
          }}
        />
      )}
      {desk && place === "archive" && (
        <div className="page">
          <Correspondences projectId={desk.project.id} />
        </div>
      )}

      <Explain
        open={explainOpen}
        frames={lastTrace?.frames ?? null}
        onClose={() => {
          writeFlag();
          setExplainOpen(false);
        }}
      />
    </div>
  );
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      const comma = value.indexOf(",");
      resolve(comma >= 0 ? value.slice(comma + 1) : value);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
