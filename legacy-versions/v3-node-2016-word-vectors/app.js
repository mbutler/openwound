var pos = require('pos');
var _ = require('lodash');
var fs = require('fs');
var w2v = require('word2vec');

var tagger = new pos.Tagger();
var lexer = new pos.Lexer();
var inputText = fs.readFileSync('./data/input.txt',"UTF-8");
var numOfStopWords = 50;
var stopwords = ["the", "of", "and", "to", "a", "in", "that", "is", "was", "he", "for", "it", "with", "as", "his", "on", "be", "at", "by", "I", "this", "had", "not", "are", "but", "from", "or", "have", "an", "they", "which", "one", "were", "you", "all", "her", "she", "there", "would", "their", "we", "him", "been", "has", "when", "who", "will", "no", "more", "if", "out", "its", "so", "up", "said", "what", "about", "than", "into", "them", "can", "only", "other", "time", "new", "some", "could", "these", "two", "may", "first", "then", "do", "any", "like", "my", "now", "over", "such", "our", "man", "me", "even", "most", "made", "after", "also", "well", "did", "many", "before", "must", "years", "back", "through", "much", "where", "your", "way", "down", "should", "because", "long", "each", "just", "state", "people", "those", "too", "how", "Mr", "little", "good", "world", "make", "very", "year", "still", "see", "own", "work", "men", "day", "get", "here", "old", "between", "both", "life", "being", "under", "three", "never", "know", "same", "last", "another", "while", "us", "off", "might", "great", "states", "go", "come", "since", "against", "right", "came", "take", "used", "himself", "few", "house", "american", "use", "place", "during", "high", "without", "again", "home", "around", "small", "however", "found", "Mrs", "part", "school", "thought", "went", "say", "general", "once", "upon", "every", "left", "war", "dont", "does", "got", "united", "number", "hand", "course", "water", "until", "always", "away", "public", "something", "fact", "less", "through", "far", "put", "head", "think", "called", "set", "almost", "enough", "end", "took", "government", "night", "yet", "system", "better", "four", "nothing", "told", "eyes", "city", "going", "president", "why", "days", "present", "point", "didn't", "look", "find", "asked", "second", "group", "later", "next", "room", "social", "business", "knew", "program", "give", "half", "side", "face", "toward", "white", "five", "let", "young", "form", "given", "per", "order", "large", "several", "national", "important", "possible", "rather", "big", "among", "case", "often", "early", "john", "things", "looked", "ever", "become", "best", "need", "within", "felt", "along", "children", "saw", "church", "light", "power", "least", "family", "development", "interest", "others", "open", "thing", "seemed", "want", "area", "god", "members", "mind", "help", "country", "service", "turned", "door", "done", "law", "although", "whole", "line", "problem", "sense", "certain", "different", "kind", "began", "thus", "means", "matter", "perhaps", "name", "times", "york", "itself", "action", "human", "above", "week", "company", "free", "example", "hands", "local", "show", "history", "whether", "act", "either", "gave", "death", "feet", "today", "across", "body", "past", "quite", "taken", "anything", "field", "having", "seen", "word", "car", "experience", "im", "money", "really", "class", "words", "already", "college", "information", "tell", "making", "sure", "themselves", "together", "full", "air", "shall", "held", "known", "period", "keep", "political", "real", "miss", "probably", "century", "question", "seems", "behind", "cannot", "major", "office", "brought", "special", "whose", "boy", "cost", "federal", "economic", "self", "south", "problems", "heard", "six", "study", "ago", "became", "moment", "run", "available", "job", "street", "result", "short", "west", "age", "change", "position", "board", "individual", "reason", "turn", "close", "areas", "am", "love", "society", "level", "court", "control", "true", "community", "force", "ill", "type", "front", "wife", "center", "future", "hard", "policy", "seem", "clear", "town", "voice", "wanted", "woman", "common", "department", "girl", "black", "party", "land", "necessary", "surface", "top", "following", "rate", "sometimes", "tax", "mother", "music", "students", "low", "military", "child", "further", "third", "red", "university", "able", "education", "feel", "provide", "effect", "morning", "nations", "total", "near", "road", "stood", "art", "figure", "outside", "north", "million", "washington", "leave", "value", "cut", "usually", "fire", "plan", "play", "sound", "therefore", "english", "evidence", "table", "book", "strong", "range", "believe", "living", "peace", "various", "mean", "modern", "says", "soon", "lines", "looking", "schools", "single", "alone", "longer", "minutes", "personal", "process", "secretary", "gone", "idea", "months", "situation", "women", "increase", "nor", "section", "america", "pressure", "private", "started", "dark", "ground", "dr", "east", "nature", "stage", "finally", "kept", "call", "father", "needed", "values", "greater", "expected", "view", "thats", "everything", "space", "ten", "union", "basis", "spirit", "brown", "required", "taking", "complete", "conditions", "except", "hundred", "late", "moved", "ones", "wrote", "hours", "return", "support", "attention", "hour", "live", "particular", "recent", "data", "hope", "person", "beyond", "coming", "dead", "middle", "cold", "costs", "else", "forces", "heart", "material", "couldnt", "developed", "feeling", "fine", "story", "inside", "lost", "read", "report", "research", "twenty", "industry", "instead", "miles", "son", "wall", "added", "amount", "followed", "makes", "move", "pay", "basic", "cant", "including", "building", "defense", "hold", "reached", "simply", "tried", "central", "wide", "committee", "equipment", "picture", "island", "simple", "actually", "care", "religious", "shown", "friends", "river", "beginning", "getting", "higher", "medical", "received", "rest", "sort", "boys", "doing", "floor", "foreign", "terms", "trying", "indeed", "administration", "cent", "difficult", "subject", "especially", "meeting", "earth", "market", "paper", "passed", "walked", "blue", "bring", "county", "labor", "hall", "natural", "police", "similar", "training", "England", "final", "growth", "international", "property", "talk", "working", "written", "congress", "food", "girls", "start", "wasnt", "answer", "hear", "issue", "purpose", "suddenly", "weeks", "western", "needs", "stand", "youre", "considered", "countries", "fall", "hair", "likely", "nation", "lay", "sat", "cases", "color", "entire", "french", "happened", "paid", "production", "ready", "results", "square", "difference", "earlier", "involved", "meet", "step", "stock", "thinking", "William", "Christian", "club", "letter", "aid", "increased", "lot", "month", "particularly", "whom", "below", "effort", "knowledge", "lower", "points", "sent", "trade", "using", "industrial", "size", "yes", "bad", "bill", "certainly", "eye", "ideas", "temperature", "addition", "deal", "due", "method", "methods", "moral", "reading", "decided", "directly", "nearly", "neither", "questions", "record", "showed", "statements", "throughout", "anyone", "programs", "try", "according", "member", "physical", "science", "services", "southern", "hot", "remember", "Soviet", "strength", "comes", "normal", "trouble", "understand", "volume", "population", "summer", "trial", "appeared", "bed", "concerned", "district", "led", "merely", "sales", "student", "direction", "friend", "maybe", "piece", "ran", "army", "blood", "continued", "degree", "direct", "evening", "game", "green", "husband", "list", "literature", "plane", "association", "average", "cause", "generally", "george", "influence", "met", "provided", "seven", "systems", "chance", "changes", "easy", "former", "freedom", "hell", "meaning", "opened", "shot", "spring", "ways", "works", "wrong", "fear", "organization", "planning", "series", "term", "theory", "ask", "effective", "lead", "myself", "respect", "stopped", "wouldnt", "clearly", "efforts", "forms", "groups", "movement", "plant", "truth", "worked", "based", "beautiful", "consider", "farm", "horse", "hotel", "mans", "note", "press", "somewhat", "treatment", "arms", "charge", "placed", "apparently", "carried", "feed", "herself", "hes", "hit", "ive", "length", "numbers", "operation", "persons", "radio", "reaction", "born", "manner", "oh", "recently", "running", "approach", "chief", "deep", "eight", "immediately", "larger", "performance", "price", "sun", "couple", "daily", "gun", "lived", "main", "stop", "straight", "heavy", "image", "march", "opportunity", "technical", "test", "understanding", "writing", "additional", "british", "decision", "described", "determined", "europe", "fiscal", "negro", "progress", "served", "window", "cars", "character", "quality", "religion", "reported", "responsibility", "steps", "appear", "serious", "account", "ball", "communist", "corner", "design", "learned", "moving", "post", "activity", "forward", "pattern", "pool", "poor", "slowly", "specific", "staff", "types", "activities", "audience", "choice", "filled", "growing", "justice", "latter", "letters", "nuclear", "obtained", "returned", "democratic", "doubt", "obviously", "parts", "plans", "thirty", "established", "figures", "foot", "function", "include", "leaders", "mass", "saying", "standard", "stay", "attack", "closed", "drive", "gives", "speak", "waiting", "whatever", "completely", "covered", "faith", "hospital", "language", "race", "season", "wish", "built", "designed", "distance", "effects", "extent", "glass", "income", "lack", "products", "ahead", "analysis", "corps", "elements", "existence", "expect", "firm", "married", "principle", "there's"]
var commonList = _.take(stopwords, numOfStopWords);
var parts = {
		CC: [],
		CD: [],
		DT: [],
		EX: [],
		FW: [],
		IN: [],
		JJ: [],
		JJR: [],
		JJS: [],
		LS: [],
		MD: [],
		NN: [],
		NNP: [],
		NNPS: [],
		NNS: [],
		POS: [],
		PDT: [],
		PP$: [],
		PRP: [],
		PRP$: [],
		RB: [],
		RBR: [],
		RBS: [],
		RP: [],
		SYM: [],
		TO: [],
		UH: [],
		VB: [],
		VBD: [],
		VBG: [],
		VBN: [],
		VBP: [],
		VBZ: [],
		WDT: [],
		WP: [],
		WP$: [],
		WRB: [],
		',': [],
		'!': [],
		'.': [],
		':': [],
		'$': [],
		'#': [],
		'"': [],
		'(': [],
		';': [],
		')': []
};

w2v.loadModel( './data/glove.6B.50d.txt', function(err, model){

	console.log("\nanalyzing word vectors...");
	
	//loop through the array of word/tag arrays
	_.forEach(taggedText, function(set) {		
		var originalWord = set[0];
		var originalTag = set[1];		
		var replacementWord = originalWord;
		var similarTag = '';
		var similarSet = [];
		var reindex = 0;		

		//get an array of 10 {word:, dist:} objects that are similar to the original word
		var similarityArray = checkSimilarity(model, originalWord);

		//loop through array of similar objects and tag each new word. Grab from right so most similar is last replacement word
		_.forEachRight(similarityArray, function(obj) {
			similarTag = tag(obj.word);

			//if tags are the same, take the new similar word
			if (similarTag === originalTag) {
				similarSet.push(obj.word);
				replacementWord = obj.word;				
			} else {
				//pick a random word from the list of same tags
			}
		});

		//adds random variance to picking replacement word from similarity list
		//0 is least similar word, similarSet.length -1 is most similar
		//using this instead of _.sample to allow for control over similarity if needed
		if (similarSet.length > 0) {
			reindex = _.random(0, similarSet.length - 1);
			replacementWord = similarSet[reindex];
		}

		//replace some nouns randomly. Add parts-of-speech to taste
		if (originalTag === "NNP") {
			replacementWord = _.sample(parts.NN);
		} else if (originalTag === "NNPS") {
			replacementWord = _.sample(parts.NNS);
		}

		//preserve a certain amount of stop words
		if (checkCommon(originalWord) === true) {
			replacementWord = originalWord;
		}

		//add appropriate spaces
		if (!_.includes([".", ",", "!", "?", ";"], replacementWord)) {
			replacementWord = " " + replacementWord;
		}
		
		//log out to command line and file
		console.log(replacementWord);
		fs.appendFileSync("./data/output.txt", replacementWord);
	});
});

// returns an array of N objects with best name and distance. In this case, ten
function checkSimilarity(model, name) {
	var mostSimilar = model.mostSimilar(name, 10);	
	return mostSimilar;
}

//returns the parts-of-speech tag for a single word
function tag(word) {
	var token = lexer.lex(word),
	    taggedWord = tagger.tag(token),
	    taggedToken = taggedWord[0],	    
	    tag = taggedToken[1]

	return tag;
}

//tags a length of text. [word, tag] array pushed to a list
function tagOriginal(text) {
	console.log("tagging parts-of-speech...");
	var list = lexer.lex(text);
	var taggedWords = tagger.tag(list);
	var taggedList = [];
    var i;

	for (i in taggedWords) {
		var taggedWord = taggedWords[i];
		var word = taggedWord[0];
		var tag = taggedWord[1];
		var set = [word, tag];

		parts[tag].push(word);
		taggedList.push(set);
	}

	return taggedList;
}

//returns boolean based on if a word is in the common list
function checkCommon(word) {
	return _.includes(commonList, word);
}

//tag the input text from file
var taggedText = tagOriginal(inputText);
