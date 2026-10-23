from tokenization.tokenizer import Tokenizer
import regex as re
import pickle


class BPETokenizer(Tokenizer):
    def __init__(self, vocab, merges, special_tokens=None):
        super().__init__()
        self.vocab = vocab
        self.reverse_vocab = {value: key for key, value in vocab.items()}
        self.merges = {merge: idx for idx, merge in enumerate(merges)}
        self.vocab_size = len(vocab)
        
        self.special_tokens = special_tokens
        self.special_token_ids = {token: idx for idx, token in enumerate(special_tokens.values())} if special_tokens else {}
        self.special_tokens_reverse_ids = {v: k for k, v in self.special_token_ids.items()} if special_tokens else {}
        self.eos_token_id = self.special_token_ids.get('<|endoftext|>', None)
        self.pad_token_id = self.special_token_ids.get('<|pad|>', None)
        
    @classmethod
    def from_config(cls, config):
        with open(config.vocab_file_path, 'rb') as file:
            vocab = pickle.load(file)
        with open(config.merges_file_path, 'rb') as file:
            merges = pickle.load(file)
        return BPETokenizer(vocab, merges, config.special_tokens)
    
    def _get_byte_pairs(self, byt_str):
        byte_pairs = []
        for idx in range(len(byt_str)-1):
            byte_pairs.append(tuple([byt_str[idx], byt_str[idx+1]]))
        return byte_pairs
    
    def encode(self, text: str):
        special_tokens = sorted(self.special_tokens.values(), reverse=True) if self.special_tokens != None else []
        
        if special_tokens:
            pattern = "|".join([re.escape(special_token) for special_token in special_tokens])
            text = re.split(f"({pattern})", text)
        else:
            text = [text]
        
        pattern = r"""'(?:[sdmt]|ll|ve|re)| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
            
        text = [re.findall(pattern, chunk) if (chunk and chunk not in special_tokens) else [chunk] for chunk in text]

        parse_word = lambda word: tuple(bytes([byt])for byt in word)
                    
        text = [[parse_word(word.encode("utf-8")) if not word in special_tokens else word for word in chunk] for chunk in text if chunk != ['']]
        
        new_words = []
          
        for chunk in text:
            for word in chunk:
                if word in special_tokens:
                    new_words.append(word.encode("utf-8"))
                else:
                    merge_exists = True
                    new_word = word
                    while merge_exists:
                        earliest_merge_idx = len(self.merges)
                        earliest_merge = None
                        candidate_merges = self._get_byte_pairs(new_word)
                        for candidate_merge in candidate_merges:
                            if candidate_merge in self.merges and self.merges[candidate_merge] < earliest_merge_idx:
                                earliest_merge = candidate_merge
                                earliest_merge_idx = self.merges[candidate_merge]
                                
                        if earliest_merge != None:
                            merge_exists = True
                            tmp = []
                            idx = 0
                            while idx < len(new_word):
                                if idx < len(new_word) - 1 and new_word[idx:idx+2] == earliest_merge:
                                    tmp.append(earliest_merge[0] + earliest_merge[1])
                                    idx +=2
                                else:
                                    tmp.append(new_word[idx])
                                    idx +=1
                            new_word = tuple(tmp)
                        else:
                            merge_exists = False 
                            earliest_merge = None 
                    new_words+= [w for w in new_word]    
        return [self.reverse_vocab[byte_pair] for byte_pair in new_words]
    
    def decode(self, ids: list[int], skip_special_tokens: bool = False):
        
        if skip_special_tokens and self.special_tokens != None:
            ids = [id for id in ids if id not in self.special_token_ids.values()]
            
        byts_list = [self.vocab[id] for id in ids]
        tmp  = []
        for byts in byts_list:
            tmp += list(byts)
            
        try:
            return bytes(tmp).decode("utf-8", errors="replace")
        except UnicodeDecodeError as e:
            return ''