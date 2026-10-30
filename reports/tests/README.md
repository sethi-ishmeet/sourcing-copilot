# Test report

97 tests, 0 failures, 0 errors, 0 skipped, 3.56s.

Run with `make test` (everything except the browser test, which runs in CI after the UI build and locally with `make test-browser`).

| Folder | Tests | What |
|---|---|---|
| tests/api | 31 | auth, reads and data presentation, screenings and decisions |
| tests/copilot | 35 | rules, pretend LinkedIn, fake model, end-to-end flows and failures |
| tests/data | 28 | loading, data checks, computed profile facts |
| tests/evals | 2 | the eval harness itself |
| tests/store | 1 | one store read and written by eight threads at once |

Plus 1 browser test in tests/browser (screenshots in reports/browser).

Raw results: junit.xml in this folder.
