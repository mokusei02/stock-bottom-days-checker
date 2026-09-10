# Daily market snapshots

The Streamlit process reads validated snapshots from the public `market-data`
branch of this same repository. No credentials, cookies, or search histories are
included in that branch. It does not call Yahoo Finance for web searches.

`.github/workflows/market-data.yml` runs on weekdays at 07:05 UTC (16:05 JST),
or on manual dispatch. GitHub scheduling is best-effort and can run late.
The first scheduled job reads all symbols in `companies.csv`; unavailable symbols
keep their previous data. Full histories from 2000 are downloaded so corporate
action adjustments do not leave incompatible old/new price scales.

The Nikkei bundle is replaced only when every constituent was retrieved in the
same run. A rate-limit error aborts the job without publishing partial changes.
The data branch is pushed only after validation finishes. Git retains previous
snapshots; no force pushes or cache deletion are used.

The app pins all reads to one immutable commit. It caches the manifest for five
minutes, and cached rankings are keyed by that commit and the requested period.
It shows the saved price's last trading date and fetch timestamp, and explicitly
labels older data. Company metadata not saved in the snapshot is shown as
unavailable, not guessed. A newly listed/unavailable symbol without a saved
history reports that fact instead of showing another stock's data.

Validation: `python -m unittest discover -s tests -v`.

Initial bootstrap (before enabling the workflow):
`python scripts/update_market_data.py --output ../market-data --only-nikkei`.
Publish only the resulting `prices/`, `manifest.json`, and `nikkei225.zip` to the
data branch, then run a full update to cover the remaining search symbols.
