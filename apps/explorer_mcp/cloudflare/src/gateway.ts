const MAX_REQUEST_BYTES = 64 * 1024;
const BROWSER_ORIGINS = new Set(["https://chatgpt.com", "https://platform.openai.com"]);

export async function handleRequest(
  request: Request,
  env: Pick<Env, "MCP_RATE_LIMITER" | "PUBLICATION">,
  forward: (request: Request) => Promise<Response>,
): Promise<Response> {
  const url = new URL(request.url);
  const origin = request.headers.get("Origin");
  if (origin && origin !== url.origin && !BROWSER_ORIGINS.has(origin)) {
    return new Response("Origin is not allowed", { status: 403 });
  }
  const headers = new Headers({ "Cache-Control": "no-store" });
  if (origin) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Vary", "Origin");
    headers.set("Access-Control-Expose-Headers", "Mcp-Session-Id, Mcp-Protocol-Version, Retry-After");
  }
  const reply = (message: string, status: number) => new Response(message, { status, headers });
  if (url.pathname === "/" && request.method === "GET") {
    return Response.json({ name: "Congress Explorer", mcp: "/mcp", publication: env.PUBLICATION }, { headers });
  }
  if (url.pathname !== "/mcp") return reply("Not found", 404);
  if (request.method === "OPTIONS") {
    headers.set("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Content-Type, Accept, Mcp-Protocol-Version, Mcp-Session-Id");
    return new Response(null, { status: 204, headers });
  }
  if (!["POST", "GET", "DELETE"].includes(request.method)) {
    headers.set("Allow", "POST, GET, DELETE, OPTIONS");
    return reply("Method not allowed", 405);
  }
  const { success } = await env.MCP_RATE_LIMITER.limit({
    key: request.headers.get("CF-Connecting-IP") ?? "unknown",
  });
  if (!success) {
    headers.set("Retry-After", "60");
    return reply("Request limit reached; retry later", 429);
  }
  // Enforce the bound while reading, including chunked requests with no length.
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (request.body) {
    const reader = request.body.getReader();
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_REQUEST_BYTES) {
          await reader.cancel();
          return reply("MCP request exceeds 64 KiB", 413);
        }
        chunks.push(value);
      }
    } finally {
      reader.releaseLock();
    }
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const upstreamHeaders = new Headers(request.headers);
  upstreamHeaders.delete("Content-Length");
  // Never forward caller-provided proxy credentials or forwarding identities.
  upstreamHeaders.delete("Authorization");
  upstreamHeaders.delete("Cookie");
  upstreamHeaders.delete("X-Forwarded-For");
  try {
    const response = await forward(new Request(request.url, {
      method: request.method,
      headers: upstreamHeaders,
      body: size ? body : undefined,
      redirect: "manual",
      signal: request.signal,
    }));
    const responseHeaders = new Headers(response.headers);
    headers.forEach((value, key) => responseHeaders.set(key, value));
    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch (error) {
    console.error(JSON.stringify({ event: "congress_mcp_upstream_failed", message: String(error) }));
    headers.set("Retry-After", "10");
    return reply("Congress Explorer is starting or temporarily unavailable; retry shortly", 503);
  }
}
