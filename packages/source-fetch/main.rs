//! Perform bounded HTTP requests for the Python capture and recovery pipeline.
//!
//! Read JSON requests from stdin and emit metadata plus local body paths on stdout.
//! File starts share one rate limit; redirects and fallback continue the same file.
//! Python owns URL validation, fallback decisions, source interpretation, and storage.
// Rust guideline compliant 2026-02-21

use std::{collections::BTreeMap, env, path::PathBuf, pin::Pin, sync::Arc, time::Duration};

use anyhow::{Context, Result, ensure};
use async_compression::tokio::bufread::{BrotliDecoder, GzipDecoder, ZlibDecoder};
use futures_util::TryStreamExt;
use reqwest::{Client, Response, StatusCode, header};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, AsyncWriteExt, BufReader},
    sync::{Mutex, Semaphore},
    task::JoinSet,
    time::{Instant, sleep_until},
};
use tokio_util::io::StreamReader;

#[global_allocator]
static ALLOCATOR: mimalloc::MiMalloc = mimalloc::MiMalloc;

#[derive(Debug)]
struct RateLimit {
    next: Mutex<Instant>,
    gap: Duration,
}

impl RateLimit {
    fn new(per_second: u32) -> Self {
        Self {
            next: Mutex::new(Instant::now()),
            gap: Duration::from_secs_f64(1.0 / f64::from(per_second)),
        }
    }

    async fn wait(&self) {
        let mut next = self.next.lock().await;
        sleep_until(*next).await;
        // Schedule from now to avoid a catch-up burst after a stalled runtime.
        *next = Instant::now() + self.gap;
    }

    async fn wait_for_start(&self, new_file: bool) {
        if new_file {
            self.wait().await;
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "lowercase")]
enum Transport {
    Direct,
    Zyte,
}

#[derive(Debug, Deserialize)]
struct Request {
    id: u64,
    url: String,
    transport: Transport,
    max_bytes: usize,
    // Older callers omit this field: count their requests conservatively.
    #[serde(default = "default_new_file")]
    new_file: bool,
    #[serde(default = "default_timeout_ms")]
    timeout_ms: u64,
    #[serde(default)]
    headers: BTreeMap<String, String>,
}

fn default_new_file() -> bool {
    true
}

fn default_timeout_ms() -> u64 {
    300_000
}

#[derive(Debug, Serialize)]
struct Header {
    name: String,
    value: String,
}

fn error_kind(error: &reqwest::Error) -> &'static str {
    if error.is_timeout() {
        "timeout"
    } else if error.is_connect() {
        "connect_error"
    } else if error.is_body() || error.is_decode() {
        "body_error"
    } else {
        "request_error"
    }
}

fn body_error_kind(error: &std::io::Error) -> &'static str {
    // StreamReader and the content decoders wrap reqwest's error. Preserve its
    // timeout classification without serializing a message containing the URL.
    let mut cause = error
        .get_ref()
        .map(|e| e as &(dyn std::error::Error + 'static));
    while let Some(error) = cause {
        if let Some(error) = error.downcast_ref::<reqwest::Error>() {
            return error_kind(error);
        }
        cause = error.source();
    }
    if error.kind() == std::io::ErrorKind::TimedOut {
        "timeout"
    } else {
        "body_error"
    }
}

fn oversized_identity_response(response: &Response, request: &Request) -> Option<u64> {
    // Encoded lengths do not describe the decoded body. Let the streaming cap
    // handle those responses, unknown lengths, ranges, and provider payloads.
    let headers = response.headers();
    if !matches!(request.transport, Transport::Direct)
        || response.status() != StatusCode::OK
        || headers.contains_key(header::TRANSFER_ENCODING)
        || headers.contains_key(header::CONTENT_RANGE)
        || !headers.contains_key(header::CONTENT_LENGTH)
        || !headers
            .get_all(header::CONTENT_ENCODING)
            .iter()
            .all(|value| {
                value
                    .to_str()
                    .is_ok_and(|value| value.trim().eq_ignore_ascii_case("identity"))
            })
    {
        return None;
    }
    // reqwest exposes the HTTP body's validated exact length, not an unchecked
    // integer from one of several possibly conflicting header fields.
    response
        .content_length()
        .filter(|&length| length > request.max_bytes as u64)
}

async fn save_response(
    response: Response,
    request: &Request,
    output: &std::path::Path,
) -> Result<Value> {
    let headers: Vec<Header> = response
        .headers()
        .iter()
        .map(|(name, value)| Header {
            name: name.to_string(),
            value: String::from_utf8_lossy(value.as_bytes()).into_owned(),
        })
        .collect();
    let mut metadata = json!({
        "http_status": response.status().as_u16(), "final_url": response.url().as_str(),
        "response_header_items": headers, "response_header_fidelity": "repeated_fields",
        "response_reason": response.status().canonical_reason().unwrap_or(""),
        "http_version": format!("{:?}", response.version()), "response_metadata_version": 2,
    });
    // Decode after copying headers: reqwest's automatic decoders remove the
    // original Content-Encoding and Content-Length fields before callers see them.
    let encoding = response
        .headers()
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("identity")
        .trim()
        .to_ascii_lowercase();
    let path = output.join(format!("{}.body", request.id));
    let mut file = tokio::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .await?;
    if let Some(length) = oversized_identity_response(&response, request) {
        // Return an empty, incomplete body with the original headers. Dropping
        // the response releases the download slot without draining the payload.
        metadata["body_file"] = json!(path);
        metadata["bytes"] = json!(0);
        metadata["complete"] = json!(false);
        metadata["error"] = json!("response_limit");
        metadata["body_read_skipped"] = json!("declared_size_limit");
        metadata["declared_body_bytes"] = json!(length);
        return Ok(metadata);
    }
    let input = StreamReader::new(response.bytes_stream().map_err(std::io::Error::other));
    let mut reader: Pin<Box<dyn AsyncRead + Send>> = match encoding.as_str() {
        "gzip" | "x-gzip" => Box::pin(GzipDecoder::new(input)),
        "br" => Box::pin(BrotliDecoder::new(input)),
        "deflate" => Box::pin(ZlibDecoder::new(input)),
        _ => Box::pin(input),
    };
    let mut bytes = 0;
    let mut complete = matches!(
        encoding.as_str(),
        "identity" | "" | "gzip" | "x-gzip" | "br" | "deflate"
    );
    let mut error = if complete {
        None
    } else {
        Some("unsupported_content_encoding")
    };
    // Limit each decoded read as well as the total retained body.
    let mut chunk = vec![0; 65_536];
    loop {
        match reader.read(&mut chunk).await {
            Ok(0) => break,
            Ok(count) => {
                let take = count.min(request.max_bytes.saturating_sub(bytes));
                file.write_all(&chunk[..take]).await?;
                bytes += take;
                if take < count {
                    complete = false;
                    error = Some("response_limit");
                    break;
                }
            }
            Err(cause) => {
                complete = false;
                error = Some(body_error_kind(&cause));
                break;
            }
        }
    }
    file.flush().await?;
    metadata["body_file"] = json!(path);
    metadata["bytes"] = json!(bytes);
    metadata["complete"] = json!(complete);
    metadata["error"] = json!(error);
    Ok(metadata)
}

async fn fetch(
    client: &Client,
    limit: &RateLimit,
    request: &Request,
    output: &std::path::Path,
    token: Option<&str>,
) -> Result<Value> {
    ensure!(request.max_bytes > 0, "Response limit must be positive");
    ensure!(
        (1..=900_000).contains(&request.timeout_ms),
        "Invalid request deadline"
    );
    let mut builder = match request.transport {
        Transport::Direct => client.get(&request.url),
        Transport::Zyte => client
            .post("https://api.zyte.com/v1/extract")
            .basic_auth(
                token.context("ZYTE_TOKEN is required for fallback")?,
                Some(""),
            )
            .json(
                &json!({"url": request.url, "httpResponseBody": true, "httpResponseHeaders": true}),
            ),
    };
    builder = builder
        .header("Accept-Encoding", "gzip, deflate, br")
        .timeout(Duration::from_millis(request.timeout_ms));
    for (name, value) in &request.headers {
        builder = builder.header(name, value);
    }
    limit.wait_for_start(request.new_file).await;
    match builder.send().await {
        Ok(response) => save_response(response, request, output).await,
        Err(error) => Ok(json!({"complete": false, "error": error_kind(&error)})),
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    ensure!(
        args.len() == 4,
        "Usage: source-fetch BODY_DIRECTORY FILES_PER_SECOND CONCURRENCY"
    );
    let output = Arc::new(PathBuf::from(&args[1]));
    ensure!(output.is_dir(), "Body directory must already exist");
    let rate: u32 = args[2].parse()?;
    let concurrency: usize = args[3].parse()?;
    ensure!(
        rate > 0 && concurrency > 0,
        "Rate and concurrency must be positive"
    );
    let token = env::var("ZYTE_TOKEN")
        .ok()
        .filter(|v| !v.is_empty())
        .map(Arc::new);
    // Redirects return to Python for scope checking and continue the same file.
    let client = Client::builder()
        .no_gzip()
        .no_brotli()
        .no_deflate()
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .connect_timeout(Duration::from_secs(15))
        .read_timeout(Duration::from_secs(90))
        .timeout(Duration::from_millis(default_timeout_ms()))
        .build()?;
    let limit = Arc::new(RateLimit::new(rate));
    let permits = Arc::new(Semaphore::new(concurrency));
    let stdout = Arc::new(Mutex::new(tokio::io::stdout()));
    let mut tasks = JoinSet::new();
    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    while let Some(line) = lines.next_line().await? {
        let request: Request = serde_json::from_str(&line).context("Invalid request JSON")?;
        let permit = Arc::clone(&permits).acquire_owned().await?;
        let (client, limit, output, stdout, token) = (
            client.clone(),
            Arc::clone(&limit),
            Arc::clone(&output),
            Arc::clone(&stdout),
            token.clone(),
        );
        tasks.spawn(async move {
            let _permit = permit;
            let result = fetch(&client, &limit, &request, &output, token.as_deref().map(String::as_str)).await;
            // Internal errors are fatal to the parent; network failures are capture results.
            let value = match result {
                Ok(response) => json!({"id": request.id, "response": response}),
                Err(_) => json!({"id": request.id, "fatal": "native transport could not complete request"}),
            };
            let mut line = serde_json::to_vec(&value)?;
            line.push(b'\n');
            let mut stdout = stdout.lock().await;
            stdout.write_all(&line).await?;
            stdout.flush().await?;
            Ok::<_, anyhow::Error>(())
        });
        while let Some(result) = tasks.try_join_next() {
            result??;
        }
    }
    while let Some(result) = tasks.join_next().await {
        result??;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn omitted_file_start_flag_keeps_older_requests_rate_limited() {
        let request: Request = serde_json::from_value(json!({
            "id": 1, "url": "https://example.gov/a.pdf", "transport": "direct", "max_bytes": 1024
        }))
        .unwrap();
        assert!(request.new_file);
    }

    #[tokio::test(start_paused = true)]
    async fn continuations_do_not_spend_a_file_start_slot() {
        let rate = RateLimit::new(60);
        rate.wait_for_start(true).await;
        let first = Instant::now();
        for _ in 0..6 {
            rate.wait_for_start(false).await;
        }
        assert_eq!(Instant::now(), first);
        rate.wait_for_start(true).await;
        let elapsed = Instant::now() - first;
        assert!(elapsed >= Duration::from_secs_f64(1.0 / 60.0));
        assert!(elapsed <= Duration::from_millis(18));
    }

    #[tokio::test(start_paused = true)]
    async fn rate_limit_spaces_starts_and_never_catches_up() {
        let rate = RateLimit::new(40);
        let first = Instant::now();
        rate.wait().await;
        rate.wait().await;
        assert_eq!(Instant::now() - first, Duration::from_millis(25));
        tokio::time::advance(Duration::from_secs(2)).await;
        rate.wait().await;
        let resumed = Instant::now();
        rate.wait().await;
        assert_eq!(Instant::now() - resumed, Duration::from_millis(25));
    }
}
