import { useEffect, useRef, useState } from "react";
import { ApiError, api, randomSeed, variationBody, type LiveState, type Variation } from "./api";
import { wordDiff } from "./diff";
import { keepCaption, survival } from "./Instrument";

type Telling = {
  step: number;
  reset: boolean;
  trimmed: boolean;
  inputText: string;
  variation: Variation;
};

const MAX_STEPS = 48;

/** Memory Weather: the passage is told again, and the telling becomes the next passage. */
export function Weather({
  initialText,
  initialKeep,
  live,
  onKept,
  onAdopt,
}: {
  initialText: string;
  initialKeep: number;
  live: LiveState | null;
  onKept: () => Promise<void>;
  onAdopt: (text: string) => void;
}) {
  const abort = useRef(false);
  const [source, setSource] = useState(initialText);
  const [keep, setKeep] = useState(Math.min(11, Math.max(1, initialKeep)));
  const [steps, setSteps] = useState(10);
  const [resetEvery, setResetEvery] = useState(0);
  const [overflow, setOverflow] = useState<"trim" | "stop">("trim");
  const [tellings, setTellings] = useState<Telling[]>([]);
  const [running, setRunning] = useState(false);
  const [stopped, setStopped] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [kept, setKept] = useState(false);

  useEffect(() => {
    setSource(initialText);
  }, [initialText]);

  useEffect(() => () => {
    abort.current = true;
  }, []);

  async function run() {
    if (live?.state !== "ready") {
      setError("The model is not ready.");
      return;
    }
    abort.current = false;
    setRunning(true);
    setStopped("");
    setError("");
    setNotice("");
    setKept(false);
    setTellings([]);
    let current = source;
    const told: Telling[] = [];
    for (let step = 0; step < steps; step += 1) {
      if (abort.current) {
        setStopped("Stopped. The tellings so far are kept on screen.");
        break;
      }
      const reset = resetEvery > 0 && step > 0 && step % resetEvery === 0;
      if (reset) current = source;
      try {
        const variation = await api<Variation>("/api/v1/live/vary", {
          method: "POST",
          body: JSON.stringify({ text: current, keep, seed: randomSeed(), trim: overflow === "trim" }),
        });
        told.push({
          step,
          reset,
          trimmed: variation.trimmed,
          inputText: variation.source_text ?? current,
          variation,
        });
        setTellings([...told]);
        if (variation.text.trim() === "") {
          setStopped("No text available for the next cycle.");
          break;
        }
        current = variation.text;
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : String(reason);
        if (reason instanceof ApiError && (reason.code === "INPUT_TOO_LONG" || reason.code === "INPUT_EMPTY")) {
          setStopped(`The next telling could not be read: ${message}`);
        } else {
          setError(message);
        }
        break;
      }
    }
    setRunning(false);
  }

  async function keepRun() {
    if (tellings.length === 0) return;
    setError("");
    try {
      await api("/api/v1/live/keep-run", {
        method: "POST",
        body: JSON.stringify({
          source_text: source,
          keep,
          steps: tellings.map((telling) => ({
            reset: telling.reset,
            trimmed: telling.trimmed,
            input_text: telling.inputText,
            input_codes: telling.variation.source_codes,
            input_padded_token_ids: telling.variation.source_padded_token_ids,
            input_token_count: telling.variation.source_token_count,
            variation: variationBody(telling.variation),
          })),
        }),
      });
      setKept(true);
      setNotice(`Kept ${tellings.length} ${tellings.length === 1 ? "telling" : "tellings"}, each with the one it was told from.`);
      await onKept();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const bars = tellings.map((telling) => survival(source, telling.variation.text));
  const ready = live?.state === "ready";

  return (
    <div className="page stack" style={{ gap: "2rem" }}>
      <div className="banner" aria-live="polite">
        {error && <p className="error">{error}</p>}
        {!error && notice && <p>{notice}</p>}
      </div>
      <div className="titled">
        <h1>Memory Weather</h1>
        <span style={{ maxWidth: "60ch" }}>
          The passage is told again. The telling becomes the next passage. Each time, the first passes are kept and the
          rest are sampled fresh.
        </span>
      </div>

      <section className="two">
        <div className="stack" style={{ gap: "1.4rem" }}>
          <div className="stack" style={{ gap: "0.5rem" }}>
            <label className="eyebrow" htmlFor="weather-source">
              Source
            </label>
            <textarea
              id="weather-source"
              className="passage"
              style={{ minHeight: "11rem", fontSize: "1.15rem" }}
              value={source}
              disabled={running}
              onChange={(event) => setSource(event.target.value)}
            />
          </div>
          <div className="settings">
            <label>
              Keep {keep} of 12
              <input
                type="range"
                min={1}
                max={11}
                value={keep}
                disabled={running}
                onChange={(event) => setKeep(Number(event.target.value))}
              />
            </label>
            <label>
              Tellings
              <input
                type="number"
                min={1}
                max={MAX_STEPS}
                value={steps}
                disabled={running}
                onChange={(event) => setSteps(Math.max(1, Math.min(MAX_STEPS, Number(event.target.value) || 1)))}
              />
            </label>
            <label>
              Return to the source every
              <select value={resetEvery} disabled={running} onChange={(event) => setResetEvery(Number(event.target.value))}>
                <option value={0}>never</option>
                <option value={2}>2 tellings</option>
                <option value={3}>3 tellings</option>
                <option value={4}>4 tellings</option>
                <option value={6}>6 tellings</option>
              </select>
            </label>
            <label>
              When a telling overflows the window
              <select value={overflow} disabled={running} onChange={(event) => setOverflow(event.target.value as "trim" | "stop")}>
                <option value="trim">cut it to the window</option>
                <option value="stop">stop the weather</option>
              </select>
            </label>
          </div>
          <p className="quiet" style={{ margin: 0, fontSize: "0.9rem" }}>
            {keepCaption(keep)}
          </p>
          <div className="row">
            {running ? (
              <button
                type="button"
                onClick={() => {
                  abort.current = true;
                }}
              >
                Stop
              </button>
            ) : (
              <button type="button" className="primary" disabled={!ready || source.trim() === ""} onClick={() => void run()}>
                {tellings.length ? "Run again" : "Run"}
              </button>
            )}
            <button type="button" disabled={running || tellings.length === 0 || kept} onClick={() => void keepRun()}>
              {kept ? "Kept" : "Keep this run"}
            </button>
          </div>
          {!ready && <p className="quiet" style={{ margin: 0 }}>{live?.message || "The model is loading."}</p>}
          {tellings.length > 0 && (
            <div className="stack" style={{ gap: "0.4rem" }}>
              <span className="eyebrow">Weather</span>
              <div className="bars" role="img" aria-label="How much of the source survives each telling">
                {Array.from({ length: Math.max(tellings.length, steps) }, (_, index) => (
                  <i
                    key={index}
                    className={index < bars.length ? undefined : "faint"}
                    style={{ height: `${index < bars.length ? Math.max(3, bars[index]) : 3}%` }}
                  />
                ))}
              </div>
              <p className="mono" style={{ margin: 0 }}>
                share of the source's words still present, telling by telling
              </p>
            </div>
          )}
        </div>

        <div className="stack">
          {tellings.length === 0 && !running && (
            <p className="quiet">Run the weather and the tellings appear here, one by one.</p>
          )}
          <div className="tellings">
            {tellings.map((telling) => {
              const pieces = wordDiff(telling.inputText, telling.variation.text);
              return (
                <div key={telling.step}>
                  {telling.reset && <div className="telling reset">returned to the source</div>}
                  {telling.trimmed && (
                    <div className="telling reset">
                      the last telling overflowed the window and was cut to {telling.variation.source_token_count} tokens
                    </div>
                  )}
                  <div className="telling">
                    <span className="mono">
                      telling {telling.step + 1}
                      <br />
                      {telling.variation.source_token_count ?? "?"} tok
                    </span>
                    <div className="stack" style={{ gap: "0.4rem" }}>
                      <p className="diff">
                        {pieces.map((piece, index) =>
                          piece.kind === "same" ? (
                            <span key={index}>{piece.text}</span>
                          ) : piece.kind === "removed" ? (
                            <del key={index}>{piece.text}</del>
                          ) : (
                            <ins key={index}>{piece.text}</ins>
                          ),
                        )}
                        {telling.variation.text.trim() === "" && <span className="quiet">(nothing decodable)</span>}
                      </p>
                      <div>
                        <button type="button" className="quiet-button" onClick={() => onAdopt(telling.variation.text)}>
                          Put this telling on the instrument
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
            {running && (
              <div className="telling pending">
                <span className="mono">telling {tellings.length + 1}</span>
                <p className="quiet" style={{ fontFamily: "inherit", fontSize: "0.9rem" }}>
                  telling…
                </p>
              </div>
            )}
            {stopped && (
              <div className="telling stopped">
                <span className="mono">stopped</span>
                <p>{stopped}</p>
              </div>
            )}
          </div>
          {tellings.length > 0 && (
            <p className="quiet" style={{ margin: 0, fontSize: "0.85rem" }}>
              Each telling is compared with the one it was told from. Underlined words arrived; struck words left.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
