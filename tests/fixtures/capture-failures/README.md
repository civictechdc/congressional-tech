These exact retained publisher responses reproduce the October 5, 2026 capture
failure audit. `sources.json` records the original URL and uncompressed digest.

The two `.rtfd.gz` responses are regular-file serializations despite their PDF
URL and media type. Their child bytes were independently read using Apple's
`Foundation.FileWrapper(serializedRepresentation:)`. The production parser
supports only the observed v3 regular-file layout. It validates explicit lengths
and names; it does not search for PDF headers. Unknown layouts remain unsupported.

`file-wrappers/generate.swift` creates the five small native differential fixtures;
`native-results.jsonl` records their original names and native roundtrip result.
The `.expected` files contain exact payloads returned by Foundation. No paths in
serialized data are used as output paths in production.
