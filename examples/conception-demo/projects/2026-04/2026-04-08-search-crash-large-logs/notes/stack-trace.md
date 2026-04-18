# Debug-build stack trace at OOM

Captured with `RUST_BACKTRACE=full` and a debug build. The Python wrapper (`helio` is a thin CLI over a PyO3 extension; the heavy lifting is in Rust, but the entry point is Python) prints its own frames before the panic propagates.

```
Traceback (most recent call last):
  File "/usr/local/bin/helio", line 8, in <module>
    sys.exit(main())
             ^^^^^^
  File "/opt/helio/lib/python3.12/site-packages/helio/__main__.py", line 41, in main
    return run_cli(sys.argv[1:])
           ^^^^^^^^^^^^^^^^^^^^^
  File "/opt/helio/lib/python3.12/site-packages/helio/cli.py", line 212, in run_cli
    return cmd.dispatch(args)
           ^^^^^^^^^^^^^^^^^^
  File "/opt/helio/lib/python3.12/site-packages/helio/commands/search.py", line 88, in run
    for hit in engine.stream(query, corpus):
  File "/opt/helio/lib/python3.12/site-packages/helio/search/__init__.py", line 33, in stream
    yield from _ext.stream_trigram(query, corpus_path, opts.to_dict())
helio._ext.EngineOOM: engine process aborted (SIGKILL)

stack backtrace (Rust side, captured before abort):
   0: helio_search::scorer::candidate_vec::push
             at src/scorer/candidate_vec.rs:62
   1: helio_search::scorer::rank::collect_ranges
             at src/scorer/rank.rs:148
   2: helio_search::query::run_trigram_query
             at src/query/mod.rs:97
   3: helio_search::stream::StreamingWriter::pump
             at src/stream.rs:203
   4: helio_search::stream::stream_trigram
             at src/stream.rs:54
   5: <helio_search::py::stream_trigram as ...>::__call__
             at src/py.rs:112
   6: pyo3::impl_::trampoline::trampoline
   7: <unknown>
   8: _PyEval_EvalFrameDefault
   9: _PyFunction_Vectorcall
  10: Py_BytesMain
```

Relevant kernel message from `/var/log/kern.log`:

```
[ 4812.441276] Out of memory: Killed process 18324 (helio) total-vm:29834124kB, anon-rss:16782400kB, file-rss:8192kB, shmem-rss:0kB, UID:1000 pgtables:33136kB oom_score_adj:0
```

The `anon-rss:16782400kB` line is load-bearing — that is the candidate-range vec plus two in-flight reallocations, not the mmap. mmap pages count under `file-rss` and stay small (~8 MB at the moment of kill).
