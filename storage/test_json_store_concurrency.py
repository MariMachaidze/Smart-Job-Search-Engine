"""
Live concurrency test for storage/json_store.py.

Run directly:
    python3 storage/test_json_store_concurrency.py
    (or: python3 -m storage.test_json_store_concurrency, from the repo root)

What it does, in order:

1. Reproduces the original bug that existed in `upsert`/`save_all` before
   this fix, using a standalone reimplementation of the OLD unlocked logic
   (the real module no longer contains this code path -- it's inlined here
   purely to demonstrate the failure mode existed). Many real OS threads,
   released together via a `threading.Barrier` so they genuinely overlap
   rather than running sequentially, all `upsert` distinct records into the
   same shared JSON file. A small injected delay widens the race window so
   the bug reproduces reliably with a small, fast thread count -- without
   it, a handful of threads on a fast local disk might not always collide
   within one test run, even though the bug is real (race conditions are
   probabilistic). Expected result: most records go missing, and/or
   `FileNotFoundError` is raised by `os.replace`.

2. Runs the exact same concurrent-writer scenario against the real, FIXED
   `storage.json_store.upsert` -- no injected delay, just real threads
   hammering the same entity file -- repeated across many trials (one clean
   run proves nothing for a probabilistic bug). Asserts every single record
   survives, with no duplicates and no exceptions, on every single trial.

Exits 0 if the fix holds across all trials, 1 otherwise.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import json_store  # noqa: E402


# ---------------------------------------------------------------------------
# Part 1: standalone reimplementation of the ORIGINAL unlocked upsert/write,
# to reproduce the two bugs the real fix addresses:
#   BUG 1 (tmp-file collision): all writers share one hardcoded `<path>.tmp`.
#   BUG 2 (lost update): load -> modify -> save with no lock around the cycle.
# ---------------------------------------------------------------------------

def _buggy_read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _buggy_write_json_atomic(path, data, inject_delay=0.0):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = path + ".tmp"  # BUG 1: shared hardcoded tmp path, no uuid
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if inject_delay:
        # Widens the window so multiple writers' os.replace calls on the
        # SAME tmp_path race against each other.
        time.sleep(inject_delay)
    os.replace(tmp_path, path)


def _buggy_upsert(path, record, key_field, inject_delay=0.0):
    records = _buggy_read_json(path, [])  # BUG 2: unlocked read...
    if inject_delay:
        # ...window where other threads also read the same starting state
        # and will each compute their own "updated" list from it.
        time.sleep(inject_delay)
    key_value = record.get(key_field)
    for i, existing in enumerate(records):
        if existing.get(key_field) == key_value:
            records[i] = record
            break
    else:
        records.append(record)
    _buggy_write_json_atomic(path, records, inject_delay=inject_delay)  # last save silently wins


# ---------------------------------------------------------------------------
# Shared harness: real concurrent threads, released together via a Barrier.
# ---------------------------------------------------------------------------

def run_concurrent(fn, n_writers):
    """Runs `fn(i)` for i in range(n_writers) from real OS threads, all
    released at (as close to) the same instant via a Barrier, so they
    genuinely overlap rather than running sequentially one after another."""
    barrier = threading.Barrier(n_writers)
    errors = []

    def worker(i):
        barrier.wait()
        try:
            fn(i)
        except Exception as e:
            errors.append((i, repr(e)))

    with ThreadPoolExecutor(max_workers=n_writers) as pool:
        futures = [pool.submit(worker, i) for i in range(n_writers)]
        for f in futures:
            f.result()
    return errors


def reproduce_bug(tmp_dir, n_writers=12, trials=5):
    print(f"\n=== Step 1: reproducing the ORIGINAL bug "
          f"({trials} trials x {n_writers} concurrent writers, unlocked code) ===")
    any_failure = False
    for trial in range(trials):
        path = os.path.join(tmp_dir, f"buggy_trial_{trial}.json")

        def write_one(i, path=path):
            _buggy_upsert(path, {"id": f"rec-{i}", "value": i}, "id", inject_delay=0.01)

        errors = run_concurrent(write_one, n_writers)
        try:
            records = _buggy_read_json(path, [])
            ids_present = {r["id"] for r in records}
            expected_ids = {f"rec-{i}" for i in range(n_writers)}
            missing = expected_ids - ids_present
            corrupted = False
        except Exception as e:
            # Interleaved concurrent writes to the shared tmp path can
            # corrupt the JSON itself (e.g. two writers' content concatenated)
            # -- this is itself the bug, not a test-harness error.
            missing = set()
            corrupted = True
            print(f"  trial {trial}: bug REPRODUCED -- final file is CORRUPTED, "
                  f"unreadable as JSON: {e!r}")
            any_failure = True
            continue

        if errors or missing:
            any_failure = True
            print(f"  trial {trial}: bug REPRODUCED -- {len(errors)} exception(s) "
                  f"(e.g. {errors[0][1] if errors else 'n/a'}), "
                  f"{len(missing)}/{n_writers} records missing")
        else:
            print(f"  trial {trial}: no failure this trial (race is probabilistic)")

    if not any_failure:
        print("  NOTE: bug did not reproduce in any trial here -- races are "
              "probabilistic, this doesn't mean the old code was safe.")
    return any_failure


def verify_fix(data_dir, n_writers=20, trials=30):
    print(f"\n=== Step 2: verifying the FIX "
          f"({trials} trials x {n_writers} concurrent writers, real storage.json_store.upsert) ===")
    os.environ["DATA_DIR"] = data_dir
    user_id = "concurrency-test-user"
    entity = "documents"

    all_passed = True
    for trial in range(trials):
        json_store.save_all(user_id, entity, [])  # clean slate each trial

        def write_one(i):
            json_store.upsert(user_id, entity, {"id": f"rec-{i}", "value": i, "trial": trial}, "id")

        errors = run_concurrent(write_one, n_writers)
        records = json_store.load_all(user_id, entity)
        ids_present = {r["id"] for r in records}
        expected_ids = {f"rec-{i}" for i in range(n_writers)}
        missing = expected_ids - ids_present
        duplicated = len(records) != len(ids_present)

        if errors or missing or duplicated:
            all_passed = False
            print(f"  trial {trial}: FAILED -- {len(errors)} exception(s), "
                  f"missing: {sorted(missing)}, duplicated: {duplicated}")
            for i, e in errors:
                print(f"    writer {i} raised: {e}")
        else:
            print(f"  trial {trial}: OK -- all {n_writers}/{n_writers} records present, "
                  f"no duplicates, no errors")

    return all_passed


if __name__ == "__main__":
    scratch = tempfile.mkdtemp(prefix="json_store_concurrency_")
    try:
        bug_dir = os.path.join(scratch, "bug_repro")
        os.makedirs(bug_dir, exist_ok=True)
        bug_reproduced = reproduce_bug(bug_dir)

        fix_dir = os.path.join(scratch, "fix_verify")
        os.makedirs(fix_dir, exist_ok=True)
        fix_ok = verify_fix(fix_dir)

        print("\n=== Summary ===")
        print(f"Original (unlocked) bug reproduced in this run: {bug_reproduced}")
        print(f"Fix held across ALL trials with real concurrent threads: {fix_ok}")

        if fix_ok:
            print("\nPASS: storage.json_store.upsert is safe under real concurrent writers.")
            sys.exit(0)
        else:
            print("\nFAIL: storage.json_store.upsert LOST DATA under concurrent writers.")
            sys.exit(1)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
