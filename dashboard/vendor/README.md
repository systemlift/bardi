# Vendored third-party libraries

These are unmodified copies of the two JavaScript libraries `dashboard/index.html` depends on.
They are committed to the repo rather than loaded from a CDN so the dashboard keeps working if
cdnjs is down, or if the client's network blocks third-party CDNs.

| File | Library | Version | Upstream | SHA-256 |
|---|---|---|---|---|
| `chart.umd.min.js` | Chart.js | 4.4.1 | `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js` | `81ffafe13c37e1b25793b020d446f4d9739b949dadb7f9f79d709a0cad781c2f` |
| `xlsx.full.min.js` | SheetJS (xlsx) | 0.18.5 | `https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js` | `c9506197caf809a075b6dee1da0d36fb19da7158ffe8a88e7b0c96c5d8623c99` |

Downloaded 2026-08-12.

## Verifying

```sh
sha256sum dashboard/vendor/chart.umd.min.js dashboard/vendor/xlsx.full.min.js
```

## Upgrading

1. Download the new version from the upstream URL above.
2. Update the version comment in `dashboard/index.html` (the `<script>` block near the top).
3. Update the version and SHA-256 in the table above.
4. Load the dashboard and confirm the four charts render and **Memberships → Download Excel** still produces a file.
