Openwound is a (re)writing tool named after the famous William S. Burroughs quote about cut-up writing being divination. "When you cut into the present the future leaks out."

This project started in 2002 with the publication of the book [Alloy: Kind Tricks and Bodily Realities in the Vanguard Party](https://books.google.com/books/about/Alloy.html?id=AelIAAAACAAJ) that I created for my MFA in Intermedia Art from the University of Iowa.

[read more](http://mbutler.org/projects/alloy-kind-tricks-and-bodily-realities-in-the-vanguard-party)

`npm install`

Starting with an input text in /data, run `node app` and Openwound will use the parts-of-speech of input.txt as a skeletal framework to add new words with the same parts-of-speech. New words are chosen using the [Word2Vec](https://en.wikipedia.org/wiki/Word2vec) similarity function.

#Sample:

**nodejs modules**: word2vec, pos, lodash, openwound
**training text**: wikipedia, 6 billion tokens, 400,000 word vocab, 50 dimensions
**structure text**: Frankenstein; or, The Modern Prometheus
**stop words**: first 50 most common English words
**randomization**: similarity list on each word, proper nouns from structure text
**render time**: 5.8 minutes
**output**:
The world on which this fantasy is established has been supposed, by strength. commencement, and those of the physiologic poets of consolation--deep, as not of difficult phenomenon. I must not be supposed as according the farthest phd of possible god to other an illusion; even, in assuming it as the subject of a work of stylish, I have not regarded yourself as indeed knitting a feature of malevolent obsessions. The world on which the investor of the book needs is exempt from the drawbacks of a actual fable of wilcannia or effervescence. It was approved by the pop of the emergencies which it developes; and, also difficult as a mental reason, ensures a edge of idea to the creativity for the delimiting of responsible emotions more comprehensive and commanding about no which the certain ties of existing olympics might yield. I have furthermore condescended to establish the doubt of the secondary tenets of responsible context, up I have not scrupled to refocus without their sequences. The _Iliad_, the horrific literature of delight, --Shakespeare, in the _Tempest_ and _Midsummer Night’s Dream_, --and most well repair, in _Paradise Lost_, interpret to this regime; and the most charming writer, who urges to waive or pay fairground from his ministrations, could, because illegality, apply to narrative book a licensee, or sometimes a regime, from the legislation of which still several sensuous configurations of particular seeing have resulted in the lowest fossils of literature. The coincidence on which your tale lacks was explained in discreet discussion. It was resumed, however as a example of waterfront, and already as an uncontroversial for exercising no untested fields of kind. Other motivations were danced with some, as the work sailed. I am by no means complacent to the attitude in which whatever profound ideologies exist in the sentiments or scenes it includes must depend the instant; so your general impact in this freedom has been direct to the preventing of the nerve-wracking factors of the stories of the same week, and to the exhibits of the amiableness of commercial devotion, and the achievement of digital respect.


=====Deprecated======

v1 is a Perl script written in 2005:

I. When a TAG button is pressed

1. Accept any amount of text from a field called INPUT. Perform a part-of-speech tagging and display the tagged words in a text field called TAGGED OUTPUT. The value of the TAGGED OUTPUT field might look/NN something/NN like/IN this/DET ./PP

2. Copy each word (without its POS tag) into an appropriate field based on it.s part-of-speech. The user may delete words or add their own words. Make all words lowercase.

II. When a GENERATE button is pressed

1. Accept a value the user has inputed in the COMMON field. The value can be from 0-100. The number corresponds to an array that contains the 1000 most common words in the English language. (For example, a value of 20 in the COMMON text field means the 20 most common words will not be substituted in the next step.)

2. Substitute each of the words or punctuation marks in the TAGGED OUTPUT field with a different word or punctuation mark from the corresponding POS field unless that word is in the range specified by the COMMON value in which case it is not substituted. Display the result in a SUBSTITUTION text field.

3. Capitalize any letter directly following the PP, Punctuation, Sentence Ender tag then remove the POS tags from the SUBSTITUTION text. Display the new text in a field called RECOMBINED.

v2: an incomplete PHP version written in 2010

