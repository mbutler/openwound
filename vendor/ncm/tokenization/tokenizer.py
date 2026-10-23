from collections.abc import Iterable
import itertools

class Tokenizer(object):
    def encode(self, text: str):
        _ = text
        raise NotImplementedError("This method should be implemented in subclasses")
             
    def encode_iterable(self, iterable: Iterable[str]):
        itr = iter([])
        for text in iterable:
            itr = itertools.chain(itr, self.encode(text))
        return itr
    
    @classmethod
    def from_config(cls, config):
        _ = config
        raise NotImplementedError("This method should be implemented in subclasses")
    
    def encode_chunk(self, input_path, start, end):
        with open(input_path, "rb") as f:
            f.seek(start)
            chunk = f.read(end - start).decode("utf-8", errors="ignore")
            return self.encode(chunk)  
    
    def decode(self, ids: list[int], skip_special_tokens: bool = False):
        _ = ids
        raise NotImplementedError("This method should be implemented in subclasses")
    
    def decode_batch(self, ids_batch: list[list[int]], skip_special_tokens: bool = False):
        return [self.decode(ids, skip_special_tokens=skip_special_tokens) for ids in ids_batch]