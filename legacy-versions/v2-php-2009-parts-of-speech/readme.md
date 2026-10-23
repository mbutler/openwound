# Openwound v2 — PHP, 2009 — parts of speech, aborted

The pages are titled "Open Wound 2". This is an unfinished port of the v1 flow.

`PosTagger.php` tags text from the bundled `lexicon.txt`. The Tag button in `index.php` posts to `tag.php`, which prints the tagged text. The Generate button posts back to `index.php`, which only tags again. Substitution, the common-word skip, and the recombined text were never written.

`ow.php` is a smaller tagging script with the same tagger.
