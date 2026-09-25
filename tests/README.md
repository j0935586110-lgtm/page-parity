RN-20260925173746-ef6c
# page-parity V1 Independent Test Suite

This directory contains an independent test suite for the page-parity V1 specification.
The suite is designed to be run against any implementation that complies with the spec,
without referencing the reference implementation (`impl-dsh`).

## Test Structure

- `tests/test_*.py`: Python unittest module that executes the CLI via subprocess.
- `tests/fixtures/`: Three mini‑site samples used by the tests.
  - `F1`: Clean site – three pages fully consistent.
  - `F2`: Known‑defects site – missing menu, variable drift, and an orphan page (listed as reasonable exception).
  - `F3`: Boundary site – comments with fake declarations, same values with different formatting (`0.3s` vs `.3s`, `0.05` vs `.05`), and nested `@media` declarations. Also includes an overflow test page for L2.

## Requirements

- Python 3.6+ (for unittest subprocess execution).
- The page-parity implementation must be made available via the `PP_IMPL` environment
  variable or, if unset, defaults to `../impl-dsh` relative to this directory.
- The implementation must provide a CLI entry point (either `bin/page-parity` executable
  or `python -m page_parity`).

## How to Run

From the `tests-oc` directory:

```bash
# Use the default implementation (../impl-dsh)
python -m unittest discover -v

# Or specify a different implementation root:
export PP_IMPL=/path/to/your/impl
python -m unittest discover -v
```

## Expected Outcomes

- **Contract tests**
  - `--help` output ≤ 300 characters.
  - `--schema` emits valid JSON.
  - `--self-test` exits with code 0 (the internal negative control is correctly detected as FAIL).
  - Default `--format=json` yields a single‑line JSON document on stdout containing the keys `verdict`, `exit_reason`, `codes`, `counts`, `details_url`.
  - Invalid option → exit code 3.
  - No input (`page-parity check`) → exit code 2 (INDETERMINATE).

- **Functional tests**
  - **F1 (clean site)** → exit code 0 (OK) or 2 (INDETERMINATE if browser unavailable for L2; L1 alone should succeed).
  - **F2 (known defects)** → exit code 1 (FINDINGS) due to missing menu and variable‑drift failures.
    - The orphan page in `pageC.html` is listed in `page-parity.toml` with a reason; it should appear in the report but not increase the failure count.
  - **F3 (boundary)** → no false‑positive drift for `--transition` or `--ratio` despite formatting differences.
  - **L2 overflow** → when a browser is available, the overflow test page should trigger `ELEMENT_OVERFLOW` with a selector matching the overflowing element (`.hero-tags`).

## Determining Pass/Fail

A test passes if the assertion in the corresponding test method does not raise.
The test runner will report a summary of passed/failed tests.

The suite treats the implementation as a black box; it only checks:
- Exit codes.
- Ability to parse JSON output.
- Presence of expected error codes in the `codes[]` array.
- Basic sanity of CLI contract.

## Notes

- The test suite deliberately avoids installing any extra packages; it uses only the Python standard library (`unittest`, `subprocess`, `json`, `pathlib`).
- All fixture files are self‑contained and do not require network access.
- L2 tests require a browser (Playwright) to be usable by the implementation. If the implementation cannot launch a browser, it should return exit code 2 (INDETERMINATE) for L2‑dependent checks, which is accepted by the tests.