from tokenization.tokenizer import Tokenizer


class SudokuTokenizer(Tokenizer):
    vocab_size = 12
    blank_token_id = 0
    row_separator_id = 10
    bos_token_id = 11
    pad_token_id = None
    eos_token_id = None
    seq_len = 89
    prompt_len = 91

    @classmethod
    def from_config(cls, config):
        return cls()

    def encode(self, text):
        text = text.replace('<BOS>', 'B')
        chars = {'_': 0, '|': 10, 'B': 11, **{str(i): i for i in range(10)}}
        return [chars[c] for c in text if not c.isspace()]

    def decode(self, ids, skip_special_tokens=False):
        chars = ['_'] + list('123456789') + ['|', '<BOS>']
        return ''.join(chars[int(i)] for i in ids
                       if not (skip_special_tokens and int(i) == self.bos_token_id))
