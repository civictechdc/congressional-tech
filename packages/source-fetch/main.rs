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

/// Thread-safe rate limiter managing minimum spacing between outbound requests.
#[derive(Debug)]
struct RateLimit {
    next: Mutex<Instant>,
    gap: Duration,
}

impl RateLimit {
    /// Create a new rate limiter with the given maximum operations per second.
    fn new(per_second: u32) -> Self {
        Self {
            next: Mutex::new(Instant::now()),
            gap: Duration::from_secs_f64(1.0 / f64::from(per_second)),
        }
    }

    /// Wait until the scheduled release time and update the next available slot.
    async fn wait(&self) {
        let mut next = self.next.lock().await;
        sleep_until(*next).await;
        // Schedule from now to avoid a catch-up burst after a stalled runtime.
        *next = Instant::now() + self.gap;
    }

    /// Conditionally wait for rate limit pacing if `new_file` starts a new request sequence.
    async fn wait_for_start(&self, new_file: bool) {
        if new_file {
            self.wait().await;
        }
    }
}

/// Outbound HTTP transport selection.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "lowercase")]
enum Transport {
    Direct,
    Zyte,
}

/// Inbound JSON request descriptor sent over stdin.
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

/// Serialized HTTP header key-value pair for metadata fidelity.
#[derive(Debug, Serialize)]
struct Header {
    name: String,
    value: String,
}

/// Map a reqwest error into a stable error kind category string.
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

/// Stream and decode the HTTP response body into a body file, collecting metadata.
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

const LEGACY_PYTHON_UA: &str =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36";

const BROWSER_USER_AGENT: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

const DIRECT_BROWSER_HEADERS: [(&str, &str); 8] = [
    ("User-Agent", BROWSER_USER_AGENT),
    (
        "Accept",
        "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
    ),
    ("Accept-Language", "en-US,en;q=0.9"),
    ("Upgrade-Insecure-Requests", "1"),
    ("Sec-Fetch-Dest", "document"),
    ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-Site", "none"),
    ("Sec-Fetch-User", "?1"),
];

const DIRECT_JSON_API_HEADERS: [(&str, &str); 2] = [
    ("User-Agent", BROWSER_USER_AGENT),
    ("Accept", "application/json"),
];

fn is_json_api_url(url: &str) -> bool {
    reqwest::Url::parse(url)
        .ok()
        .and_then(|parsed| {
            parsed.host_str().map(|host| {
                host.eq_ignore_ascii_case("api.congress.gov")
                    || host.eq_ignore_ascii_case("api.govinfo.gov")
            })
        })
        .unwrap_or(false)
}

fn apply_request_headers(
    mut builder: reqwest::RequestBuilder,
    request: &Request,
) -> Result<reqwest::RequestBuilder> {
    let mut headers = header::HeaderMap::new();
    headers.insert(
        header::ACCEPT_ENCODING,
        header::HeaderValue::from_static("gzip, deflate, br"),
    );
    if matches!(request.transport, Transport::Direct) {
        let defaults: &[(&str, &str)] = if is_json_api_url(&request.url) {
            &DIRECT_JSON_API_HEADERS
        } else {
            &DIRECT_BROWSER_HEADERS
        };
        for &(name, value) in defaults {
            headers.insert(
                header::HeaderName::from_bytes(name.as_bytes())?,
                header::HeaderValue::from_static(value),
            );
        }
    }
    let has_custom_ua = request
        .headers
        .iter()
        .any(|(k, v)| k.eq_ignore_ascii_case("user-agent") && v != LEGACY_PYTHON_UA);
    for (name, value) in &request.headers {
        if matches!(request.transport, Transport::Zyte)
            && (name.eq_ignore_ascii_case("authorization")
                || name.eq_ignore_ascii_case("content-type"))
        {
            continue;
        }
        if matches!(request.transport, Transport::Direct)
            && name.eq_ignore_ascii_case("user-agent")
            && value == LEGACY_PYTHON_UA
        {
            if !has_custom_ua {
                headers.insert(
                    header::USER_AGENT,
                    header::HeaderValue::from_static(BROWSER_USER_AGENT),
                );
            }
            continue;
        }
        headers.insert(
            header::HeaderName::from_bytes(name.as_bytes())
                .context("Invalid request header name")?,
            header::HeaderValue::from_str(value).context("Invalid request header value")?,
        );
    }
    for (name, value) in &headers {
        builder = builder.header(name, value);
    }
    Ok(builder)
}

/// Execute a single HTTP request using the specified transport, pacing, and limits.
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
    let builder = match request.transport {
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
    let builder = apply_request_headers(builder, request)?
        .timeout(Duration::from_millis(request.timeout_ms));
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

    #[tokio::test]
    async fn direct_requests_send_browser_profile_headers_and_preserve_caller_overrides() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let mut captured = Vec::new();
            for _ in 0..2 {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut reader = BufReader::new(&mut socket);
                let mut req_headers: BTreeMap<String, Vec<String>> = BTreeMap::new();
                let mut line = String::new();
                reader.read_line(&mut line).await.unwrap();
                loop {
                    line.clear();
                    reader.read_line(&mut line).await.unwrap();
                    let trimmed = line.trim_end_matches(&['\r', '\n'][..]);
                    if trimmed.is_empty() {
                        break;
                    }
                    if let Some((k, v)) = trimmed.split_once(':') {
                        req_headers
                            .entry(k.trim().to_ascii_lowercase())
                            .or_default()
                            .push(v.trim().to_string());
                    }
                }
                captured.push(req_headers);
                socket
                    .write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n\r\nok")
                    .await
                    .unwrap();
            }
            captured
        });

        let dir = std::env::temp_dir().join(format!("sf-hdr-test-{}", std::process::id()));
        let _ = tokio::fs::remove_dir_all(&dir).await;
        tokio::fs::create_dir_all(&dir).await.unwrap();
        let client = Client::builder()
            .no_gzip()
            .no_brotli()
            .no_deflate()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .unwrap();
        let limit = RateLimit::new(100);

        let legacy_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36";
        let req1: Request = serde_json::from_value(json!({
            "id": 1,
            "url": format!("http://{addr}/first"),
            "transport": "direct",
            "max_bytes": 1024,
            "headers": {"User-Agent": legacy_ua}
        }))
        .unwrap();
        let res1 = fetch(&client, &limit, &req1, &dir, None).await.unwrap();
        assert_eq!(res1["http_status"], 200);

        let req2: Request = serde_json::from_value(json!({
            "id": 2,
            "url": format!("http://{addr}/second"),
            "transport": "direct",
            "max_bytes": 1024,
            "headers": {
                "User-Agent": legacy_ua,
                "user-agent": "custom-probe/1.0",
                "accept": "application/pdf"
            }
        }))
        .unwrap();
        let res2 = fetch(&client, &limit, &req2, &dir, None).await.unwrap();
        assert_eq!(res2["http_status"], 200);

        let _ = tokio::fs::remove_dir_all(&dir).await;
        let captured = server.await.unwrap();

        for hdrs in &captured {
            for (k, vals) in hdrs {
                assert_eq!(vals.len(), 1, "duplicate wire header {k}: {vals:?}");
            }
        }

        assert!(captured[0]["user-agent"][0].contains("Mac OS X 10_15_7"));
        assert!(captured[0]["user-agent"][0].contains("(KHTML, like Gecko)"));
        assert!(captured[0]["accept"][0].contains("application/pdf;q=0.9"));
        assert_eq!(captured[0]["accept-language"][0], "en-US,en;q=0.9");
        assert_eq!(captured[0]["upgrade-insecure-requests"][0], "1");
        assert_eq!(captured[0]["sec-fetch-dest"][0], "document");
        assert_eq!(captured[0]["sec-fetch-mode"][0], "navigate");
        assert_eq!(captured[0]["sec-fetch-site"][0], "none");
        assert_eq!(captured[0]["sec-fetch-user"][0], "?1");
        assert_eq!(captured[0]["accept-encoding"][0], "gzip, deflate, br");

        assert_eq!(captured[1]["user-agent"], vec!["custom-probe/1.0"]);
        assert_eq!(captured[1]["accept"], vec!["application/pdf"]);
        assert_eq!(captured[1]["accept-language"], vec!["en-US,en;q=0.9"]);
    }

    #[test]
    fn zyte_and_json_api_requests_omit_document_navigation_headers() {
        let client = Client::new();
        let zyte_req: Request = serde_json::from_value(json!({
            "id": 10,
            "url": "https://www.energy.senate.gov/public/",
            "transport": "zyte",
            "max_bytes": 1024
        }))
        .unwrap();
        let built_zyte = apply_request_headers(
            client
                .post("https://api.zyte.com/v1/extract")
                .json(&json!({"url": zyte_req.url})),
            &zyte_req,
        )
        .unwrap()
        .build()
        .unwrap();
        assert_eq!(
            built_zyte.headers().get("content-type").unwrap(),
            "application/json"
        );
        assert!(built_zyte.headers().get("sec-fetch-mode").is_none());
        assert!(built_zyte.headers().get("upgrade-insecure-requests").is_none());
        assert!(built_zyte.headers().get("accept-language").is_none());
        assert_eq!(
            built_zyte.headers().get("accept-encoding").unwrap(),
            "gzip, deflate, br"
        );

        let api_direct: Request = serde_json::from_value(json!({
            "id": 11,
            "url": "https://api.govinfo.gov/collections/CHRG/2026-01-01T00:00:00Z?pageSize=1000",
            "transport": "direct",
            "max_bytes": 1024,
            "headers": {"X-Api-Key": "test-key"}
        }))
        .unwrap();
        let built_api = apply_request_headers(client.get(&api_direct.url), &api_direct)
            .unwrap()
            .build()
            .unwrap();
        assert_eq!(
            built_api.headers().get("accept").unwrap(),
            "application/json"
        );
        assert!(built_api.headers().get("sec-fetch-dest").is_none());
        assert!(built_api.headers().get("upgrade-insecure-requests").is_none());

        let empty_direct: Request = serde_json::from_value(json!({
            "id": 12,
            "url": "https://www.energy.senate.gov/public/",
            "transport": "direct",
            "max_bytes": 1024
        }))
        .unwrap();
        let built_direct =
            apply_request_headers(client.get(&empty_direct.url), &empty_direct)
                .unwrap()
                .build()
                .unwrap();
        assert_eq!(
            built_direct.headers().get("user-agent").unwrap(),
            BROWSER_USER_AGENT
        );
        assert_eq!(
            built_direct.headers().get("sec-fetch-dest").unwrap(),
            "document"
        );
    }
}
