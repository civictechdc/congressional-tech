const RELEASE_ID = /^[0-9a-f]{64}$/;
const HOLD_MS = 60_000;

/**
 * Follow the archive's moving pointer to the immutable manifest it selects now.
 *
 * Containers never see the pointer: each is named after, and started with, one immutable
 * release manifest, so replicas of a release agree and a new release starts new containers.
 * Isolates re-read the pointer at most once a minute, so they can disagree for that long after
 * a flip. When the pointer cannot be read, the last release this isolate resolved keeps serving.
 */
export function followPointer(
  pointer: string,
  fetcher: (url: string) => Promise<Response> = (url) => fetch(url),
  clock: () => number = Date.now,
): () => Promise<string> {
  let held: { publication: string; at: number } | undefined;
  return async () => {
    const now = clock();
    if (held && now - held.at < HOLD_MS) return held.publication;
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
