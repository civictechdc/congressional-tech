# Congress Explorer 0.6.7

This release improves hearing, witness and legislative research in Congress Explorer.

- Older witness identifiers resolve to current records when the selected archive
  provides a mapping. Hearing bundles keep previously listed witnesses with
  their status and distinguish appearances by sitting members of Congress from
  outside witnesses. Person search uses the published names and aliases.
- Hearing bundles report whether captions are archived or only advertised,
  deduplicate recordings and use current witness identifiers in prepared
  testimony and transcript results.
- Legislative queries handle partitioned nomination records and use the correct
  publisher URLs for historical Congresses. Document-kind filters continue to
  use the synonyms supplied by the selected archive.
- The hosted server warms its pinned archive before reporting readiness, so
  initial research requests can use the same prepared data as later requests.

The desktop release uses the archive you have selected. Run
`congress-explorer-mcp prepare` and restart your client to use the current
published data. The hosted service selects its archive through its deployment.
