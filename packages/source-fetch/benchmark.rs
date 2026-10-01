//! Benchmark complete direct and Zyte downloads of the six retained source examples.
//!
//! Usage: `reqwest-fetch-bench OUTPUT_DIRECTORY [both|direct|zyte] [REPEATS]`
//! Supply `ZYTE_TOKEN` or `ZYTE_ENV_FILE` for Zyte. Output directories must be new.
//! Timings exclude body-file writes, R2 publication, and catalog construction.
// Rust guideline compliant 2026-02-21

use std::{
    env, fs,
    path::Path,
    time::{Duration, Instant},
};

use anyhow::{Context, Result, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use futures_util::{StreamExt, stream};
use reqwest::{Client, Response};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

#[global_allocator]
static ALLOCATOR: mimalloc::MiMalloc = mimalloc::MiMalloc;

// Match the CI worker count and decoded response limit.
const WORKERS: usize = 8;
const MAX_BYTES: usize = 64 * 1024 * 1024;
const USER_AGENT: &str =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36";

#[derive(Debug, Deserialize)]
struct Case {
    id: String,
    url: String,
}

fn zyte_token() -> Result<String> {
    if let Ok(token) = env::var("ZYTE_TOKEN") {
        ensure!(!token.is_empty(), "ZYTE_TOKEN is empty");
        return Ok(token);
    }
    let path = env::var("ZYTE_ENV_FILE").context("Set ZYTE_TOKEN or ZYTE_ENV_FILE")?;
    for entry in dotenvy::from_path_iter(path)? {
        let (key, value) =
            entry.map_err(|_| anyhow::anyhow!("Could not parse the environment file"))?;
        if key == "ZYTE_TOKEN" && !value.is_empty() {
            return Ok(value);
        }
    }
    anyhow::bail!("ZYTE_TOKEN was not found in the environment file")
}

async fn read_body(response: &mut Response, limit: usize) -> Result<Vec<u8>> {
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await? {
        ensure!(
            chunk.len() <= limit.saturating_sub(body.len()),
            "Response exceeds byte limit"
        );
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

async fn fetch(client: &Client, case: &Case, mode: &str, token: &str) -> Result<(Value, Vec<u8>)> {
    let request = if mode == "zyte" {
        client
            .post("https://api.zyte.com/v1/extract")
            .basic_auth(token, Some(""))
            .json(&json!({"url": case.url, "httpResponseBody": true, "httpResponseHeaders": true}))
    } else {
        client.get(&case.url).header("User-Agent", USER_AGENT)
    };
    let mut response = request.send().await?;
    let http_status = response.status().as_u16();
    let protocol = format!("{:?}", response.version());
    let mut metadata = json!({
        "http_status": http_status,
        "final_url": response.url().as_str(),
        "content_type": response.headers().get("content-type").and_then(|v| v.to_str().ok()),
        "complete": http_status != 206 && !response.headers().contains_key("content-range"),
        "protocol": protocol,
    });
    // Zyte wraps source bytes in base64 JSON, requiring additional space.
    let limit = if mode == "zyte" {
        MAX_BYTES * 4 / 3 + 1024 * 1024
    } else {
        MAX_BYTES
    };
    let mut body = read_body(&mut response, limit).await?;
    if mode == "zyte" {
        metadata["provider_http_status"] = json!(http_status);
        metadata["http_status"] = Value::Null;
        if http_status == 200 {
            let payload: Value = serde_json::from_slice(&body)?;
            body = STANDARD.decode(
                payload["httpResponseBody"]
                    .as_str()
                    .context("Missing source body")?,
            )?;
            ensure!(body.len() <= MAX_BYTES, "Source exceeds byte limit");
            let status = payload["statusCode"]
                .as_u64()
                .context("Missing source status")?;
            metadata["http_status"] = json!(status);
            metadata["final_url"] = payload["url"].clone();
            let headers = payload["httpResponseHeaders"]
                .as_array()
                .context("Missing source headers")?;
            metadata["content_type"] = headers
                .iter()
                .find(|h| {
                    h["name"]
                        .as_str()
                        .is_some_and(|n| n.eq_ignore_ascii_case("content-type"))
                })
                .map_or(Value::Null, |h| h["value"].clone());
            metadata["complete"] = json!(
                status != 206
                    && !headers.iter().any(|h| h["name"]
                        .as_str()
                        .is_some_and(|n| n.eq_ignore_ascii_case("content-range")))
            );
        } else {
            metadata["error"] = json!("provider_http_error");
            metadata["complete"] = json!(false);
        }
    }
    metadata["body_bytes"] = json!(body.len());
    metadata["sha256"] = json!(format!("{:x}", Sha256::digest(&body)));
    Ok((metadata, body))
}

async fn batch(
    client: &Client,
    cases: &[Case],
    mode: &str,
    token: &str,
    repeat: usize,
    output: &Path,
) -> Result<(Vec<Value>, Value)> {
    let started = Instant::now();
    let mut pending = stream::iter(cases)
        .map(|case| async move {
            let started = Instant::now();
            let result = fetch(client, case, mode, token).await;
            (case, started.elapsed().as_secs_f64(), result)
        })
        .buffer_unordered(WORKERS);
    let mut completed = Vec::new();
    while let Some(item) = pending.next().await {
        completed.push(item);
    }
    let seconds = started.elapsed().as_secs_f64();
    let mut rows = Vec::new();
    for (case, elapsed, result) in completed {
        let (mut row, body) = match result {
            Ok(result) => result,
            Err(error) => (
                json!({"error": error.to_string(), "complete": false}),
                Vec::new(),
            ),
        };
        let name = format!("{mode}-{repeat}-{}.bin", case.id);
        if !body.is_empty() {
            fs::write(output.join(&name), body)?;
            row["body_file"] = json!(name);
        }
        row["case_id"] = json!(case.id);
        row["url"] = json!(case.url);
        row["transport"] = json!(mode);
        row["repeat"] = json!(repeat);
        row["fetch_seconds"] = json!(elapsed);
        println!("{row}");
        rows.push(row);
    }
    Ok((
        rows,
        json!({"transport": mode, "repeat": repeat, "seconds": seconds}),
    ))
}

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    ensure!(
        (2..=4).contains(&args.len()),
        "Usage: reqwest-fetch-bench OUTPUT_DIRECTORY [both|direct|zyte] [REPEATS]"
    );
    let output = Path::new(&args[1]);
    let mode = args.get(2).map_or("both", String::as_str);
    ensure!(
        ["both", "direct", "zyte"].contains(&mode),
        "Unknown transport"
    );
    let repeats = args.get(3).map_or(Ok(3), |s| s.parse::<usize>())?;
    ensure!((1..=10).contains(&repeats), "Use 1 through 10 repetitions");
    let cases: Vec<Case> = serde_json::from_str(include_str!("cases.json"))?;
    let token = if mode == "direct" {
        String::new()
    } else {
        zyte_token()?
    };
    // Keep the CI timeout bounds; add a total deadline for this short benchmark.
    let client = Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .read_timeout(Duration::from_secs(90))
        .timeout(Duration::from_secs(120))
        .redirect(reqwest::redirect::Policy::limited(5))
        .retry(reqwest::retry::never())
        .build()?;
    fs::create_dir(output).context("Output directory must be new and its parent must exist")?;
    let (mut observations, mut batches) = (Vec::new(), Vec::new());
    for repeat in 1..=repeats {
        let order = if repeat % 2 == 1 {
            ["direct", "zyte"]
        } else {
            ["zyte", "direct"]
        };
        for transport in order.into_iter().filter(|t| mode == "both" || *t == mode) {
            let (rows, timing) = batch(&client, &cases, transport, &token, repeat, output).await?;
            let auth_failed = rows
                .iter()
                .any(|r| matches!(r["provider_http_status"].as_u64(), Some(401 | 403)));
            observations.extend(rows);
            batches.push(timing);
            fs::write(
                output.join("results.json"),
                serde_json::to_vec_pretty(&json!({
                    "workers": WORKERS, "response_limit_bytes": MAX_BYTES,
                    "client_reuse": "one pooled client across all repeats", "host_pacing": false,
                    "observations": observations, "batches": batches,
                }))?,
            )?;
            ensure!(
                !auth_failed,
                "Zyte authorization failed; results were retained"
            );
        }
    }
    ensure!(
        !observations
            .iter()
            .any(|r| r.get("error").is_some() || r["complete"] != true),
        "Some requests failed; inspect results.json"
    );
    Ok(())
}
