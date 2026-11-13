import assert from "node:assert/strict";
import { test } from "node:test";
import { handleRequest } from "../src/gateway.ts";

const publication = "https://congressional-data.spicygov.ai/viewer-publications/releases/55c14dcda87ae954583bf518050b3bd45db6aed49c88c53413260c1d092ef105/manifest.json";
const env: Pick<Env, "PUBLICATION" | "MCP_RATE_LIMITER"> = {
  PUBLICATION: publication, MCP_RATE_LIMITER: { limit: async () => ({ success: true }) },
};
const endpoint = "https://congress.example/mcp";
const mustNotForward = async (): Promise<Response> => { throw new Error("Unexpected container request"); };

test("forwards the MCP payload and response while discarding caller credentials", async () => {
  const payload = JSON.stringify({ jsonrpc: "2.0", id: 7, method: "tools/call", params: {
    name: "query_sql", arguments: { query: { sql: "SELECT ? AS value", parameters: ["quoted ' value"] } },
  } });
  const response = await handleRequest(new Request(endpoint, {
    method: "POST", body: payload, headers: {
      "Content-Type": "application/json", Accept: "application/json, text/event-stream",
      "Mcp-Protocol-Version": "2025-06-18", Origin: "https://chatgpt.com",
      Authorization: "Bearer should-not-reach-container", Cookie: "private=value", "X-Forwarded-For": "forged",
    },
  }), env, async (request) => {
    assert.equal(request.url, endpoint);
    assert.equal(await request.text(), payload);
    assert.equal(request.headers.get("Mcp-Protocol-Version"), "2025-06-18");
    for (const header of ["Authorization", "Cookie", "X-Forwarded-For"]) assert.equal(request.headers.get(header), null);
    return Response.json({ jsonrpc: "2.0", id: 7, result: { content: [] } });
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), "https://chatgpt.com");
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { jsonrpc: "2.0", id: 7, result: { content: [] } });
});

test("rejects oversized requests without relying on Content-Length", async () => {
  const response = await handleRequest(new Request(endpoint, { method: "POST", body: "x".repeat(65537) }), env, mustNotForward);
  assert.equal(response.status, 413);
});

test("rate limiting uses the Cloudflare client IP and does not start a container", async () => {
  const response = await handleRequest(new Request(endpoint, { method: "POST", headers: { "CF-Connecting-IP": "192.0.2.3" } }), {
    ...env,
    MCP_RATE_LIMITER: { limit: async ({ key }) => { assert.equal(key, "192.0.2.3"); return { success: false }; } },
  }, mustNotForward);
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("Retry-After"), "60");
});

test("checks origins, paths, and methods before touching the container", async () => {
  for (const [request, expected] of [
    [new Request(endpoint, { method: "POST", headers: { Origin: "https://chatgpt.com.attacker.example" } }), 403],
    [new Request("https://congress.example/admin", { method: "POST" }), 404],
    [new Request(endpoint, { method: "PUT" }), 405],
    [new Request(endpoint, { method: "OPTIONS", headers: { Origin: "https://chatgpt.com" } }), 204],
  ] as const) {
    assert.equal((await handleRequest(request, env, mustNotForward)).status, expected);
  }
  const root = await handleRequest(new Request("https://congress.example/"), env, mustNotForward);
  assert.deepEqual(await root.json(), { name: "Congress Explorer", mcp: "/mcp", publication });
});

test("preserves MCP errors and streams responses", async () => {
  const response = await handleRequest(new Request(endpoint, { method: "POST", body: "{}" }), env,
    async () => new Response("data: {\"error\":\"invalid request\"}\n\n", {
      status: 400, headers: { "Content-Type": "text/event-stream" },
    }));
  assert.equal(response.status, 400);
  assert.equal(response.headers.get("Content-Type"), "text/event-stream");
  assert.equal(await response.text(), 'data: {"error":"invalid request"}\n\n');
});

test("readiness reaches the selected container and preserves a starting response", async () => {
  const response = await handleRequest(new Request("https://congress.example/ready"), env,
    async request => {
      assert.equal(new URL(request.url).pathname, "/ready");
      return Response.json({ status: "unavailable" }, { status: 503 });
    });
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.equal((await handleRequest(new Request("https://congress.example/ready", { method: "POST" }), env, mustNotForward)).status, 405);
});

test("a failed container produces a retryable error without exposing its exception", async () => {
  const response = await handleRequest(new Request(endpoint, { method: "POST", body: "{}" }), env,
    async () => { throw new Error("internal container details"); });
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("Retry-After"), "10");
  assert.doesNotMatch(await response.text(), /internal container details/);
});
