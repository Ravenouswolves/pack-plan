# Pack Plan tests

`./tests/run.sh` starts `python -m http.server` on port 8765 and runs:

1. `test_app.py` — Wilson's original 39 UI, math, and persistence checks, pointed at this staging copy.
2. `test_prep.py` — first-run, `rwBudget.v1` persistence, the footer disclaimer, no console errors, the 390px wrap fixes, the service worker, and a check that the only outside calls are Google Fonts.

These tests do not deploy or publish anything.
