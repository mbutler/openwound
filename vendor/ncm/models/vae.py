import torch
import torch.nn as nn
from torch.nn import functional as F
import math

class LayerNorm(nn.Module):
    def __init__(self, ndim, bias=False):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(ndim))
        self.bias = nn.Parameter(torch.zeros(ndim)) if bias else None

    def forward(self, input):
        return F.layer_norm(input, self.weight.shape, self.weight, self.bias, 1e-6)


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x):
        orig_dtype = x.dtype
        x_f = x.float()
        rms = x_f.pow(2).mean(dim=-1, keepdim=True).add_(self.eps).rsqrt_()
        return (x_f * rms).to(orig_dtype) * self.weight


class SelfAttention(nn.Module):
    def __init__(self, config):
        super().__init__()
        assert config.n_embd % config.n_head == 0
        self.c_attn = nn.Linear(config.n_embd, 3 * config.n_embd, bias=config.bias)
        self.c_proj = nn.Linear(config.n_embd, config.n_embd, bias=config.bias)
        self.attn_dropout = nn.Dropout(config.dropout)
        self.resid_dropout = nn.Dropout(config.dropout)
        self.n_head = config.n_head
        self.n_embd = config.n_embd
        self.dropout = config.dropout
        self.use_qk_norm = bool(getattr(config, "use_qk_norm", False))
        if self.use_qk_norm:
            head_dim = config.n_embd // config.n_head
            self.q_norm = RMSNorm(head_dim)
            self.k_norm = RMSNorm(head_dim)
        # attn_window=w restricts attention to |i-j| <= w; 0 means full.
        self.attn_window = int(getattr(config, "attn_window", 0) or 0)
        assert hasattr(torch.nn.functional, "scaled_dot_product_attention")

    def _window_mask(self, T, device):
        i = torch.arange(T, device=device)
        return (i[:, None] - i[None, :]).abs() <= self.attn_window

    def forward(self, x):
        B, T, C = x.size()
        q, k, v = self.c_attn(x).split(self.n_embd, dim=2)
        k = k.view(B, T, self.n_head, C // self.n_head).transpose(1, 2)
        q = q.view(B, T, self.n_head, C // self.n_head).transpose(1, 2)
        v = v.view(B, T, self.n_head, C // self.n_head).transpose(1, 2)

        if self.use_qk_norm:
            q = self.q_norm(q)
            k = self.k_norm(k)

        attn_mask = self._window_mask(T, x.device) if self.attn_window > 0 else None
        y = torch.nn.functional.scaled_dot_product_attention(
            q, k, v, attn_mask=attn_mask, dropout_p=self.dropout if self.training else 0
        )
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        y = self.resid_dropout(self.c_proj(y))
        return y


class MLP(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.c_fc = nn.Linear(config.n_embd, 4 * config.n_embd, bias=config.bias)
        self.gelu = nn.GELU()
        self.c_proj = nn.Linear(4 * config.n_embd, config.n_embd, bias=config.bias)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x):
        x = self.c_fc(x)
        x = self.gelu(x)
        x = self.c_proj(x)
        x = self.dropout(x)
        return x


class Block(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.ln_1 = LayerNorm(config.n_embd, bias=config.bias)
        self.attn = SelfAttention(config)
        self.ln_2 = LayerNorm(config.n_embd, bias=config.bias)
        self.mlp = MLP(config)

    def forward(self, x):
        x = x + self.attn(self.ln_1(x))
        x = x + self.mlp(self.ln_2(x))
        return x

class Encoder(nn.Module):
    def __init__(
        self,
        in_vocab_size,
        context_length,
        embed_dim,
        n_layers,
        compression_factor=4,
        kernel_size=8,
        stride=2,
        bias=False,
        padding=3,
        dropout=0.1,
        enc_layers=0,
        use_qk_norm=False,
        enc_attn_window=0,
        enc_conv_layers=0,
        enc_conv_kernel=3,
        use_pos_emb=True,
    ):
        super().__init__()

        assert compression_factor ==1 or compression_factor % 2 == 0, "Compression factor must be a power of 2"
        self.compression_factor = compression_factor
        self.wte = nn.Embedding(in_vocab_size, embed_dim)
        self.wpe = nn.Embedding(context_length, embed_dim) if use_pos_emb else None
        self.drop = nn.Dropout(dropout)

        self.blocks = nn.ModuleList([
            Block(config=type("Config", (object,), {
                "n_embd": embed_dim, "n_head": n_layers, "bias": True,
                "dropout": dropout, "use_qk_norm": use_qk_norm,
                "attn_window": int(enc_attn_window)}))
            for _ in range(int(enc_layers))
        ])
        k = int(enc_conv_kernel)
        self.conv_blocks = nn.ModuleList()
        for _ in range(int(enc_conv_layers)):
            c1 = nn.Conv1d(embed_dim, embed_dim, k, padding=k // 2)
            c2 = nn.Conv1d(embed_dim, embed_dim, k, padding=k // 2)
            nn.init.zeros_(c2.weight); nn.init.zeros_(c2.bias)
            self.conv_blocks.append(nn.ModuleDict({
                "ln": LayerNorm(embed_dim), "c1": c1, "c2": c2}))
        self.ln_e = LayerNorm(embed_dim) if (int(enc_layers) > 0 or int(enc_conv_layers) > 0) else None

        # Sequence compression: f>1 shortens the sequence before quantization; init is an average pool.
        self.down = None
        if int(compression_factor) > 1:
            f = int(compression_factor)
            conv = nn.Conv1d(embed_dim, embed_dim, kernel_size=f, stride=f, bias=True)
            with torch.no_grad():
                conv.weight.zero_()
                idx = torch.arange(embed_dim)
                conv.weight[idx, idx, :] = 1.0 / f
                conv.bias.zero_()
            self.down = conv

    def _conv_stack(self, x):
        for blk in self.conv_blocks:
            h = blk["ln"](x).transpose(1, 2)
            h = blk["c2"](F.gelu(blk["c1"](h))).transpose(1, 2)
            x = x + h
        return x

    def forward(self, idx):
        tok_emb = self.wte(idx)
        if self.wpe is not None:
            pos = torch.arange(0, idx.size(1), dtype=torch.long, device=idx.device)
            tok_emb = tok_emb + self.wpe(pos)
        x = self.drop(tok_emb)
        x = self._conv_stack(x)
        for blk in self.blocks:
            x = blk(x)
        if self.ln_e is not None:
            x = self.ln_e(x)
        if self.down is not None:
            x = self.down(x.transpose(1, 2)).transpose(1, 2)
        return x

    def forward_nopos(self, idx):
        B, T, C = idx.shape[0], idx.shape[1], self.wte.embedding_dim
        pos = torch.arange(T, device=idx.device, dtype=torch.float32).unsqueeze(1)
        i = torch.arange(0, C, 2, device=idx.device, dtype=torch.float32)
        div = torch.exp(-math.log(10000.0) * i / C)
        pe = torch.zeros(T, C, device=idx.device, dtype=torch.float32)
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        x = self.drop(self.wte(idx) + pe.to(self.wte.weight.dtype).unsqueeze(0))
        x = self._conv_stack(x)
        for blk in self.blocks:
            x = blk(x)
        if self.ln_e is not None:
            x = self.ln_e(x)
        return x


class Decoder(nn.Module):
    def __init__(
        self,
        in_vocab_size,
        embed_dim,
        n_layers,
        compression_factor=4,
        kernel_size=8,
        stride=2,
        bias=False,
        padding=3,
        dropout=0.1,
        use_qk_norm=False,
        dec_layers=1,
        use_pos_emb=False,
        context_length=None,
    ):
        super().__init__()

        assert compression_factor ==1 or compression_factor % 2 == 0, "Compression factor must be a power of 2"

        self.wpe = nn.Embedding(int(context_length), embed_dim) if use_pos_emb else None
        self.drop = nn.Dropout(dropout)
        self.ln_f = LayerNorm(embed_dim)
        self.compression_factor = compression_factor

        # n_layers is the head count here, not a depth.
        _cfg = type("Config", (object,), {
            "n_embd": embed_dim, "n_head": n_layers, "bias": True,
            "dropout": dropout, "use_qk_norm": use_qk_norm})
        self.middle_block = Block(config=_cfg)
        self.extra_blocks = nn.ModuleList(
            [Block(config=_cfg) for _ in range(max(0, int(dec_layers) - 1))]
        )

        self.output_layer = nn.Linear(embed_dim, in_vocab_size, bias=False)
        self.ln_f = LayerNorm(embed_dim)

        self.up = None
        if int(compression_factor) > 1:
            f = int(compression_factor)
            convT = nn.ConvTranspose1d(embed_dim, embed_dim, kernel_size=f, stride=f, bias=True)
            with torch.no_grad():
                convT.weight.zero_()
                idx = torch.arange(embed_dim)
                convT.weight[idx, idx, :] = 1.0
                convT.bias.zero_()
            self.up = convT


    def forward(self, z):
        if self.up is not None:
            z = self.up(z.transpose(1, 2)).transpose(1, 2)
        if self.wpe is not None:
            z = z + self.wpe(torch.arange(z.shape[1], dtype=torch.long, device=z.device))
        x = self.middle_block(z)
        for blk in self.extra_blocks:
            x = blk(x)
        x = self.ln_f(x)
        x = self.output_layer(x)
        return x
    
    
if __name__ == "__main__": 
    encoder = Encoder(in_vocab_size=1000, context_length=512, compression_factor=1, embed_dim=256, n_layers=1)
    decoder = Decoder(in_vocab_size=1000, embed_dim=256, compression_factor=1, n_layers=1)

    print(encoder)
    print(decoder)
    sample_input = torch.randint(0, 1000, (2, 512))
    encoded_output = encoder(sample_input)
    decoded_output = decoder(encoded_output)

    print("Encoded output shape:", encoded_output.shape)
    print("Decoded output shape:", decoded_output.shape)