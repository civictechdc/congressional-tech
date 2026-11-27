import { Container, getContainer } from "@cloudflare/containers";
import { handleRequest } from "./gateway.ts";
import {
  followPointer,
  forwardWithReleaseSync,
  selectContainerSlot,
  startingResponse,
  startupOptionsForPath,
  type PointerResolver,
} from "./publication.ts";

// Set by this Worker on every forwarded request; a caller's own copy is overwritten.
const PUBLICATION_HEADER = "X-Congress-Publication";

export class CongressExplorer extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "15m";

  override async fetch(request: Request): Promise<Response> {
    const publication = request.headers.get(PUBLICATION_HEADER);
    if (!publication) return new Response("Missing archive release", { status: 500 });
    const pathname = new URL(request.url).pathname;
    // This instance is named after one immutable release; every start selects that release.
    this.envVars = {
      CONGRESS_MCP_PUBLICATION: publication,
      CONGRESS_MCP_SEARCH_ORIGIN: this.env.SPICYENGINE_ORIGIN,
    };
    // A fresh filesystem must download and verify the pinned metadata before
    // accepting MCP calls. Readiness probes use a bounded wait and return a
    // fast retryable 503 while the container finishes warming in the background.
    try {
      await this.startAndWaitForPorts({
        cancellationOptions: startupOptionsForPath(pathname, request.signal),
      });
    } catch (error) {
      if (pathname === "/ready" && !request.signal.aborted) {
        return startingResponse(publication);
      }
      throw error;
    }
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
        const pathname = new URL(attempt.url).pathname;
        const slot = selectContainerSlot(pathname, () => crypto.getRandomValues(new Uint8Array(1))[0]);
        const container = getContainer(env.CONGRESS, `${selected}:${slot}`);
        const pinned = new Request(attempt);
        pinned.headers.set(PUBLICATION_HEADER, selected);
        return container.fetch(pinned);
      });
    });
  },
} satisfies ExportedHandler<Env>;
