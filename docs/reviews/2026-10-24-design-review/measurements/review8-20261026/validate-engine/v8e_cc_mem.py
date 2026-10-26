# Heap model of docspec-rs GraphTopology::from_table (topology.rs) per input row and token.
# Rust: String/Vec header 24 B; hashbrown slot = entry/0.875 + 1 ctrl byte; heap rounded to 16 B.
import math, sys
def r(n): return math.ceil(n/16)*16
def hm(entry): return entry/0.875 + 1
KEY=64      # source_id hex row_key
FILE=130    # iceberg/scratch data-file path in __docspec_file
TOK=64      # hex body/text/rendition token value
NS=8        # namespace string ("body", "text", ...)
DOC=64      # document_id hex
def est(rows, tok_occ, tok_distinct, body_occ):
    per_row = (24+r(KEY))            \
            + hm(24+8)+r(KEY)          \
            + 24+r(FILE) + 8           \
            + 8+1                      \
            + 24 + 24                  \
            + hm(24+8+24)+r(FILE)+r(DOC) \
            + 8+8                      # by_root/components row index
    per_tok_occ = 48 + r(NS) + r(TOK)  # row_tokens tuple + clones
    per_tok_distinct = hm(48+8) + r(NS) + r(TOK)
    per_body = 24 + r(TOK)
    total = rows*per_row + tok_occ*per_tok_occ + tok_distinct*per_tok_distinct + body_occ*per_body
    acct = rows*(KEY+FILE+32) + tok_occ*(NS+TOK+16)   # retained_bytes the code reserves
    return per_row, total, acct
for name,(R,TO,TD,B) in {
  "spec today: 1.68M source files, 2.3M token occ, 1.0M distinct, 1.6M body occ":(1.68e6,2.3e6,1.0e6,1.6e6),
  "4M rows, 2M tokens":(4e6,2e6,2e6,2e6),
}.items():
    pr,t,a=est(R,TO,TD,B)
    print(f"{name}: per-row {pr:.0f} B, total {t/2**30:.2f} GiB, budget-reserved {a/2**30:.2f} GiB, ratio {t/a:.1f}x; ARCH 13.4 = {8*4e6/2**20:.0f} MiB")
