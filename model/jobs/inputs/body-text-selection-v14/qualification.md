# Body-text selection v14

V14 carries forward the v13 baseline, its 416 source exclusions and 22,917 unchanged overrides. One PDF reading changes. [V13 qualification](../body-text-selection-v13/qualification.md)

## Page 151 of House Report 118–372, book 4

Physical page 151 reproduces the DHS Inspector General highlights sheet dated April 12, 2022, on printed page 5303. The previous text lost 25 words about testing families on arrival at or departure from hotels. It also interleaved the columns and garbled the title and the final lines of the findings. Two readers checked the full transcription against the original scan. The page preserves the printed heading, both columns in reading order, the contact information and the footer. [Reviewed transcription](page-151.txt)

| Evidence | SHA-256 |
| --- | --- |
| Source PDF, 575,953,191 bytes | `251ea1a6d6819b6f01e471cf4d22e924beea8e831c38ae1a4313c6bdd79b01cf` |
| V13 selected reading | `5d84e2bca02998e7b509ec12d2b5c17ef12d9da8a76c3e4b8e1f487b6f7c8f82` |
| V13 full text | `371f6d62f5fe62cefc1f530214801d9928106ba90b1c91e35c95735816d3528d` |
| Previous page 151 | `8b3f650f35bf8d877c9c3eea70704a614f333385261a11790fbb768742076dd3` |
| Reviewed transcript file | `bb609bb8eb1cf2ee21fe7e4ad567e26db3d9a4c338f3dc39a30ad58af74eeac6` |
| New page 151, without the file-ending newline | `7e086bd148edb62f3034585fe952d217ff422e1c4958e515ca42c3159249baa7` |
| V14 selected reading | `76fbfa836395f5db6a8a7334cf2f60d2aea789d78b2e4b427338ed500b909e76` |
| V14 full text | `6973f8979138aa4c9776850ca74d799d1cfbb5d1769a4615da9b8eeb67a1e28d` |

The existing PDF page composition code combined the retained Vision observation with the reviewed final text. The prior published text and its page offsets matched the retained base reading. All 1,207 other page texts matched v13 byte for byte. A separate comparison with the scan matched all 368 word and punctuation tokens in order. Removing or duplicating the testing passage failed the comparison.

The staged rows, composition receipt and independent control results are under the main checkout's `.cache/archive-release/fix-downloads-page151-20261121/`. The versioned reading retains the original OCR settings and the identities of the reviewed final text and its evidence. [Remaining accuracy limits](LIMITS.md)
