import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";

type Anchor = {
  owner_kind: string;
  owner_id: string;
  start_byte: number;
  end_byte: number;
  text_sha256?: string;
  slice_sha256?: string;
};

type Donor = {
  text: string;
  title: string;
  anchor: Anchor;
};

type Protection = { start_byte: number; end_byte: number; text: string };

type Entry = {
  id: string;
  ordinal: number;
  revision_id: string;
  text: string;
  removed: boolean;
  draft: string | null;
  protected: Protection[];
};

type HeldName = {
  id: string;
  text: string;
  status: string;
  target_state: string;
  entry_id: string;
  entry_removed: boolean;
  placeholder: string;
  donor_owner_kind: string;
  donor_owner_id: string;
  donor_start: number;
  donor_end: number;
  source_title: string | null;
  message: string | null;
};

type Preview = {
  id: string;
  operation: string;
  work_state_version: number;
  binding_applies: boolean;
  exact_donor_copy: boolean;
  destination: { label: string };
  base: { text: string };
  final: { text: string };
  candidate_id: string;
  donor_text: string | null;
  separator: string | null;
  protected: Protection[];
  provider_window?: string | null;
  omitted_text?: string | null;
};

type WorkRecord = {
  id: string;
  title: string;
  state_version: number;
  binding: {
    id: string;
    influence_version_id: string;
    name: string;
    interpretation: string;
    template: string | null;
  } | null;
  entries: Entry[];
  held_names: HeldName[];
  previews: Preview[];
  events: { id: string; action: string; detail: Record<string, unknown>; earlier_text: string | null }[];
};

type InfluenceVersion = {
  id: string;
  influence_id: string;
  version_number: number;
  name: string;
  interpretation: string;
  template: string | null;
  operative: boolean;
};

function byteSpan(text: string, start: number, end: number, base: number) {
  const encoder = new TextEncoder();
  const prefix = encoder.encode(text.slice(0, start)).length;
  const width = encoder.encode(text.slice(start, end)).length;
  return { start_byte: base + prefix, end_byte: base + prefix + width };
}

function findIn(text: string, needle: string) {
  const found: { start: number; end: number }[] = [];
  if (!needle) return found;
  let cursor = 0;
  while (cursor <= text.length) {
    const index = text.indexOf(needle, cursor);
    if (index < 0) return found;
    found.push({ start: index, end: index + needle.length });
    cursor = index + needle.length;
  }
  return found;
}

function eventLabel(action: string, detail: Record<string, unknown>): string {
  if (action === "create") return "Work opened.";
  if (action === "bind") return `Bound “${detail.name}”.`;
  if (action === "unbind") return "Unbound the influence. Earlier names stay held.";
  if (action === "transfer") {
    return detail.mark_text ? `Added a passage. Held the name “${detail.mark_text}”.` : "Added a passage.";
  }
  if (action === "protected_insert") return "Inserted a protected passage.";
  if (action === "return") return `Returned the name “${detail.text}”.`;
  if (action === "edit") return "Edited an entry.";
  if (action === "remove") return "Removed an entry.";
  if (action === "restore") return "Restored an entry.";
  if (action === "reorder") return "Reordered the entries.";
  if (action === "retarget") return "Chose a current place for a held name.";
  if (action === "repair") return `Adopted a repair. “${detail.omitted_text}” became “${detail.replacement_text}”.`;
  return action;
}

export function Work({
  projectId,
  donor,
  onEncounter,
  onEntries,
}: {
  projectId: string | null;
  donor: Donor | null;
  onEncounter: (text: string, anchor: Anchor) => void;
  onEntries?: (entries: { id: string; revision_id: string; text: string; removed: boolean }[]) => void;
}) {
  const [works, setWorks] = useState<{ id: string; title: string }[]>([]);
  const [workId, setWorkId] = useState<string | null>(null);
  const [work, setWork] = useState<WorkRecord | null>(null);
  const [influences, setInfluences] = useState<InfluenceVersion[]>([]);
  const [title, setTitle] = useState("");
  const [ruleName, setRuleName] = useState("What crosses must leave its name behind.");
  const [ruleText, setRuleText] = useState("Identity is displaced when this material enters the work.");
  const [operative, setOperative] = useState(true);
  const [needle, setNeedle] = useState("");
  const [marks, setMarks] = useState<{ start: number; end: number }[]>([]);
  const [mark, setMark] = useState<{ start: number; end: number } | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [repairEntryId, setRepairEntryId] = useState<string | null>(null);
  const [omissionNeedle, setOmissionNeedle] = useState("");
  const [omissions, setOmissions] = useState<{ start: number; end: number }[]>([]);
  const [omission, setOmission] = useState<{ start: number; end: number } | null>(null);
  const [repairCount, setRepairCount] = useState(3);
  const [repairJob, setRepairJob] = useState<string | null>(null);
  const [repairProgress, setRepairProgress] = useState("");
  const [releaseRepair, setReleaseRepair] = useState(false);
  const [appendix, setAppendix] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});

  async function refresh(nextId = workId) {
    if (!projectId) return;
    const listed = await api<{ works: { id: string; title: string }[] }>(`/api/v1/projects/${projectId}/works`);
    const ideas = await api<{ influences: { versions: InfluenceVersion[] }[] }>(
      `/api/v1/projects/${projectId}/influences`,
    );
    setWorks(listed.works);
    setInfluences(ideas.influences.flatMap((item) => item.versions));
    const chosen = nextId ?? listed.works[0]?.id ?? null;
    setWorkId(chosen);
    if (!chosen) {
      setWork(null);
      onEntries?.([]);
      return;
    }
    const loaded = await api<WorkRecord>(`/api/v1/projects/${projectId}/works/${chosen}`);
    setWork(loaded);
    onEntries?.(loaded.entries);
    setDrafts((current) => {
      const next = { ...current };
      for (const entry of loaded.entries) {
        if (next[entry.id] === undefined) next[entry.id] = entry.draft ?? "";
      }
      return next;
    });
  }

  useEffect(() => {
    setWorkId(null);
    setWork(null);
    onEntries?.([]);
    setPreview(null);
    setError("");
    if (!projectId) return;
    let cancel = false;
    refresh(null).catch((reason: Error) => {
      if (!cancel) setError(reason.message);
    });
    return () => {
      cancel = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !workId || !repairJob) return;
    const timer = window.setInterval(() => {
      void api<{ state: string; progress: { stage?: string }; error: { message?: string } | null; result: { preview_ids?: string[] } | null }>(
        `/api/v1/jobs/${repairJob}`,
      )
        .then(async (job) => {
          if (job.state === "queued" || job.state === "running") {
            setRepairProgress(job.progress.stage ? `${job.progress.stage}.` : "Preparing a repair.");
            return;
          }
          setRepairJob(null);
          setRepairProgress("");
          const loaded = await api<WorkRecord>(`/api/v1/projects/${projectId}/works/${workId}`);
          setWork(loaded);
          onEntries?.(loaded.entries);
          const prepared = loaded.previews.find((item) => job.result?.preview_ids?.includes(item.id));
          if (prepared) setPreview(prepared);
          if (job.state !== "succeeded" && job.state !== "cancelled") {
            setError(job.error?.message || "The repair was not prepared.");
          }
        })
        .catch((reason: Error) => setError(reason.message));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, workId, repairJob]);

  function fail(reason: unknown) {
    setError(reason instanceof Error ? reason.message : "The work could not be changed.");
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !title.trim()) return;
    setError("");
    const created = await api<WorkRecord>(`/api/v1/projects/${projectId}/works`, {
      method: "POST",
      body: JSON.stringify({ title }),
    });
    setTitle("");
    await refresh(created.id);
  }

  async function saveInfluence(event: FormEvent) {
    event.preventDefault();
    if (!projectId) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/influences`, {
      method: "POST",
      body: JSON.stringify({
        name: ruleName,
        interpretation: ruleText,
        template: operative ? "withhold_marked_span_v1" : null,
        parameters: operative ? { mark_role: "name", replacement_text: "_____" } : null,
      }),
    });
    await refresh();
  }

  async function bind(versionId: string) {
    if (!projectId || !work) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/binding`, {
      method: "POST",
      body: JSON.stringify({ influence_version_id: versionId, expected_work_state_version: work.state_version }),
    });
    setPreview(null);
    await refresh();
  }

  async function unbind() {
    if (!projectId || !work) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/binding/unbind`, {
      method: "POST",
      body: JSON.stringify({ expected_work_state_version: work.state_version }),
    });
    setPreview(null);
    await refresh();
  }

  function showMarks(event: FormEvent) {
    event.preventDefault();
    if (!donor) return;
    const found = findIn(donor.text, needle);
    setMarks(found);
    setMark(found.length === 1 ? found[0] : null);
    setError(found.length ? "" : "That name is not in the selected passage.");
  }

  function showOmissions(event: FormEvent) {
    event.preventDefault();
    const entry = work?.entries.find((item) => item.id === repairEntryId);
    if (!entry) return;
    const found = findIn(entry.text, omissionNeedle);
    setOmissions(found);
    setOmission(found.length === 1 ? found[0] : null);
    setError(found.length ? "" : "That span is not in this entry.");
  }

  async function prepareRepair() {
    if (!projectId || !work || !repairEntryId || !omission) return;
    const entry = work.entries.find((item) => item.id === repairEntryId);
    if (!entry) return;
    setError("");
    const span = byteSpan(entry.text, omission.start, omission.end, 0);
    const queued = await api<{ id: string }>(`/api/v1/projects/${projectId}/works/${work.id}/repairs`, {
      method: "POST",
      body: JSON.stringify({
        client_request_id: crypto.randomUUID(),
        passage_revision_id: entry.revision_id,
        omission: span,
        context: { start_byte: 0, end_byte: new TextEncoder().encode(entry.text).length },
        destination: {
          kind: "replace_entry",
          entry_id: entry.id,
          expected_revision_id: entry.revision_id,
        },
        candidate_count: repairCount,
        release_protection: releaseRepair,
      }),
    });
    setRepairProgress("Preparing a repair.");
    setRepairJob(queued.id);
  }

  async function download(path: string, filename: string, init?: RequestInit) {
    const response = await fetch(path, init);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.message || response.statusText);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function previewTransfer() {
    if (!projectId || !work || !donor) return;
    setError("");
    const active = work.entries.filter((entry) => !entry.removed);
    const body: {
      work_id: string;
      position: number;
      donor: Anchor;
      mark?: { start_byte: number; end_byte: number };
    } = {
      work_id: work.id,
      position: active.length,
      donor: donor.anchor,
    };
    if (mark) body.mark = byteSpan(donor.text, mark.start, mark.end, donor.anchor.start_byte);
    const prepared = await api<Preview>(`/api/v1/projects/${projectId}/previews/transfer`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    setPreview(prepared);
  }

  async function previewInsert(entry: Entry) {
    if (!projectId || !work || !donor) return;
    setError("");
    const body: {
      work_id: string;
      entry_id: string;
      boundary: number;
      separator: string;
      donor: Anchor;
      mark?: { start_byte: number; end_byte: number };
    } = {
      work_id: work.id,
      entry_id: entry.id,
      boundary: new TextEncoder().encode(entry.text).length,
      separator: " ",
      donor: donor.anchor,
    };
    if (mark) body.mark = byteSpan(donor.text, mark.start, mark.end, donor.anchor.start_byte);
    const prepared = await api<Preview>(`/api/v1/projects/${projectId}/previews/protected-insert`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    setPreview(prepared);
  }

  async function adopt(prepared: Preview) {
    if (!projectId || !work) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/commit`, {
      method: "POST",
      body: JSON.stringify({
        client_request_id: crypto.randomUUID(),
        preview_id: prepared.id,
        candidate_id: prepared.candidate_id,
        expected_work_state_version: prepared.work_state_version,
      }),
    });
    setPreview(null);
    await refresh();
  }

  async function previewNameReturn(held: HeldName, target?: { start_byte: number; end_byte: number }) {
    if (!projectId || !work) return;
    setError("");
    const prepared = await api<Preview>(
      `/api/v1/projects/${projectId}/works/${work.id}/held-names/${held.id}/return`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_work_state_version: work.state_version,
          target_start: target?.start_byte ?? null,
          target_end: target?.end_byte ?? null,
        }),
      },
    );
    setPreview(prepared);
  }

  async function move(index: number, delta: number) {
    if (!projectId || !work) return;
    const ids = work.entries.filter((entry) => !entry.removed).map((entry) => entry.id);
    const next = index + delta;
    if (next < 0 || next >= ids.length) return;
    const order = [...ids];
    const [item] = order.splice(index, 1);
    order.splice(next, 0, item);
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/entries/reorder`, {
      method: "POST",
      body: JSON.stringify({ entry_ids: order, expected_work_state_version: work.state_version }),
    });
    await refresh();
  }

  async function remove(entryId: string) {
    if (!projectId || !work) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/entries/${entryId}/remove`, {
      method: "POST",
      body: JSON.stringify({ expected_work_state_version: work.state_version }),
    });
    await refresh();
  }

  async function restore(entryId: string) {
    if (!projectId || !work) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/entries/${entryId}/restore`, {
      method: "POST",
      body: JSON.stringify({ expected_work_state_version: work.state_version }),
    });
    await refresh();
  }

  async function saveDraft(entryId: string) {
    if (!projectId || !work) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/entries/${entryId}/draft`, {
      method: "PUT",
      body: JSON.stringify({ text: drafts[entryId] ?? "" }),
    });
    await refresh();
  }

  async function saveEdit(entry: Entry, release: boolean) {
    if (!projectId || !work) return;
    setError("");
    await api(`/api/v1/projects/${projectId}/works/${work.id}/entries/${entry.id}/edit`, {
      method: "POST",
      body: JSON.stringify({
        text: edits[entry.id] ?? entry.text,
        expected_work_state_version: work.state_version,
        release_protection: release,
      }),
    });
    await refresh();
  }

  const active = work?.entries.filter((entry) => !entry.removed) ?? [];
  const removed = work?.entries.filter((entry) => entry.removed) ?? [];
  const repairEntry = active.find((entry) => entry.id === repairEntryId) ?? null;

  return (
    <section className="work-panel" aria-label="Work">
      <h2>Work</h2>
      {!projectId && <p>Open a project to start a work.</p>}
      {error && <p className="error">{error}</p>}
      {projectId && (
        <form onSubmit={(event) => void create(event).catch(fail)}>
          <label>
            New work
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <button type="submit" disabled={!title.trim()}>
            Create work
          </button>
        </form>
      )}
      {works.length > 0 && (
        <ul className="passages">
          {works.map((item) => (
            <li key={item.id}>
              <button type="button" aria-current={item.id === workId ? "true" : undefined} onClick={() => void refresh(item.id).catch(fail)}>
                {item.title}
              </button>
            </li>
          ))}
        </ul>
      )}
      {work && (
        <>
          <h3>{work.title}</h3>
          {work.binding ? (
            <p>
              Bound influence: {work.binding.name} {work.binding.interpretation}
              <button type="button" onClick={() => void unbind().catch(fail)}>
                Unbind
              </button>
            </p>
          ) : (
            <p>No influence is bound. A transferred passage is copied exactly.</p>
          )}
          {active.length === 0 && <p>This work has no entries.</p>}
          {active.map((entry, index) => (
            <article className="work-entry" key={entry.id}>
              <p className="prose">{entry.text}</p>
              {entry.protected.map((item) => (
                <p className="legend" key={`${item.start_byte}-${item.end_byte}`}>
                  Protected: {item.text}
                </p>
              ))}
              <p>
                <button type="button" onClick={() => void move(index, -1).catch(fail)} disabled={index === 0}>
                  Move up
                </button>
                <button type="button" onClick={() => void move(index, 1).catch(fail)} disabled={index === active.length - 1}>
                  Move down
                </button>
                <button type="button" onClick={() => void remove(entry.id).catch(fail)}>
                  Remove
                </button>
                <button type="button" onClick={() => void previewInsert(entry).catch(fail)} disabled={!donor}>
                  Insert the selected passage
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setRepairEntryId(entry.id);
                    setOmissions([]);
                    setOmission(null);
                    setOmissionNeedle("");
                    setReleaseRepair(false);
                  }}
                >
                  Mark an omission
                </button>
              </p>
              <details>
                <summary>Draft and edit</summary>
                <label>
                  Draft, kept apart from the desk
                  <textarea value={drafts[entry.id] ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [entry.id]: event.target.value }))} />
                </label>
                <button type="button" onClick={() => void saveDraft(entry.id).catch(fail)}>
                  Save draft
                </button>
                <label>
                  Replace the committed passage
                  <textarea value={edits[entry.id] ?? entry.text} onChange={(event) => setEdits((current) => ({ ...current, [entry.id]: event.target.value }))} />
                </label>
                <button type="button" onClick={() => void saveEdit(entry, false).catch(fail)}>
                  Save edit
                </button>
                <button type="button" onClick={() => void saveEdit(entry, true).catch(fail)}>
                  Save edit and release protection
                </button>
              </details>
            </article>
          ))}
          {removed.length > 0 && (
            <div>
              <h3>Removed entries</h3>
              {removed.map((entry) => (
                <article key={entry.id}>
                  <p className="prose">{entry.text}</p>
                  <button type="button" onClick={() => void restore(entry.id).catch(fail)}>
                    Restore
                  </button>
                </article>
              ))}
            </div>
          )}
          <h3>Names held from this work</h3>
          {work.held_names.length === 0 && <p>No names are held.</p>}
          <ul className="hits">
            {work.held_names.map((held) => (
              <li key={held.id}>
                <article>
                  <h4>{held.text}</h4>
                  <p className="legend">
                    {held.source_title ? `From ${held.source_title}. ` : ""}
                    {held.status === "returned" ? "Returned." : "Held."} {held.message}
                  </p>
                  <button
                    type="button"
                    onClick={() =>
                      onEncounter(held.text, {
                        owner_kind: held.donor_owner_kind,
                        owner_id: held.donor_owner_id,
                        start_byte: held.donor_start,
                        end_byte: held.donor_end,
                      })
                    }
                  >
                    Look for this name
                  </button>
                  {held.status === "held" && held.target_state === "resolved" && (
                    <button type="button" onClick={() => void previewNameReturn(held).catch(fail)}>
                      Preview the return
                    </button>
                  )}
                  {held.status === "held" && held.target_state !== "resolved" && held.message && (
                    <p>
                      <button
                        type="button"
                        onClick={() => void previewNameReturn(held, { start_byte: 0, end_byte: 0 }).catch(fail)}
                        disabled={held.entry_removed}
                      >
                        Insert the name at the start
                      </button>
                    </p>
                  )}
                </article>
              </li>
            ))}
          </ul>
          {repairEntry && (
            <form onSubmit={showOmissions} aria-label="Omission repair">
              <h3>Omit a span from this entry</h3>
              <p className="prose">{repairEntry.text}</p>
              <p>
                The model sees this whole entry with the marked occurrence removed. Bytes outside that mark stay. The name rule does not apply.
              </p>
              <label>
                Mark the omitted span
                <input value={omissionNeedle} onChange={(event) => setOmissionNeedle(event.target.value)} />
              </label>
              <button type="submit">Show occurrences</button>
              {omissions.map((item) => (
                <button
                  type="button"
                  key={`${item.start}-${item.end}`}
                  aria-pressed={omission === item}
                  onClick={() => setOmission(item)}
                >
                  Omit “{repairEntry.text.slice(item.start, item.end)}” at this place
                </button>
              ))}
              <label>
                Repairs to prepare
                <input
                  type="number"
                  min={1}
                  max={8}
                  value={repairCount}
                  onChange={(event) => setRepairCount(Number(event.target.value))}
                />
              </label>
              {repairEntry.protected.length > 0 && (
                <label>
                  <input type="checkbox" checked={releaseRepair} onChange={(event) => setReleaseRepair(event.target.checked)} />
                  Release protection on this entry
                </label>
              )}
              <p>
                <button type="button" onClick={() => void prepareRepair().catch(fail)} disabled={!omission || Boolean(repairJob)}>
                  Prepare repairs
                </button>
              </p>
              {repairProgress && <p className="legend">{repairProgress}</p>}
            </form>
          )}
          {donor && (
            <form onSubmit={showMarks}>
              <h3>Transfer the selected passage</h3>
              <p className="legend">Transfer copies text into the work.</p>
              <p className="legend">{donor.title}</p>
              <p className="prose">{donor.text}</p>
              <p>This adds the passage at the end of the work.</p>
              <label>
                Mark a name in this passage
                <input value={needle} onChange={(event) => setNeedle(event.target.value)} />
              </label>
              <button type="submit">Show occurrences</button>
              {marks.map((item) => (
                <button
                  type="button"
                  key={`${item.start}-${item.end}`}
                  aria-pressed={mark === item}
                  onClick={() => setMark(item)}
                >
                  Mark “{donor.text.slice(item.start, item.end)}” at this place
                </button>
              ))}
              <p>
                <button type="button" onClick={() => void previewTransfer().catch(fail)}>
                  Preview this transfer
                </button>
              </p>
            </form>
          )}
          {preview && (
            <article className="saved" aria-label="Operation preview">
              <h3>{preview.destination.label}</h3>
              {preview.binding_applies && !preview.exact_donor_copy && (
                <p>The influence changed this passage. It is not an exact copy of the donor. To add the exact donor, unbind the influence and prepare the transfer again.</p>
              )}
              {preview.binding_applies && preview.exact_donor_copy && <p>The influence applied. The text matches the donor.</p>}
              {!preview.binding_applies && preview.operation === "transfer_fragment_v1" && (
                <p>No influence changed this passage.</p>
              )}
              {preview.operation === "omit_and_repair_v1" && (
                <p>
                  The model proposed this replacement for the marked omission. The name rule does not apply. The surrounding bytes were not rewritten.
                </p>
              )}
              {preview.provider_window && <p className="legend">The model saw: {preview.provider_window}</p>}
              {preview.separator ? <p className="legend">Separator before the inserted passage: “{preview.separator}”</p> : null}
              {preview.protected.map((item) => (
                <p className="legend" key={`${item.start_byte}-${item.end_byte}`}>
                  Protected: {item.text}
                </p>
              ))}
              <div className="pair">
                <div>
                  <h4>Base</h4>
                  <p className="prose">{preview.base.text}</p>
                </div>
                <div>
                  <h4>Result</h4>
                  <p className="prose">{preview.final.text}</p>
                </div>
              </div>
              <button type="button" onClick={() => void adopt(preview).catch(fail)}>
                {preview.destination.label}
              </button>
            </article>
          )}
          {work.previews.length > 0 && (
            <details>
              <summary>Prepared changes not yet added</summary>
              <ul>
                {work.previews.map((item) => (
                  <li key={item.id}>
                    <button type="button" onClick={() => setPreview(item)}>
                      {item.destination.label}: {item.final.text}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <details>
            <summary>Influence</summary>
            <form onSubmit={(event) => void saveInfluence(event).catch(fail)}>
              <label>
                Name
                <input value={ruleName} onChange={(event) => setRuleName(event.target.value)} />
              </label>
              <label>
                Interpretation
                <textarea value={ruleText} onChange={(event) => setRuleText(event.target.value)} />
              </label>
              <label>
                <input type="checkbox" checked={operative} onChange={(event) => setOperative(event.target.checked)} />
                Withhold the marked name and replace it with _____
              </label>
              {!operative && <p>This idea does not govern the work.</p>}
              <button type="submit">Save influence</button>
            </form>
            <ul>
              {influences.map((item) => (
                <li key={item.id}>
                  <p>
                    {item.name} {item.operative ? "Operative." : "This idea does not govern the work."}
                  </p>
                  <p>{item.interpretation}</p>
                  {item.operative && (
                    <button type="button" onClick={() => void bind(item.id).catch(fail)}>
                      Bind this version
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </details>
          <h3>Export</h3>
          <label>
            <input type="checkbox" checked={appendix} onChange={(event) => setAppendix(event.target.checked)} />
            Include sources, influences, held names, and history
          </label>
          <p>
            <button
              type="button"
              onClick={() =>
                void download(
                  `/api/v1/projects/${projectId}/works/${work.id}/export?form=markdown&appendix=${appendix ? 1 : 0}`,
                  appendix ? "work-with-appendix.md" : "work.md",
                ).catch(fail)
              }
            >
              Download this work
            </button>
            <button
              type="button"
              onClick={() =>
                void download(`/api/v1/projects/${projectId}/export`, "openwound-project.zip", { method: "POST" }).catch(fail)
              }
            >
              Download the project archive
            </button>
          </p>
          <details>
            <summary>History</summary>
            <ol>
              {work.events.map((event) => (
                <li key={event.id}>
                  {eventLabel(event.action, event.detail)}
                  {typeof event.detail.provider_window === "string" && (
                    <p className="legend">The model saw: {event.detail.provider_window}</p>
                  )}
                  {event.earlier_text && <p className="prose">{event.earlier_text}</p>}
                </li>
              ))}
            </ol>
          </details>
        </>
      )}
    </section>
  );
}
