# Reproduction — five steps

Assumes a machine with at least 4 GB free RAM. Run under a tightened ulimit to turn the OOM into a deterministic signal.

## 1. Generate a synthetic 1 GB nginx access log

```bash
pipx install fakelog
fakelog nginx --size 1GiB --status-distribution 'real' > /tmp/access.log
ls -lh /tmp/access.log   # expect ~1.0G
```

## 2. Check out the trigram-index branch

```bash
git clone https://github.com/alice-voland/helio.git /tmp/helio
git -C /tmp/helio checkout search/fuzzy-v2
cd /tmp/helio
make install-dev
```

## 3. Build the index

```bash
helio index build --corpus /tmp/access.log --out /tmp/helio-index
```

Should finish in 15–20 s. `/tmp/helio-index/` ends up around 680 MB.

## 4. Tighten virtual memory so the OOM fires deterministically

```bash
ulimit -v 2000000      # 2 GB virtual memory cap for this shell
```

## 5. Trigger the crash

```bash
helio search "5[0-9][0-9] /api/" --index /tmp/helio-index
```

Expected behaviour: 2–4 hits scroll past, then the process aborts. Without the ulimit, the kernel OOM killer takes ~1.5 s longer on a 32 GB machine because of swap dynamics, but the crash is the same.

## Reverting

```bash
unset ulimit override   # or close the shell
rm -rf /tmp/access.log /tmp/helio-index /tmp/helio
```
