# Openwound

Openwound is a (re)writing tool named after the famous William S. Burroughs quote about cut-up writing being divination. "When you cut into the present the future leaks out."

This project started in 2002 with the publication of the book [Alloy: Kind Tricks and Bodily Realities in the Vanguard Party](https://books.google.com/books/about/Alloy.html?id=AelIAAAACAAJ) that I created for my MFA in Intermedia Art from the University of Iowa. [Read more](http://mbutler.org/alloy-kind-tricks-and-bodily-realities-in-the-vanguard-party/). I originally used a DOS program called [Babble](https://archive.org/details/Babble_1020). Every version since is a new language and a new way of choosing the words that replace the original.

Babble (2002) predates these versions and lives outside this repository. The three implementations that are here are archived under `legacy-versions/`, and each file keeps the history it had before the move. This directory is the working tree for the Python version.

## Versions

| | Year | Language | Method | Where |
|---|---|---|---|---|
| v1 | 2005 | Perl | Parts of speech. Substitute each word with another word of the same tag, drawn from the source text. | `legacy-versions/v1-perl-2005-parts-of-speech` |
| v2 | 2009 | PHP | The same parts-of-speech idea, retagged with a bundled lexicon. Tagging works. Generation was never written. | `legacy-versions/v2-php-2009-parts-of-speech` |
| v3 | 2016 | Node.js | Word vectors plus parts of speech. Keep the source grammar and replace words with GloVe neighbors that share the tag. | `legacy-versions/v3-node-2016-word-vectors` |
| v4 | 2026 | Python | Next-Concept Modeling. Encode a short passage as a twelve-level residual hierarchy, reconstruct it level by level, and vary it by keeping a prefix of those codes. | `.` |

v2 carries the same method as v1. It is a separate version because the program was rewritten and then left unfinished, and because the pages call themselves "Open Wound 2". The `version` field in v3's `package.json` is `2.5.0`, from when that package was the code at the root of this repo. The generation number is v3.

## v4

v4 is a local studio for writing with the released Next-Concept Modeling TinyStories model. The requirements are in `ncm_art_studio_openwound_v4_technical_spec.md`. The pinned research code is in `vendor/ncm` at commit `c702742`. A passage is encoded as a twelve-level residual hierarchy, reconstructed level by level, and varied by keeping a prefix of those codes. A random short model with the released architectural flags passes that contract in `tests/adapter`. The released TinyStories checkpoint also loads. A CPU smoke record is in `fixtures/recorded/tinystories-cpu-fp32-eager-v1.json`.

The Instrument is the interface for that work. Write or paste a passage, and the model reads it as it settles: the twelve passes are drawn as a band of code cells, the twelve readings appear below, and one dial, Keep, chooses how many passes stay fixed while the rest are sampled. The variation changes under the dial in well under a second on a CPU. Nothing is written until you keep it; a kept variation records the exact encoding, the sampled hierarchy, the seed, and its parent. Memory Weather tells the passage again a finite number of times, each telling becoming the next passage, and shows how much of the source survives. A kept run is a chain of revisions. From the repository root, with the environment in `.venv` and the interface built in `frontend/dist`:

```
.venv/bin/python -m ncm_art.cli serve
```

That listens on `127.0.0.1:8765`. The API process loads TinyStories the first time the Instrument asks, which takes a few seconds. It also starts the worker for the slower jobs under Archive; that worker stays up when the checkpoint is missing. `.venv/bin/python -m ncm_art.cli doctor` checks the pinned model files first. To rebuild the interface, run `npm run build` in `frontend`.

Archive holds Correspondences. Import a UTF-8 `.txt` or `.md` file, or paste text. The original bytes are kept, and paragraphs can be read with the passages around them. Shared-word search works with no model. Related meaning uses the pinned MiniLM embedding model:

```
.venv/bin/python -m ncm_art.cli models install minilm-l6-v2
```

Those weights stay in `.model-cache` and are not committed. If they are missing, shared-word search still works. A saved correspondence reopens with its passages and interpretation history.

A work is a separate ordered text. Transfer a selected passage into it. Bind the influence that withholds a marked name, preview the passage with that name replaced by `_____`, and add it to the work. The name stays in the index until it is returned. Previewing does not change the work, and the desk draft is left alone.

Mark one occurrence in an entry and ask a configured local model to replace only that span. The model sees the entry with that occurrence removed. Nothing is added until the repair is adopted, and the name rule does not apply. Without a provider, the work stays as it is. Download the work as text, or a project archive that imports as a new project. The provider address lives outside the project, in `{library}/instruction.json` or `NCM_ART_INSTRUCTION_URL` and `NCM_ART_INSTRUCTION_MODEL`. The API key is only `NCM_ART_INSTRUCTION_API_KEY`.

Correspondences can also encode a passage that fits the TinyStories window and compare its saved codes with another encoding. The figure is slot agreement at a chosen prefix, with a common-code baseline inside 16-token length bands. Latent graft replaces codes in that prefix and regenerates what follows. Transfer still copies text. Encoding, pair reconstruction, and a graft that changes codes need the TinyStories checkpoint. Agreement between codes that are already saved does not.

A work entry can also be healed around a marked span. The configured instruction provider sees only the surroundings and returns the text before and after that span. The span itself is put back by the server and stays protected. Without a provider, the entry stays as it is.
