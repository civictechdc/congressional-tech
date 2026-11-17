import assert from "node:assert/strict";
import { test } from "node:test";
import { followPointer } from "../src/publication.ts";

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
