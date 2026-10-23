# Openwound v3 — Node.js, 2016 — word vectors and parts of speech

`app.js` tags `data/input.txt`, then replaces each word with a GloVe neighbor that has the same part of speech. Proper nouns are drawn at random from the nouns in the source. The first 50 most common English words are left in place. Results are printed and appended to `data/output.txt`.

The `version` field in `package.json` is `2.5.0`. That number is from when this package sat at the root of the repository. This generation is v3.

## Installation

The pre-trained word vector data needed for the Word2Vec module is not distributed with this project. It's an 822 MB download. For information on the _Wikipedia 2014 + Gigaword 5 GloVe_ set, visit the [Stanford Natural Language Processing Group glove page](http://nlp.stanford.edu/projects/glove/). Download it directly [here](http://nlp.stanford.edu/data/glove.6B.zip).

You'll probably want the *glove.6B.50d.txt* file, though you can experiment with the larger sets if you like. Place the *glove.6B.50d.txt* file in the `data` directory of this folder.

Next, you'll need to prepend the appropriate number of words and the length of the vector to the file. From the `data` directory, run:

`sed -i '1s/^/400000 50\n\n/' glove.6B.50d.txt`

From this folder:

`npm install`

Then, with an input text file at `data/input.txt`:

`node app`

## Sample

**nodejs modules**: word2vec, pos, lodash, openwound

**training text**: wikipedia, 6 billion tokens, 400,000 word vocab, 50 dimensions

**structure text**: Frankenstein; or, The Modern Prometheus

**stop words**: first 50 most common English words

**randomization**: similarity list on each word, proper nouns from structure text

**render time**: 5.8 minutes

**output**:

The world on which this fantasy is established has been supposed, by strength. commencement, and those of the physiologic poets of consolation--deep, as not of difficult phenomenon. I must not be supposed as according the farthest phd of possible god to other an illusion; even, in assuming it as the subject of a work of stylish, I have not regarded yourself as indeed knitting a feature of malevolent obsessions. The world on which the investor of the book needs is exempt from the drawbacks of a actual fable of wilcannia or effervescence. It was approved by the pop of the emergencies which it developes; and, also difficult as a mental reason, ensures a edge of idea to the creativity for the delimiting of responsible emotions more comprehensive and commanding about no which the certain ties of existing olympics might yield. I have furthermore condescended to establish the doubt of the secondary tenets of responsible context, up I have not scrupled to refocus without their sequences. The _Iliad_, the horrific literature of delight, --Shakespeare, in the _Tempest_ and _Midsummer Night’s Dream_, --and most well repair, in _Paradise Lost_, interpret to this regime; and the most charming writer, who urges to waive or pay fairground from his ministrations, could, because illegality, apply to narrative book a licensee, or sometimes a regime, from the legislation of which still several sensuous configurations of particular seeing have resulted in the lowest fossils of literature. The coincidence on which your tale lacks was explained in discreet discussion. It was resumed, however as a example of waterfront, and already as an uncontroversial for exercising no untested fields of kind. Other motivations were danced with some, as the work sailed. I am by no means complacent to the attitude in which whatever profound ideologies exist in the sentiments or scenes it includes must depend the instant; so your general impact in this freedom has been direct to the preventing of the nerve-wracking factors of the stories of the same week, and to the exhibits of the amiableness of commercial devotion, and the achievement of digital respect.
