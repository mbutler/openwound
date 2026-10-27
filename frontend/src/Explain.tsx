import { useEffect, useRef } from "react";
import type { TraceFrame } from "./api";

const LEVELS = [1, 8, 16, 24, 32, 40, 52, 64, 76, 92, 108, 128];

/** The first-run explanation. Uses the artist's own trace when one exists. */
export function Explain({
  open,
  frames,
  onClose,
}: {
  open: boolean;
  frames: TraceFrame[] | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  const picks = frames && frames.length === 12 ? [0, 3, 6, 11].map((index) => frames[index]) : null;
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="explain-title">
      <p className="eyebrow">How the model reads</p>
      <h1 id="explain-title">This model does not write one word at a time.</h1>
      <p className="lede">
        It writes the whole passage twelve times, rough to fine. The first pass decides one code for everything. The last
        pass decides a hundred and twenty-eight. Each pass adds detail to all of the one before.
      </p>
      <div className="two" style={{ gap: "2rem" }}>
        <div className="stack">
          <h2>Twelve passes, widening</h2>
          <div className="stairs" role="img" aria-label="Twelve bars widening from one code to one hundred and twenty-eight">
            {LEVELS.map((length, index) => (
              <div className="stair" key={length}>
                <span className="mono" style={{ textAlign: "right" }}>
                  {index + 1}
                </span>
                <i style={{ width: `${Math.max(1.5, (length / 128) * 85)}%`, opacity: 0.5 + 0.5 * (index / 11) }}>
                  <b>{length}</b>
                </i>
              </div>
            ))}
          </div>
          <p className="quiet" style={{ margin: 0, fontSize: "0.9rem" }}>
            A code is a choice from 4,096. The early passes fix the shape; the late passes fix the words. Keeping an
            early pass fixes its codes, not their meaning. The model does not know what a lantern is for.
          </p>
        </div>
        <div className="stack">
          <h2>Read back after each pass</h2>
          {picks ? (
            <div className="frames">
              {picks.map((frame) => (
                <div className="frame" key={frame.level}>
                  <span className="mono">pass {frame.level}</span>
                  <p className="clamp">{frame.text.trim() || "(nothing decodable)"}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="quiet" style={{ margin: 0 }}>
              Write a passage and the model's own readings of it will appear here, after passes 1, 4, 7, and 12.
            </p>
          )}
          <p className="quiet" style={{ margin: 0, fontSize: "0.9rem" }}>
            Keep some passes and the model finishes the rest. That is a variation. Tell it again and again and it drifts.
            That is the weather. Everything kept is saved with its parent, so you can always walk back.
          </p>
        </div>
      </div>
      <div className="row" style={{ marginTop: "1.4rem" }}>
        <button type="button" className="primary" onClick={onClose}>
          Begin with a passage
        </button>
        <span className="quiet" style={{ fontSize: "0.85rem" }}>Longer is better, up to the window of 128 tokens.</span>
      </div>
    </dialog>
  );
}
