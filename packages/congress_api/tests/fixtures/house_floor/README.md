# Retained House floor feed entries

`retained-entries.xml` contains the original feed header and exact entry XML
at positions 0, 1 and 2225 of the retained House feed. It is a deliberately
selected fixture, not a claim of complete source coverage.

- Publisher: `https://docs.house.gov/BillsThisWeek-RSS.xml` (Atom despite its filename).
- Complete original SHA-256: `c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e`.
- Complete original size: 38,854,265 bytes.
- Fixture SHA-256: `918f49e1ebf1d0a932041ad804041e249330ec0e574c22f0fcfc427a4d6a941b`.

The January 2020 pair shares one weekly URL but has distinct entry identities
and content. The September 2026 entry exercises a longer set of document links.
Entry byte hashes are asserted in `tests/test_house_floor_feed.py`. No publisher
request was made to prepare this fixture; it reuses the CT retained raw archive.

Original-source screenshots and the extraction receipt are retained under the
CT main checkout's `.cache/archive-release/ocr-recovery-20261113/repairs/house-floor-feed-20261113/`.
