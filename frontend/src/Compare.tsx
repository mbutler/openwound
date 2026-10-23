import { useEffect, useState } from "react";
import { api } from "./api";

type Encoding = {
  id: string;
  kind: string;
  text: string;
  title: string;
  token_count: number | null;
  passage_revision_id: string;
};

type Pair = {
  representation_id: string;
  text: string;
  title: string;
  token_count: number | null;
  agreement: number;
  adjusted: number | null;
  shared_prefix: boolean;
  same_band: boolean;
  note: string;
};

type Comparison = {
  id: string;
  prefix_count: number;
  query: Encoding;
  baseline: { state: string; value: number | null; count: number; message: string };
  pairs: Pair[];
};

type Entry = { id: string; revision_id: string; text: string; removed: boolean };

export function Compare({
  projectId,
  passage,
  entries,
}: {
  projectId: string | null;
  passage: { id: string; text: string; title: string } | null;
  entries: Entry[];
}) {
  const [encodings, setEncodings] = useState<Encoding[]>([]);
  const [prefix, setPrefix] = useState(3);
  const [queryId, setQueryId] = useState<string | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [graft, setGraft] = useState("");
  const [sides, setSides] = useState<{ title: string; text: string }[] | null>(null);
  const [tooLong, setTooLong] = useState(false);

  async function refresh() {
    if (!projectId) return;
    const listed = await api<{ encodings: Encoding[] }>(`/api/v1/projects/${projectId}/comparisons/encodings`);
    setEncodings(listed.encodings);
  }

  useEffect(() => {
    setEncodings([]);
    setComparison(null);
    setError("");
    if (!projectId) return;
    let cancel = false;
    refresh().catch((reason: Error) => {
      if (!cancel) setError(reason.message);
    });
    return () => {
      cancel = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!passage) {
      setTooLong(false);
      return;
    }
    let cancel = false;
    api<{ too_long: boolean }>("/api/v1/tokenize-preview", {
      method: "POST",
      body: JSON.stringify({ text: passage.text }),
    })
      .then((count) => {
        if (!cancel) setTooLong(count.too_long);
      })
      .catch(() => {
        if (!cancel) setTooLong(false);
      });
    return () => {
      cancel = true;
    };
  }, [passage]);

  useEffect(() => {
    if (!projectId || !jobId) return;
    const timer = window.setInterval(() => {
      void api<{
        state: string;
        progress: { stage?: string };
        error: { message?: string } | null;
        result: {
          skipped?: { message: string }[];
          sides?: { title: string; text: string }[];
          text?: string;
          message?: string;
          changed?: boolean;
        } | null;
      }>(`/api/v1/jobs/${jobId}`)
        .then(async (job) => {
          if (job.state === "queued" || job.state === "running") {
            setProgress(job.progress.stage ? `${job.progress.stage}.` : "Encoding.");
            return;
          }
          setJobId(null);
          setProgress("");
          if (job.state !== "succeeded" && job.state !== "cancelled") {
            setError(job.error?.message || "The encoding was not saved.");
            return;
          }
          const skipped = job.result?.skipped?.[0]?.message;
          if (skipped) setError(skipped);
          if (job.result?.sides) setSides(job.result.sides);
          if (job.result?.text) setGraft(job.result.message ? `${job.result.message} ${job.result.text}` : job.result.text);
          await refresh();
        })
        .catch((reason: Error) => setError(reason.message));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, jobId]);

  async function encode(body: { fragment_ids?: string[]; passage_revision_ids?: string[] }) {
    if (!projectId) return;
    setError("");
    const queued = await api<{ id: string }>(`/api/v1/projects/${projectId}/comparisons/encodings`, {
      method: "POST",
      body: JSON.stringify({ client_request_id: crypto.randomUUID(), ...body }),
    });
    setProgress("Encoding.");
    setJobId(queued.id);
  }

  async function compare(nextQuery = queryId, nextPrefix = prefix) {
    if (!projectId || !nextQuery) return;
    setError("");
    setQueryId(nextQuery);
    const result = await api<Comparison>(`/api/v1/projects/${projectId}/comparisons`, {
      method: "POST",
      body: JSON.stringify({ query_representation_id: nextQuery, prefix_count: nextPrefix }),
    });
    setComparison(result);
  }

  async function reconstruct(otherId: string) {
    if (!projectId || !queryId) return;
    setError("");
    setSides(null);
    const queued = await api<{ id: string }>(`/api/v1/projects/${projectId}/comparisons/reconstructions`, {
      method: "POST",
      body: JSON.stringify({
        client_request_id: crypto.randomUUID(),
        left_representation_id: queryId,
        right_representation_id: otherId,
        prefix_count: prefix,
      }),
    });
    setProgress("Reconstructing the pair.");
    setJobId(queued.id);
  }

  async function graftCodes(otherId: string) {
    if (!projectId || !queryId) return;
    setError("");
    setGraft("");
    const result = await api<{ id?: string; changed?: boolean; queued?: boolean; message?: string }>(
      `/api/v1/projects/${projectId}/comparisons/grafts`,
      {
        method: "POST",
        body: JSON.stringify({
          client_request_id: crypto.randomUUID(),
          base_representation_id: queryId,
          donor_representation_id: otherId,
          prefix_count: prefix,
        }),
      },
    );
    if (result.changed === false) {
      setGraft(result.message || "Those codes already agree. Nothing was generated.");
      return;
    }
    if (result.id) {
      setProgress("Preparing a latent graft.");
      setJobId(result.id);
    }
  }

  if (!projectId) return null;

  return (
    <section className="work-panel" aria-label="Compare encodings">
      <h2>Compare encodings</h2>
      {error && <p className="error">{error}</p>}
      <p>
        Slot agreement compares saved codes at a prefix. It is not a measure of shared meaning. Latent graft replaces codes. It does not move a phrase.
      </p>
      {passage && (
        <p>
          <button type="button" onClick={() => void encode({ fragment_ids: [passage.id] }).catch((reason: Error) => setError(reason.message))} disabled={tooLong || Boolean(jobId)}>
            Encode this passage
          </button>
          {tooLong && <span className="legend"> This passage is longer than the TinyStories window. It was not encoded.</span>}
        </p>
      )}
      {entries.filter((entry) => !entry.removed).map((entry) => (
        <p key={entry.id}>
          <span className="prose">{entry.text}</span>
          <button type="button" onClick={() => void encode({ passage_revision_ids: [entry.revision_id] }).catch((reason: Error) => setError(reason.message))} disabled={Boolean(jobId)}>
            Encode this entry
          </button>
        </p>
      ))}
      {progress && <p className="legend">{progress}</p>}
      {encodings.length === 0 && <p>Encode a passage to compare its codes.</p>}
      {encodings.length > 0 && (
        <>
          <p>
            {[1, 2, 3].map((depth) => (
              <button
                key={depth}
                type="button"
                aria-pressed={prefix === depth}
                onClick={() => {
                  setPrefix(depth);
                  if (queryId) void compare(queryId, depth).catch((reason: Error) => setError(reason.message));
                }}
              >
                First {depth} {depth === 1 ? "level" : "levels"}
              </button>
            ))}
          </p>
          <label>
            Prefix depth
            <input
              type="number"
              min={1}
              max={12}
              value={prefix}
              onChange={(event) => {
                const next = Number(event.target.value);
                setPrefix(next);
                if (queryId && next >= 1) void compare(queryId, next).catch((reason: Error) => setError(reason.message));
              }}
            />
          </label>
          <ul className="hits">
            {encodings.map((item) => (
              <li key={item.id}>
                <label>
                  <input
                    type="radio"
                    name="comparison-query"
                    checked={queryId === item.id}
                    onChange={() => void compare(item.id).catch((reason: Error) => setError(reason.message))}
                  />
                  {item.title}
                  {item.token_count != null ? `, ${item.token_count} tokens` : ""}
                </label>
                <p className="prose">{item.text}</p>
              </li>
            ))}
          </ul>
        </>
      )}
      {comparison && (
        <article>
          <h3>Agreement at the first {comparison.prefix_count} {comparison.prefix_count === 1 ? "level" : "levels"}</h3>
          <p>{comparison.baseline.message}</p>
          {comparison.pairs.length === 0 && <p>No other compatible encoding is saved.</p>}
          <ul className="hits">
            {comparison.pairs.map((pair) => (
              <li key={pair.representation_id}>
                <article>
                  <h4>{pair.title}</h4>
                  <p className="prose">{pair.text}</p>
                  <p>
                    Slot agreement {pair.agreement.toFixed(3)}
                    {pair.adjusted != null ? `. Adjusted ${pair.adjusted.toFixed(3)}.` : ""}
                    {pair.token_count != null ? ` ${pair.token_count} tokens.` : ""}
                  </p>
                  {pair.note && <p className="legend">{pair.note}</p>}
                  <button type="button" onClick={() => void reconstruct(pair.representation_id).catch((reason: Error) => setError(reason.message))} disabled={Boolean(jobId)}>
                    Reconstruct this pair
                  </button>
                  <button type="button" onClick={() => void graftCodes(pair.representation_id).catch((reason: Error) => setError(reason.message))} disabled={Boolean(jobId)}>
                    Latent graft
                  </button>
                </article>
              </li>
            ))}
          </ul>
        </article>
      )}
      {sides && (
        <div className="pair">
          {sides.map((side) => (
            <div key={side.title + side.text}>
              <h4>{side.title}</h4>
              <p className="prose">{side.text}</p>
            </div>
          ))}
        </div>
      )}
      {graft && <p>{graft}</p>}
    </section>
  );
}
