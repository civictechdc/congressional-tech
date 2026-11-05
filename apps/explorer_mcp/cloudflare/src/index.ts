import { Container, getContainer } from "@cloudflare/containers";
import { handleRequest } from "./gateway.ts";

export class CongressExplorer extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "5m";
  envVars = { CONGRESS_MCP_PUBLICATION: this.env.PUBLICATION };

  override async fetch(request: Request): Promise<Response> {
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

export default {
  async fetch(request, env): Promise<Response> {
    return handleRequest(request, env, async (boundedRequest) => {
      // A release change must not reach a still-running replica of the old data.
      const slot = crypto.getRandomValues(new Uint8Array(1))[0] % 2;
      const container = getContainer(env.CONGRESS, `${env.PUBLICATION}:${slot}`);
      return container.fetch(boundedRequest);
    });
  },
} satisfies ExportedHandler<Env>;
