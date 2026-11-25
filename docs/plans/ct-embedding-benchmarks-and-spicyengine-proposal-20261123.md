# Congressional-Tech Embedding Benchmarks & Final `spicyengine` Proposal

**Date:** `2026-11-23`  
**Related Local Codebase Targets:**
- `spicyengine` index DDL: [`spicyengine/src/spicyengine/indexing/prepared_index.py`](file:///Users/mikewolfd/Work/spicy-stack/spicyengine/src/spicyengine/indexing/prepared_index.py)
- `spicyengine` hybrid query fusion: [`spicyengine/src/spicyengine/search/hybrid.py`](file:///Users/mikewolfd/Work/spicy-stack/spicyengine/src/spicyengine/search/hybrid.py)
- `spicyengine` producer schema rules: [`spicyengine/docs/prepared-search.md`](file:///Users/mikewolfd/Work/spicy-stack/spicyengine/docs/prepared-search.md)
- Local inference engines: `/Users/mikewolfd/Work/fast-silicon/packages/{fast-pplx,fast-embeddinggemma-2,fast-bge-small}`

---

## 1. Executive Verdict & Recommended `spicyengine` Architecture

1. **Best Overall Retrieval Accuracy:** **Hybrid `BM25 (0.7) + fast-pplx (0.3)` in `spicyengine` (`SereneDB` `USING inverted` + `hnsw (metric='cosine')`)**. Neither dense model beats `BM25` on exact dollar/section citations (`0.7824` BM25 w/ header vs. `0.4962` `fast-pplx` vs. `0.3366` `fast-embeddinggemma-2`), while `BM25` collapses on redacted hearing Q&A turns (`0.2426`–`0.3416` vs. `0.5359`–`0.5410` dense).
2. **Best `10.5M`-Chunk RAM Efficiency (`<= 12 GB` SereneDB index RAM):** **`fast-embeddinggemma-2` at `512d mrl_int8`** (`+0.66 pp` *higher* than `768d fp32` on CT passages, `514 B/vec`, `5.4 GB` raw payload / `~8–12 GB` SereneDB HNSW `sq8`), or **`fast-pplx` `1024d`** (`~14–20 GB` SereneDB HNSW `sq8` at `10.5M` chunks, `0.00 pp` `sym_int8` / `+0.78 pp` `native_tanh_int8`).
3. **Never Default to Image Embeddings for Bulk Indexing:** On M4 Pro, `perplexity-ai/pplx-embed-v2-context-0.6b` PyTorch MPS (`bf16`) runs **`27.8×` slower at 150 DPI** (`1,935.0 ms/pg`, `0.517 pg/s`) and **`7.8×–8.4×` slower at 100 DPI** (`545.3–581.4 ms/pg`, `1.72–1.83 pg/s`) than **`fast-pplx` extracted text** (`69.5 ms/pg`, `14.39 pg/s` M4 Pro; `46.0 ms/pg`, `21.75 pg/s` Base M5), while pure-text OCR (`AppleVision`) + `fast-pplx` gives searchable BM25 tokens, exact match highlights, and still runs **an order of magnitude faster**. Reserve visual page embeddings strictly for low-text figures/charts/diagrams.
4. **Two High-Leverage `spicyengine` Additions:**
   - **Producer-side metadata header + upstream `fast-pplx` settings:** lifts `fast-pplx` deep-passage `Span-nDCG@10` from `0.3234 → 0.4890` (`+16.6 pp`) and `EmbeddingGemma-2` (`title: {hdr} | text: `) from `0.2269 → 0.3407` (`+11.4 pp`).
   - **Local query-embedder integration in `hybrid.py`** (replacing the current restriction where only `gemini-embedding-2` auto-embeds server-side) plus optional HNSW/IVF & `quant` configurability in `prepared_index.py`.

---

## 2. Aggregated CT Embedding Benchmark Ledger

### 2A. Cross-Task Quality Scoreboard (`220` Zero-Judge CT Queries)

*Locked slice drawn read-only from real CT hearings, witness statements, QFRs, bills, CRS/committee reports, and schedules across both Apple M4 Pro (`48 GB`) and Base M5 (`24 GB`, Apple10 NAX).*

| Task & Slice | `BM25` w/ `doc_header` (raw) | `fast-embeddinggemma-2` (`0.3B`) Best | `fast-pplx` (`0.6B`) Best | Winner & Margin |
| :--- | :---: | :---: | :---: | :--- |
| **Task 1: Doc Discovery** (`80` queries / `360` docs to `33K` tok) | `0.9707` `nDCG@10` | `0.9954` (`ml2048`, `QuestionAnswering`) | **`1.0000`** (`ml2048` or `MaxSim`) | **`fast-pplx`** (`80/80` perfect; `+0.46 pp`) |
| **Task 2: Deep Passage QA & Clauses** (`60` queries `@ char>=5000`, `6,483` chunks) | **`0.6354`** (`0.5265` raw) | `0.3407` M5 / `0.3418` M4P (`c256 ov160 title: {hdr}`) | **`0.4890`** (`c256`+`doc_header`) / `0.4590` (`ctx512 rep64`, `0.6519` recall) | Dense: **`fast-pplx` (`+14.8 pp`)**; Overall: **Hybrid `BM25 + fast-pplx`** |
| ↳ *Task 2A: Redacted Hearing/QFR Q→A Turns* (`20` queries) | `0.3416` (`0.2426` raw) | **`0.5410`** (`c512 title: {hdr}`) | **`0.5359`** (`ctx2048 rep128 meta`, `0.6804` recall) | **Dense `+19.4` to `+29.8 pp` over BM25** |
| ↳ *Task 2B: Deep Statutory & Dollar Clauses* (`40` queries `@ char>=6500`) | **`0.7824`** (`0.6685` raw) | `0.3366` (`c256 ov160 title: {hdr}`) | **`0.4962`** (`c256`+`doc_header`) | Dense: **`fast-pplx` (`+16.0 pp`)**; Citations: **`BM25`** |
| **Task 3: Same-Event Hearing Packet Linking** (`80` queries / `320` docs) | `0.5147` (`0.6271` `R@10`) | `0.5423` M5 / `0.5469` M4P (`ml2048`, `Retrieval-query`) | **`0.5996`** (`ml4096`+`doc_header`+`[Q] `, `0.7188` `R@10`) | **`fast-pplx`** (`+5.3–5.7 pp` vs Emb2, `+8.5 pp` vs BM25) |

### 2B. Upstream Parity & Default Fixes Verified in `fast-silicon`
All 4 upstream-alignment fixes in `fast-pplx` + workspace defaults are landed and hardware-verified (upstream cosine `1.000000`; `fast-pplx verify --mode all` passed on both M4 Pro `gpu=0.999989, ane=0.999373` and Base M5 `gpu=0.999991, ane=0.999373`):
1. **Default `[D] ` document prefix + excluded span** via `ContextualTokenizer.document_prefix_span` across `encode_documents`, `encode_texts`, `embed_parquet`, CLI (`--no-document-prefix` opt-out).
2. **`round(tanh(x) * 127)` quantization space** enabled by default (`apply_tanh: bool = True`).
3. **Contextual chunk `overlap` default `32 → 0`** (eliminates `-15%..40%` throughput loss).
4. **Global defaults locked:** `rerank_top_r = 256`, `embed_parquet --header-col / --header-text` + native `EmbeddingGemma-2` `"title: {hdr} | text: "` formatting, chip-aware `B=1` GPU vs. ANE dispatch, and `ane_profile="balanced"` (`min_cos = 0.9994` at 0 speed penalty).

### 2C. Critical Prompting, Chunking & Context-Length Findings
- **`doc_header` beats raw cover text:** Structured 1-line headers lift `fast-pplx` (`+16.6 pp`) and `EmbeddingGemma-2` (`+9.3..11.4 pp`), whereas 512 chars of cover boilerplate (`cover512_anchored`) *hurt* `EmbeddingGemma-2` (`-2.2 pp`).
- **Prefixes are non-negotiable:** Always pass `[Q] ` on `fast-pplx` queries (even doc-to-doc linking; dropping it costs `-8.70 pp` overall / `-11.77 pp` Q&A) and `QuestionAnswering` / `Retrieval-query` on `EmbeddingGemma-2` (using `Clustering`/`STS` loses `-17.2 pp`).
- **Avoid single-pass `16K`/`32K` pooling & `ctx4096`:** Single-pass `32K` (`678.5s`, `0.9587`) is `3.11×` slower and less accurate than **`encode_documents_multivector(window=2048, context=2048, rep=128) + MaxSim`** (`218.4s`, **`1.0000`** across `3.16M` tok). Keep contextual chunking at **`ctx512, rep64`** (`0.6519` recall) or **`ctx2048, rep128`** (`0.5359` Q&A turns); `ctx4096` dilutes headers (`0.3600` vs. `0.4134`).

### 2D. Hardware Throughput, Peak RAM & `323K`-Doc Archive Estimates

| Engine / Mode | Warm `B=1` Query (M5 / M4P) | Short Chunks `tok/s` (M5 / M4P) | Full CT Body (`2.7B` tok, `10.5M` chunks) | MLX / Process Peak |
| :--- | ---: | ---: | ---: | :--- |
| **`fast-embeddinggemma-2` (`hetero`)** | `3.05` / `2.76 ms` | **`49.7K`** / `36.4–40.5K` | **`15.1–18.3 hr`** M5 / `21.9–22.7 hr` M4P | `1.11` / `3.03 GB` |
| **`fast-embeddinggemma-2` (`ane`, `<=512`)** | `3.05` / **`2.69 ms`** | `23.0K` / `22.3K` | `32.6 hr` M5 / `33.6 hr` M4P | **`0.00 GB` GPU** / `1.4 GB` |
| **`fast-pplx` (`hetero2`, `balanced`)** | `9.07` / `7.66 ms` | **`23.9K`** / `18.8K` | **`31.3–36.7 hr`** M5 / `49.3 hr` (`ctx2048`) | `2.32` / `3.53 GB` |
| **`fast-pplx` (`gpu fp16`, `mmap`)** | **`6.07`** / `7.83 ms` | `17.1K` / `11.1K` | `~36–49 hr` M5 | `2.32` / `3.38 GB` |
| **`fast-pplx` (`ane`, `<=512`)** | `9.01` / `7.24 ms` | `11.0K` / `11.1K` | `68.4 hr` M5 / `67.4 hr` M4P | **`0.00 GB` GPU** / **`0.51 GB`** |

### 2E. MRL Dimensions & Quantization (`10.5M` Chunks Raw Vector Payload)
- **`fast-embeddinggemma-2` (MRL-trained):** **`512d mrl_int8`** (`514 B/vec` = **`5.4 GB`** raw for `10.5M` chunks) beats `768d fp32` (`0.3268` vs `0.3202`, `6×` smaller); `256d mrl_int8` is `2.7 GB` (`-1.80 pp`).
- **`fast-pplx` (non-MRL):** Keep full **`1024d`** (`sym_int8` `1,026 B/vec` = `10.8 GB`, `0.00 pp` loss; `native_tanh_int8` `1,024 B/vec`, `+0.78 pp`). Truncating `fast-pplx` to `512d` drops `-3.57 pp` (`-9.8 pp` at `256d`).

---

## 3. Image vs. Text Embedding Analysis (`pplx-embed-v2-context-0.6b`)

Measured on `16` real Congressional PDF pages (`3,073.8` chars/pg, `637.8` text tok/pg) on M4 Pro (`48 GB`):

| Pipeline / Precision | Resolution / Chunking | Tokens / Page | Speed (`ms/pg`) | Throughput (`pg/s`) | Driver / Peak Mem |
| :--- | :--- | ---: | ---: | ---: | :--- |
| **PyTorch MPS (`bf16`) Image** | `150 DPI` (`1.8M px`, `1260×1696`) | `1,725` vis tok | `1,935.0 ms` (`ViT 70% / LM 30%`) | `0.517 pg/s` | `4.48–6.84 GB` MPS |
| **PyTorch MPS (`bf16`) Image** | `100 DPI` (`600K px`, `840×1131`) | `563–570` vis tok | `545.3–581.4 ms` (`ViT 62% / LM 38%`) | `1.72–1.83 pg/s` | `5.70 GB` MPS |
| **PyTorch MPS (`bf16`) Text** | Extracted text (`single` / `ctx256`) | `637.8` text tok | `259.3–260.1 ms` | `3.85–3.86 pg/s` | `5.52 GB` MPS |
| **`fast-pplx` Text (M4 Pro GPU/Hetero2)** | Extracted text (`single` / `ctx256`) | `637.8` text tok | **`69.5 ms`** | **`14.39 pg/s`** (`27.8×` vs 150-DPI img) | `1.455 GB` MLX / `0.92 GB` RSS |

**Apple Silicon optimization headroom if visual embeddings are needed selectively:** reusing `fast-pplx`'s compiled causal LM (`30–38%` of cost), ink-tight margin cropping (`-40%` patches), CoreML ANE static-tile `conv1x1` bucketing (at `100 DPI` / `<=512` tokens per band), and native MLX `hd=64` fused SDPA + Q8 ViT yields an estimated **`~110–180 ms/pg` (`5.5–9 pg/s`, ~`3–5×` over MPS)** — making selective figure/chart embedding practical while keeping `fast-pplx` / `fast-embeddinggemma-2` pure text + BM25 for 98% of pages.

---

## 4. SereneDB Vector Indexing, RAM Sizing & Quantization Trade-Offs

- `spicyengine` already creates `USING inverted (..., "emb" hnsw (metric='cosine'))` while excluding the vector column from `INCLUDE (...)`, and SereneDB's `hnsw` defaults to **`sq8`** Scalar Quantization (`4×` smaller than `fp32`).
- **Why HNSW uses ~`1.5×–2.0×` vector RAM:** Graph hops are random pointer accesses (~`100 ns` DRAM vs `100 μs` NVMe random read). Layer-0 edge lists (`2 × M` neighbor pointers, ~`256–512 B/node` at `M=32`) + ID maps + BM25/filter bitmaps dominate once vectors shrink to `sq8`/`sq4`/`bq`, limiting further quantization memory savings while degrading recall on legal/statutory distinctions and forcing disk rescoring I/O under concurrency.
- **`ivf` (`sdb_ivf_search_nprobe`) tradeoffs:** Avoids holding the full index in RAM, but increases per-query bandwidth/latency and struggles under selective metadata filters (`WHERE filter_committee = ...` discards most of each scanned cluster).

| Corpus Size | `pgvector` HNSW (`fp32`) | SereneDB HNSW (`sq8` `1024d`, default) | SereneDB `512d emb2` (`hnsw` `sq8`) | Disk-Oriented (`ivf` / DiskANN) |
| ---: | :---: | :---: | :---: | :---: |
| **1M chunks** | ~5–6 GB | **~1.5–2.2 GB** | **~0.9–1.4 GB** | `< 0.5 GB` |
| **5M chunks** | ~25–30 GB | **~7–10 GB** | **~4–6 GB** | `~1–2 GB` |
| **10M chunks** | ~50–65 GB | **~14–20 GB** | **~8–12 GB** | `~2–4 GB` |
| **50M chunks** | ~250–320 GB | **~70–100 GB** | **~40–60 GB** | `~8–15 GB` |

---

## 5. Actionable `spicyengine` Integration Proposal

1. **Stage A (Producer Backfill):** Index bulk text on **Base M5** via `fast-pplx` (`[D] ` prefix + structured `doc_header` prepend: `ml2048` for `323K` whole docs [`1.0000` `nDCG@10`, `~0.6 GB` index], `c256 + doc_header` / `ctx512 rep64` for passage RAG) or `fast-embeddinggemma-2` (`512d` `title: {hdr} | text: ` if capping `10.5M` chunk index RAM under `12 GB`), emitting Parquet `emb` columns for SereneDB `hnsw (metric='cosine')` (`sq8`).
2. **Stage B (Local Query Embedder Hook in `hybrid.py`):** Allow `spicyengine` to embed interactive queries automatically against a lightweight local `fast-pplx` / `fast-embeddinggemma-2` endpoint (`6.1 ms` `B=1` GPU or `0.00 GB` GPU pure-ANE), injecting the mandatory `[Q] ` or `QuestionAnswering` prefix transparently.
3. **Stage C (Optional `ann` / `quant` Index Knobs in `prepared_index.py`):** Keep `hnsw` + `sq8` as the `~10M`-chunk sweet spot; expose optional `sq4` / `ivf` parameters for future `>30M`-chunk archives.
4. **Stage D (Sparse Visual Supplement Only):** Embed rendered pages/regions (`100 DPI`) only for pages classified as low-text charts/diagrams/figures during OCR ingestion.
