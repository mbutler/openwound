import { useEffect, useRef, useState } from "react";
import {
  api,
  randomSeed,
  variationBody,
  type Desk,
  type LiveState,
  type Revision,
  type TokenCount,
  type Trace,
  type Variation,
} from "./api";
import { Band } from "./Band";
import { wordDiff } from "./diff";

const CUMULATIVE = [1, 9, 25, 49, 81, 121, 173, 237, 313, 405, 513, 641];
const DEFAULT_LEVELS = [1, 8, 16, 24, 32, 40, 52, 64, 76, 92, 108, 128];

export function keepCaption(keep: number, levelCount = 12): string {
  if (keep === 0) return "Nothing kept. The model begins a fresh story of its own.";
  if (keep === levelCount) return "The passage exactly as it was encoded. Nothing is sampled.";
  if (keep <= 3) return "Only the roughest shape survives. Almost all of this is the model's.";
  if (keep <= 7) return "Names and sentence shapes survive. The material inside them changes.";
  return "Nearly the passage. Small slips and substitutions.";
}

function wordSet(text: string): Set<string> {
  return new Set(
    text
      .split(/\s+/)
      .map((word) => word.toLowerCase().replace(/[^a-z']/g, ""))
      .filter(Boolean),
  );
}

export function survival(source: string, text: string): number {
  const base = wordSet(source);
  if (base.size === 0) return 0;
  let hits = 0;
  for (const word of wordSet(text)) if (base.has(word)) hits += 1;
  return Math.round((hits / base.size) * 100);
}

export function Instrument({
  desk,
  live,
  onDeskChange,
  onRunWeather,
  onTrace,
}: {
  desk: Desk;
  live: LiveState | null;
  onDeskChange: () => Promise<void>;
  onRunWeather: (text: string, keep: number) => void;
  onTrace?: (trace: Trace | null) => void;
}) {
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const requestCounter = useRef(0);
  const [text, setText] = useState(desk.draft.text);
  const [tokens, setTokens] = useState<TokenCount | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [tracing, setTracing] = useState(false);
  const [keep, setKeep] = useState(6);
  const [seed, setSeed] = useState<number>(() => randomSeed());
  const [variation, setVariation] = useState<Variation | null>(null);
  const [varying, setVarying] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loadingModel, setLoadingModel] = useState(false);

  const ready = live?.state === "ready";
  const levels = trace?.levels ?? DEFAULT_LEVELS;
  const tooLong = Boolean(tokens?.too_long);
  const empty = text.trim() === "";

  // The passage follows the project. A new project brings its own draft.
  useEffect(() => {
    setText(desk.draft.text);
    setTrace(null);
    setVariation(null);
    if (editorRef.current) editorRef.current.value = desk.draft.text;
  }, [desk.project.id]);

  // Load the model once, so the first keystroke is not the slow one.
  useEffect(() => {
    if (!live || live.state !== "unloaded" || loadingModel) return;
    setLoadingModel(true);
    void api("/api/v1/live/load", { method: "POST" })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoadingModel(false));
  }, [live?.state]);

  // Autosave the draft and count tokens.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      void api("/api/v1/draft", { method: "PUT", body: JSON.stringify({ text }) }).catch((reason: Error) =>
        setError(reason.message),
      );
      void api<TokenCount>("/api/v1/tokenize-preview", { method: "POST", body: JSON.stringify({ text }) })
        .then(setTokens)
        .catch((reason: Error) => setError(reason.message));
    }, 250);
    return () => window.clearTimeout(handle);
  }, [text]);

  // Trace the passage when it settles.
  useEffect(() => {
    if (!ready || empty || tooLong || tokens === null) return;
    const handle = window.setTimeout(() => {
      setTracing(true);
      setError("");
      void api<Trace>("/api/v1/live/trace", { method: "POST", body: JSON.stringify({ text }) })
        .then((next) => {
          setTrace(next);
          onTrace?.(next);
        })
        .catch((reason: Error) => setError(reason.message))
        .finally(() => setTracing(false));
    }, 450);
    return () => window.clearTimeout(handle);
  }, [text, ready, tokens?.token_count, tooLong]);

  // Vary whenever the trace, the dial, or the seed changes. Stale answers are dropped.
  useEffect(() => {
    if (!trace || trace.text !== text) return;
    const ticket = (requestCounter.current += 1);
    const handle = window.setTimeout(() => {
      setVarying(true);
      void api<Variation>("/api/v1/live/vary", {
        method: "POST",
        body: JSON.stringify({ codes: trace.codes, keep, seed }),
      })
        .then((next) => {
          if (ticket === requestCounter.current) setVariation(next);
        })
        .catch((reason: Error) => {
          if (ticket === requestCounter.current) setError(reason.message);
        })
        .finally(() => {
          if (ticket === requestCounter.current) setVarying(false);
        });
    }, 120);
    return () => window.clearTimeout(handle);
  }, [trace, keep, seed, text]);

  async function keepVariation() {
    if (!trace || !variation) return;
    setError("");
    try {
      await api<Revision>("/api/v1/live/keep", {
        method: "POST",
        body: JSON.stringify({
          source_text: trace.text,
          source_codes: trace.codes,
          source_padded_token_ids: trace.padded_token_ids,
          source_token_count: trace.token_count,
          variation: variationBody(variation),
        }),
      });
      setNotice(`Kept the variation at ${variation.keep}. The passage stays as it is.`);
      await onDeskChange();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function keepFrame(level: number) {
    if (!trace) return;
    const frame = trace.frames[level - 1];
    setError("");
    try {
      await api<Revision>("/api/v1/live/keep-frame", {
        method: "POST",
        body: JSON.stringify({
          source_text: trace.text,
          source_codes: trace.codes,
          source_padded_token_ids: trace.padded_token_ids,
          source_token_count: trace.token_count,
          level,
          text: frame.text,
          raw_token_ids: frame.raw_token_ids,
        }),
      });
      setNotice(`Kept the reading after pass ${level}.`);
      await onDeskChange();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function restore(revision: Revision) {
    setError("");
    try {
      await api(`/api/v1/passages/${revision.id}/select`, { method: "POST" });
      setText(revision.text);
      if (editorRef.current) editorRef.current.value = revision.text;
      await onDeskChange();
      editorRef.current?.focus();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const modelLine = (() => {
    if (!live) return "Checking the model.";
    if (live.state === "unavailable") return live.message || "The TinyStories checkpoint is not available.";
    if (live.state === "unloaded" || loadingModel) return "Loading the model. A few seconds.";
    if (tooLong) return `This passage is ${tokens?.token_count} tokens. The model reads at most ${tokens?.text_length}.`;
    if (empty) return "Write or paste a passage to begin.";
    if (tracing) return "Reading the passage.";
    return "";
  })();

  const gaugePct = tokens ? Math.min(100, Math.round((tokens.token_count / tokens.text_length) * 100)) : 0;
  const pieces = trace && variation ? wordDiff(trace.text, variation.text) : [];
  const history = desk.revisions.slice().reverse();

  return (
    <div className="page stack" style={{ gap: "2.4rem" }}>
      <div className="banner" aria-live="polite">
        {error && <p className="error">{error}</p>}
        {!error && notice && <p>{notice}</p>}
        {!error && !notice && modelLine && <p className="quiet">{modelLine}</p>}
      </div>

      <section className="two">
        <div className="stack">
          <label className="eyebrow" htmlFor="passage">
            Passage
          </label>
          <textarea
            id="passage"
            className="passage"
            ref={editorRef}
            defaultValue={desk.draft.text}
            onChange={(event) => {
              setNotice("");
              setText(event.target.value);
            }}
            spellCheck
          />
          <div className="stack" style={{ gap: "0.35rem" }}>
            <div className={tooLong ? "gauge over" : "gauge"} aria-hidden="true">
              <i style={{ width: `${gaugePct}%` }} />
            </div>
            <p className="mono" style={{ margin: 0 }}>
              {tokens ? `${tokens.token_count} of ${tokens.text_length} tokens.` : "Counting tokens."} The model reads the
              whole window at once; a short passage is mostly silence to it.
            </p>
          </div>
        </div>

        <div className="stack" style={{ gap: "1.1rem" }}>
          <div className="titled">
            <h2>Twelve passes</h2>
            <span>one code, then 8, then 16 … then 128. Each pass refines the last.</span>
          </div>
          <div className={trace ? undefined : "pending"}>
            <Band
              levels={levels}
              codes={trace?.codes ?? new Array(641).fill(0)}
              keep={keep}
              changed={variation && trace && variation.source_codes.length === trace.codes.length ? variation.changed : undefined}
            />
          </div>
          <div className="dial">
            <label htmlFor="keep">
              <span className="big">Keep {keep}</span>
              <span className="of">of {levels.length} passes</span>
            </label>
            <input
              id="keep"
              type="range"
              min={0}
              max={levels.length}
              step={1}
              value={keep}
              onChange={(event) => setKeep(Number(event.target.value))}
            />
            <p>{keepCaption(keep, levels.length)}</p>
          </div>
        </div>
      </section>

      <section className="two">
        <div className="stack">
          <div className="titled">
            <h2>What the model reads back</h2>
            <span>the passage decoded after each pass</span>
          </div>
          {trace ? (
            <>
              <div className="frames">
                {trace.frames.map((frame, index) => (
                  <div className="frame" key={frame.level} style={{ opacity: 0.55 + 0.45 * (index / 11) }}>
                    <span className="mono">
                      pass {frame.level}
                      <br />
                      {CUMULATIVE[index]} codes
                    </span>
                    <p className={showAll ? undefined : "clamp"}>{frame.text.trim() || "(nothing decodable)"}</p>
                    {showAll && (
                      <div className="frame-actions">
                        <button type="button" className="quiet-button" onClick={() => void keepFrame(frame.level)}>
                          Keep this reading
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="row">
                <button type="button" onClick={() => setShowAll((value) => !value)}>
                  {showAll ? "Show two lines per pass" : "Show every line"}
                </button>
              </div>
            </>
          ) : (
            <p className="quiet">The twelve readings appear here once a passage is read.</p>
          )}
        </div>

        <div className="stack">
          <div className="titled">
            <h2>Variation at {keep}</h2>
            {variation && (
              <span className="mono">
                seed {variation.seed} · {(variation.ms / 1000).toFixed(2)} s · keeps {survival(trace?.text ?? "", variation.text)}
                % of the source's words
              </span>
            )}
          </div>
          <div className={varying ? "card pending" : "card"}>
            {variation ? (
              <p className="prose diff">
                {pieces.map((piece, index) =>
                  piece.kind === "same" ? (
                    <span key={index}>{piece.text}</span>
                  ) : piece.kind === "removed" ? (
                    <del key={index}>{piece.text}</del>
                  ) : (
                    <ins key={index}>{piece.text}</ins>
                  ),
                )}
                {variation.text.trim() === "" && <span className="quiet">(nothing decodable)</span>}
              </p>
            ) : (
              <p className="quiet" style={{ margin: 0 }}>
                Move the dial and the variation appears here.
              </p>
            )}
          </div>
          <p className="quiet" style={{ margin: 0, fontSize: "0.85rem" }}>
            Struck words were in the passage. Underlined words are the model's. Nothing here is saved until you keep it.
          </p>
          <div className="row">
            <button type="button" className="primary" disabled={!variation || varying} onClick={() => void keepVariation()}>
              Keep this
            </button>
            <button type="button" disabled={!trace} onClick={() => setSeed(randomSeed())}>
              Reroll
            </button>
            <button type="button" disabled={!trace} onClick={() => onRunWeather(text, keep)}>
              Run the weather
            </button>
          </div>
        </div>
      </section>

      <section className="history-rail">
        <div className="titled">
          <h2>Kept</h2>
          <span>every saved passage in this project, newest first. Choose one to put it on the desk.</span>
        </div>
        {history.length === 0 ? (
          <p className="quiet">Nothing kept yet.</p>
        ) : (
          <ul className="history">
            {history.map((revision) => (
              <li key={revision.id}>
                <button
                  type="button"
                  aria-current={revision.id === desk.selected_revision_id ? "true" : undefined}
                  onClick={() => void restore(revision)}
                >
                  <span className="origin">{revision.origin_kind}</span>
                  {revision.disposition === "rejected" && <span className="flag">Rejected</span>}
                  <span className="preview">{(revision.text.trim() || "(empty)").slice(0, 140)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="row" style={{ marginTop: "0.8rem" }}>
          <a href="/api/v1/exports/reading.txt" download>
            Download as text
          </a>
          <a href="/api/v1/exports/reading.json" download>
            Download as JSON
          </a>
        </p>
      </section>
    </div>
  );
}
