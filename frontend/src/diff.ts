export type DiffPiece = { kind: "same" | "added" | "removed"; text: string };

export function splitWords(text: string): string[] {
  return text.match(/\s+|\S+/g) ?? [];
}

/** Word diff that keeps each run of punctuation and whitespace intact. */
export function wordDiff(before: string, after: string): DiffPiece[] {
  const left = splitWords(before);
  const right = splitWords(after);
  const scores: number[][] = Array.from({ length: left.length + 1 }, () =>
    Array(right.length + 1).fill(0),
  );
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      scores[i][j] =
        left[i] === right[j]
          ? scores[i + 1][j + 1] + 1
          : Math.max(scores[i + 1][j], scores[i][j + 1]);
    }
  }
  const pieces: DiffPiece[] = [];
  const push = (kind: DiffPiece["kind"], text: string) => {
    const last = pieces[pieces.length - 1];
    if (last && last.kind === kind) last.text += text;
    else pieces.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (left[i] === right[j]) {
      push("same", left[i]);
      i += 1;
      j += 1;
    } else if (scores[i + 1][j] >= scores[i][j + 1]) {
      push("removed", left[i]);
      i += 1;
    } else {
      push("added", right[j]);
      j += 1;
    }
  }
  while (i < left.length) {
    push("removed", left[i]);
    i += 1;
  }
  while (j < right.length) {
    push("added", right[j]);
    j += 1;
  }
  return pieces;
}
