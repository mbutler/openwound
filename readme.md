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

v4 is a local studio for writing with the released Next-Concept Modeling TinyStories model. The requirements are in `ncm_art_studio_openwound_v4_technical_spec.md`. The pinned research code is in `vendor/ncm` at commit `c702742`. The first build step is the inference contract: encode a passage, reconstruct all twelve levels, and generate variations that retain none, three, or all of those levels. A random short model with the released architectural flags passes that contract in `tests/adapter`. The released TinyStories checkpoint also loads. A CPU smoke record, with the source reconstruction and two variations that keep the first three levels, is in `fixtures/recorded/tinystories-cpu-fp32-eager-v1.json`.
