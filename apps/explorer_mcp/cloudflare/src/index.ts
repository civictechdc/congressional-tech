import { Container, getContainer } from "@cloudflare/containers";
import { handleRequest } from "./gateway.ts";
import { followPointer, forwardWithReleaseSync, type PointerResolver } from "./publication.ts";

// Set by this Worker on every forwarded request; a caller's own copy is overwritten.
const PUBLICATION_HEADER = "X-Congress-Publication";

export class CongressExplorer extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "5m";

  override async fetch(request: Request): Promise<Response> {
    const publication = request.headers.get(PUBLICATION_HEADER);
    if (!publication) return new Response("Missing archive release", { status: 500 });
    // This instance is named after one immutable release; every start selects that release.
    this.envVars = {
      CONGRESS_MCP_PUBLICATION: publication,
      CONGRESS_MCP_SEARCH_ORIGIN: this.env.SPICYENGINE_ORIGIN,
    };
    // A fresh filesystem must download and verify the pinned metadata before
    // accepting MCP calls. The SDK's default 20 seconds is too short for this.
    await this.startAndWaitForPorts({
      cancellationOptions: {
        instanceGetTimeoutMS: 90_000,
        portReadyTimeoutMS: 90_000,
        abort: request.signal,
      },
    });
    return super.fetch(request);
  }
}

let publication: PointerResolver | undefined;

export default {
  async fetch(request, env): Promise<Response> {
    publication ??= followPointer(env.ARCHIVE_POINTER);
    return handleRequest(request, { MCP_RATE_LIMITER: env.MCP_RATE_LIMITER, publication }, async (boundedRequest) => {
      return forwardWithReleaseSync(boundedRequest, publication!, async (attempt, selected) => {
        // A release change must not reach a still-running replica of the old data.
        const slot = crypto.getRandomValues(new Uint8Array(1))[0] % 2;
        const container = getContainer(env.CONGRESS, `${selected}:${slot}`);
        const pinned = new Request(attempt);
        pinned.headers.set(PUBLICATION_HEADER, selected);
        return container.fetch(pinned);
      });
    });
  },
} satisfies ExportedHandler<Env>;
