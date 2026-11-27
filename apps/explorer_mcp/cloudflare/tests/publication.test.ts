import assert from "node:assert/strict";
import { test } from "node:test";
import {
  followPointer,
  forwardWithReleaseSync,
  releaseIdFromPublication,
  selectContainerSlot,
  SPICYENGINE_MISMATCH,
  startingResponse,
  startupOptionsForPath,
} from "../src/publication.ts";

const pointer = "https://archive.example/viewer-publications/manifest.json";
const first = "a".repeat(64), second = "b".repeat(64);
const manifest = (release: string) => `https://archive.example/viewer-publications/releases/${release}/manifest.json`;

function source(...answers: Array<Response | Error>) {
  const read: string[] = [];
  let now = 0;
  const resolve = followPointer(pointer, async (url) => {
    read.push(url);
    const answer = answers.shift();
    if (!answer) throw new Error("Unexpected pointer read");
    if (answer instanceof Error) throw answer;
    return answer;
  }, () => now);
  return { resolve, read, wait: (ms: number) => { now += ms; } };
}

test("the pointer's release becomes its immutable manifest, re-read at most once a minute", async () => {
  const { resolve, read, wait } = source(Response.json({ release_id: first }), Response.json({ release_id: second }));
  assert.equal(await resolve(), manifest(first));
  wait(59_999);
  assert.equal(await resolve(), manifest(first));
  assert.deepEqual(read, [pointer]);
  wait(1);
  assert.equal(await resolve(), manifest(second));
  assert.deepEqual(read, [pointer, pointer]);
});

test("an unreadable or malformed pointer keeps the last release and retries a minute later", async () => {
  const { resolve, read, wait } = source(Response.json({ release_id: first }), new Error("network"),
    new Response("gone", { status: 503 }), Response.json({ release_id: "../" + "c".repeat(61) }), Response.json({ release_id: second }));
  assert.equal(await resolve(), manifest(first));
  for (const _ of [1, 2, 3]) {
    wait(60_000);
    assert.equal(await resolve(), manifest(first));
    assert.equal(await resolve(), manifest(first));
  }
  assert.equal(read.length, 4);
  wait(60_000);
  assert.equal(await resolve(), manifest(second));
});

test("with no release resolved yet, a failed pointer read refuses instead of guessing", async () => {
  const { resolve } = source(Response.json({ release_id: "latest" }), Response.json({ release_id: first }));
  await assert.rejects(resolve(), /names no release/);
  assert.equal(await resolve(), manifest(first));
});

test("refreshing bypasses the 60s cache when a release-mismatch triggers re-sync", async () => {
  const { resolve, read, wait } = source(
    Response.json({ release_id: first }),
    Response.json({ release_id: second }),
  );
  assert.equal(await resolve(), manifest(first));
  wait(10_000);
  assert.equal(await resolve(), manifest(first));
  assert.equal(read.length, 1);

  const req = new Request("https://congress.example/mcp", {
    method: "POST",
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "search_docs" } }),
  });
  const attempts: string[] = [];
  const res = await forwardWithReleaseSync(req, resolve, async (attempt, selected) => {
    attempts.push(selected);
    const body = await attempt.text();
    assert.match(body, /search_docs/);
    if (selected === manifest(first)) {
      return Response.json({ jsonrpc: "2.0", id: 1, result: { isError: true, content: [{ type: "text", text: SPICYENGINE_MISMATCH }] } });
    }
    return Response.json({ jsonrpc: "2.0", id: 1, result: { content: [{ type: "text", text: "ok" }] } });
  });
  assert.deepEqual(attempts, [manifest(first), manifest(second)]);
  assert.equal(read.length, 2);
  const payload = await res.json() as { result: { content: Array<{ text: string }> } };
  assert.equal(payload.result.content[0].text, "ok");
});

test("does not loop when pointer refresh still matches the cached release", async () => {
  const { resolve, read } = source(
    Response.json({ release_id: first }),
    Response.json({ release_id: first }),
  );
  const req = new Request("https://congress.example/mcp", { method: "POST", body: "{}" });
  let calls = 0;
  const res = await forwardWithReleaseSync(req, resolve, async () => {
    calls += 1;
    return Response.json({ error: SPICYENGINE_MISMATCH });
  });
  assert.equal(calls, 1);
  assert.equal(read.length, 2);
  assert.deepEqual(await res.json(), { error: SPICYENGINE_MISMATCH });
});

test("readiness probes pin to container slot 0 while /mcp distributes across two slots", () => {
  assert.equal(selectContainerSlot("/ready", () => 1), 0);
  assert.equal(selectContainerSlot("/ready", () => 3), 0);
  assert.equal(selectContainerSlot("/mcp", () => 0), 0);
  assert.equal(selectContainerSlot("/mcp", () => 1), 1);
  assert.equal(selectContainerSlot("/mcp", () => 5), 1);
});

test("readiness startup waits are bounded to 8s while /mcp keeps the 90s cold-start budget", () => {
  const controller = new AbortController();
  const ready = startupOptionsForPath("/ready", controller.signal);
  const mcp = startupOptionsForPath("/mcp", controller.signal);
  assert.equal(ready.instanceGetTimeoutMS, 8_000);
  assert.equal(ready.portReadyTimeoutMS, 8_000);
  assert.equal(ready.abort, controller.signal);
  assert.equal(mcp.instanceGetTimeoutMS, 90_000);
  assert.equal(mcp.portReadyTimeoutMS, 90_000);
  assert.equal(mcp.abort, controller.signal);
});

test("startingResponse returns a retryable 503 with release_id when warming a known release", async () => {
  assert.equal(releaseIdFromPublication(manifest(first)), first);
  assert.equal(releaseIdFromPublication(pointer), null);

  const warm = startingResponse(manifest(first));
  assert.equal(warm.status, 503);
  assert.equal(warm.headers.get("Retry-After"), "5");
  assert.equal(warm.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await warm.json(), { status: "starting", release_id: first });

  const unknown = startingResponse(pointer);
  assert.equal(unknown.status, 503);
  assert.deepEqual(await unknown.json(), { status: "starting" });
});
