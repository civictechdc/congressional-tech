# Initial meeting-source state

These three frozen gzip JSON files bootstrap `pipeline-data/meeting-inventory/` once. The workflow copies a file only when that state file is missing. Subsequent parsed results and refresh dates are saved exclusively in the existing `pipeline-data` snapshot. This avoids making the first CI run fetch the whole research corpus.

Generated on 2026-09-27 from the read-only `~/hearing-text` research caches, the `a1705b6` meeting/GPO/YouTube inputs and the production parsers. No raw HTML, XML, PDFs, caption text or credentials are included. For imported records, `checked` is the import date used to start refresh scheduling; the cache does not retain individual HTTP receipts. House `urls` are recovered address candidates; subsequent live fetches keep the successful address.

| File | Bytes | Contents |
|---|---:|---|
| `house.json.gz` | 3,099,441 | 5,741 meetings: parsed documents, witnesses, amendments, XML update marker and absence state |
| `senate.json.gz` | 10,451,839 | 21 sites, 4,925 pages: listing routes/dates, parsed page lines needed to exclude shared menus, witnesses, documents and event matches |
| `inventory.json.gz` | 276,778 | 2,137 MODS witness lists, eight PDF witness lists, 3,268 archive probe answers and manual caption observations |

Total: **13,828,058 bytes**. The six reader tables reconstructed from this seed are byte-identical to the research tables at `a1705b6`. [The verification report](../../../docs/youtube-coverage/production-verification.md) explains the join's intentional differences and lists replay commands.

Rebuild these files only as a reviewed migration. Routine weekly runs must not rewrite the bootstrap. To rebuild from scratch, use the three production commands with an empty state directory, optionally passing `--seed-cache` to import retained research files without modifying them.
