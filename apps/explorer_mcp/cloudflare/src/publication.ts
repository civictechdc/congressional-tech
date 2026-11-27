const RELEASE_ID = /^[0-9a-f]{64}$/;
const HOLD_MS = 60_000;
const READY_STARTUP_TIMEOUT_MS = 8_000;
const MCP_STARTUP_TIMEOUT_MS = 90_000;
export const SPICYENGINE_MISMATCH = "SpicyEngine is not serving the archive release selected by Congress Explorer.";

export type PointerResolver = (options?: { refresh?: boolean }) => Promise<string>;

export function selectContainerSlot(pathname: string, randomByte: () => number): number {
  // Always route readiness probes to slot 0 so cold-start probes warm one primary
  // replica instead of waking a second cold container on 50% of attempts.
  if (pathname === "/ready") return 0;
  return randomByte() % 2;
}

export function startupOptionsForPath(pathname: string, abort: AbortSignal) {
  const timeoutMS = pathname === "/ready" ? READY_STARTUP_TIMEOUT_MS : MCP_STARTUP_TIMEOUT_MS;
  return {
    instanceGetTimeoutMS: timeoutMS,
    portReadyTimeoutMS: timeoutMS,
    abort,
  };
}

export function releaseIdFromPublication(publication: string): string | null {
  const match = publication.match(/\/releases\/([0-9a-f]{64})\/manifest\.json$/);
  return match ? match[1] : null;
}

export function startingResponse(publication: string): Response {
  const releaseId = releaseIdFromPublication(publication);
  return Response.json(
    releaseId ? { status: "starting", release_id: releaseId } : { status: "starting" },
    {
      status: 503,
      headers: {
        "Cache-Control": "no-store",
        "Retry-After": "5",
      },
    },
  );
}

/**
 * Follow the archive's moving pointer to the immutable manifest it selects now.
 *
 * Containers never see the pointer: each is named after, and started with, one immutable
 * release manifest, so replicas of a release agree and a new release starts new containers.
 * Isolates re-read the pointer at most once a minute, so they can disagree for that long after
 * a flip unless a release-mismatch response triggers an immediate refresh. When the pointer
 * cannot be read, the last release this isolate resolved keeps serving.
 */
export function followPointer(
  pointer: string,
  fetcher: (url: string) => Promise<Response> = (url) => fetch(url),
  clock: () => number = Date.now,
): PointerResolver {
  let held: { publication: string; at: number } | undefined;
  return async (options?: { refresh?: boolean }) => {
    const now = clock();
    if (!options?.refresh && held && now - held.at < HOLD_MS) return held.publication;
    try {
      const response = await fetcher(pointer);
      if (!response.ok) throw new Error(`Archive pointer answered ${response.status}`);
      const release = ((await response.json()) as { release_id?: unknown }).release_id;
      if (typeof release !== "string" || !RELEASE_ID.test(release)) {
        throw new Error("Archive pointer names no release");
      }
      held = { publication: new URL(`releases/${release}/manifest.json`, pointer).href, at: now };
    } catch (error) {
      if (!held) throw error;
      console.error(JSON.stringify({ event: "congress_mcp_pointer_unread", message: String(error) }));
      held.at = now;
    }
    return held.publication;
  };
}

/**
 * Forward an MCP request to the container for the cached release, refreshing the
 * 60-second pointer cache once if SpicyEngine already moved to a newer release.
 */
export async function forwardWithReleaseSync(
  request: Request,
  resolvePublication: PointerResolver,
  forwardToContainer: (request: Request, selected: string) => Promise<Response>,
): Promise<Response> {
  const selected = await resolvePublication();
  const canRetryPost = request.method === "POST" && new URL(request.url).pathname === "/mcp";
  const firstAttempt = canRetryPost ? request.clone() : request;
  const response = await forwardToContainer(firstAttempt, selected);
  if (!canRetryPost || response.status !== 200) return response;
  const bodyText = await response.clone().text();
  if (!bodyText.includes(SPICYENGINE_MISMATCH)) return response;
  const refreshed = await resolvePublication({ refresh: true });
  if (refreshed === selected) return response;
  await response.body?.cancel();
  return forwardToContainer(request, refreshed);
}
