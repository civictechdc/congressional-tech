//! Probe: decode one receipt file with arrow-json, strict vs. type-conflict tolerant.
//!
//! Usage: `vc7_probe <file.jsonl.gz> <strict|tolerant>`. Prints rows, batches, null
//! `record` count and the first error, if any.
// Rust guideline compliant 2026-02-21
use std::{env, fs::File, io::BufReader, sync::Arc};

use arrow_array::Array;
use arrow_json::ReaderBuilder;
use arrow_schema::{DataType, Field, Fields, Schema};

use flate2::read::MultiGzDecoder;

/// Rows per batch; DataFusion's default `batch_size`, so memory matches its reader.
const BATCH_ROWS: usize = 8192;

fn main() {
    let args: Vec<String> = env::args().collect();
    let tolerant = args[2] == "tolerant";
    // The older receipt shape: `record` is an object for most lines.
    let record = Fields::from(vec![
        Field::new("url", DataType::Utf8, true),
        Field::new("http_status", DataType::Int64, true),
        Field::new("status", DataType::Int64, true),
        Field::new("sha256", DataType::Utf8, true),
    ]);
    let schema = Arc::new(Schema::new(vec![
        Field::new("source_file", DataType::Utf8, true),
        Field::new("source_line", DataType::Int64, true),
        Field::new("record", DataType::Struct(record), true),
    ]));
    let file = BufReader::new(MultiGzDecoder::new(File::open(&args[1]).expect("open")));
    let reader = ReaderBuilder::new(schema)
        .with_batch_size(BATCH_ROWS)
        .with_ignore_type_conflicts(tolerant)
        .with_coerce_primitive(tolerant)
        .build(BufReader::new(file))
        .expect("build");
    let (mut rows, mut batches, mut null_records) = (0usize, 0usize, 0usize);
    for batch in reader {
        match batch {
            Ok(b) => {
                rows += b.num_rows();
                batches += 1;
                null_records += b.column(2).null_count();
            }
            Err(e) => {
                println!("ERROR after {rows} rows: {e}");
                break;
            }
        }
    }
    println!("mode={} rows={rows} batches={batches} null_record={null_records}", args[2]);
}
