# Historical reading refusals, November 5, 2026

The current readings bundle `7b006df1` reproduces all 25 active refusals
from `a7a8c404`. The local proof compared exact body keys and reasons in
both directions. It reproduced nine memory-limit and 16 output-limit
refusals, with zero missing, extra or unread keys.

The proof ran at `52167b94e2507f917d2c102fd2c9c54ff1a712f9` with one
worker, pinned Poppler 26.06.0 and the local DocSpec runtime. It verified
37,906,067 stored bytes and 557,834,395 decoded bytes in 29.8 seconds.
Peak process-tree memory was 0.783 GiB RSS and 0.658 GiB physical.

The bounded native control preserved all 30 selected reading rows, accepted
the original 25 decision IDs, and cleared 25 pending keys. Model coverage
checks cleared 24 missing sniff readings and one missing page reading.
The control opened zero raw bodies.

The live provenance inventory and original decision bytes matched the
selected e145 release under the nightly writer lock. All 25 active original
decisions and the native table heads matched the frozen inputs. The model
keeps the original decision file with SHA-256
`b9205fc6c2c46dffb7544e383b0f12a4a4c0e4427f35c1cc397f3642f97e4cbb`.
The staged decision file supports the compatibility proof.
