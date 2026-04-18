# Trigram index — architecture sketch

## Layout

```
+------------------+        +----------------------+        +------------------+
|  query string    | -----> |  trigram generator   | -----> |  postings merge  |
+------------------+        +----------------------+        +--------+---------+
                                                                     |
                                                                     v
                            +----------------------+        +------------------+
                            |  mmap postings file  | <----- |  candidate set   |
                            +----------------------+        +--------+---------+
                                                                     |
                                                                     v
                                                            +------------------+
                                                            |  scorer + writer |
                                                            +------------------+
```

## Index files

Per-corpus directory under `$XDG_CACHE_HOME/helio/index/<corpus-hash>/`:

- `trigrams.bin` — sorted 3-byte trigram keys.
- `postings.bin` — concatenated postings lists, one per trigram. Offsets + lengths live in `trigrams.bin`.
- `docs.bin` — document metadata (byte offset in the source log, length, optional file path).
- `MANIFEST` — build timestamp, corpus hash, index version, source file list.

All four are memory-mapped read-only. Writer holds an exclusive lock on a sibling `.lock` file during rebuild; readers open through a retry-on-stale-inode wrapper.

## Query flow

1. Strip surrounding whitespace, normalise to lowercase, bail out to substring scan if length < 3.
2. Generate overlapping trigrams. For `"nginx"` → `["ngi", "gin", "inx"]`.
3. Look up each trigram's postings list; intersect to get candidate documents.
4. Score candidates (edit distance, weighted by length) in rank order.
5. Stream hits to stdout as they cross the score threshold.

## Fallback rules

- Query length < 3: no trigrams exist. Fall back to substring scan over the corpus with the same streaming writer.
- Query contains only ASCII digits: skip fuzzy scoring, treat as exact substring (useful for IP and request-id lookups).
- `--engine=legacy`: bypass this module entirely and use v1.

## Cross-links

- OOM reproduced on step 3 of the implementation plan — see [[search-crash-large-logs]].
- Long-term plugin story (so external parsers can contribute trigrams from their own file formats) tracked in [[plugin-api-proposal]].
