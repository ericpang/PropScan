# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

`README.MD` is not a conventional README: it is the complete build specification for **PropSnap Investor**, written as a prompt to the implementer (it opens "You are an expert browser extension developer…" and ends with a 5-step build plan). The browser extension itself is not written yet. What exists is the data pipeline that will feed it: `scripts/fetch_gov_data.py`, `.github/workflows/update_data.yml` and the generated `data/*.json`. There is no `package.json`, bundler, linter, test suite or git history.

The spec was fact-checked on 31 Oct 2026 and revised on 1 Nov 2026 after the owner's v1 decisions (README Section 6). `SPEC_REVIEW.md` records every change with its evidence and what could not be verified; read it before "fixing" something in the spec that looks odd. Refresh this file once the extension code exists.

## Commands

- Refresh the data: `python scripts/fetch_gov_data.py` (needs `requests` and `pandas`; about 35 s; writes `data/`). It spaces its Data.gov.sg calls on purpose (anonymous limits are low). Environment: `URA_ACCESS_KEY` builds `data/private_psf.json` (without it that file is skipped and any existing copy is left alone); `DATA_GOV_SG_API_KEY` is optional. `--site-dir DIR` also stages the GitHub Pages site (data copy plus an `index.html` with the licence notices).
- The workflow runs monthly (3rd, 02:00 UTC) and on manual dispatch: it commits `data/` and deploys to GitHub Pages. It needs Settings > Pages > Source = "GitHub Actions" and has never run on GitHub yet.
- Load the extension unpacked: open `chrome://extensions` or `edge://extensions`, enable Developer mode, **Load unpacked**, select the extension folder. Safari: `xcrun safari-web-extension-converter <extension-folder>` (macOS + Xcode only; this workspace is Windows).

## What is being built

A Manifest V3 extension (Chrome, Edge, Safari) for PropertyGuru listings. v1 analytics are Singapore-only; on `propertyguru.com.my` the sidebar shows a "Malaysia Analytics Coming Soon." card and makes no requests. On Singapore listings it injects a fixed sidebar, `#propsnap-investor-sidebar`, showing: lease decay (99-year leasehold; warning under 60 years with computed text), asking PSF vs the HDB town / private district median, straight-line distance to the nearest MRT exit, a gross rental yield estimate, and a BSD/ABSD calculator (dated IRAS rates in the spec). The school badge was dropped. Freemium: 5 unique listing IDs in `chrome.storage.local`, then a blurred overlay with a Stripe Payment Link ($49) and a passphrase field checked against hardcoded SHA-256 hashes.

## Architecture (planned)

Scaffold the extension in `propsnap-investor/` (spec §2) so the Safari converter and store zips do not bundle the docs, scripts or data. Files: `manifest.json`, `background.js`, `content.js`, `popup.html`, `popup.js`, `styles.css`, `icon.png`.

- `background.js` (service worker) is the data layer: it fetches and caches (about a day, stale copy on failure) the three JSON files from GitHub Pages and calls the OneMap search endpoint (no token). `content.js` asks it through `chrome.runtime.sendMessage`; content-script requests are bound by the host page's same-origin policy. The extension must not call Data.gov.sg or URA.
- `content.js` scrapes the listing (resilient selectors, null fallbacks), computes the metrics, renders the sidebar and enforces the paywall. It is a classic script (no `import`).
- `popup.html` / `popup.js` handle passphrase entry; state is shared through `chrome.storage.local`.
- `styles.css` is injected into the host page by the manifest, so keep every selector under `#propsnap-investor-sidebar` or a `.propsnap-` prefix.
- Data schema (written by the script): `hdb_transactions.json` has `meta`, `street_to_town` (dataset names and spelled-out aliases) and `towns[town][flat_type]` with `n`, `median_price`, `median_psf`, `median_rent`, `rent_n`; `private_psf.json` has `sector_to_district` and `districts[d]` with `all` / `freehold` / `leasehold` `{n, median_psf}` plus `median_rent_psf`, `rent_n`; `mrt_stations.json` has `stations[{name, type, exits[[code, lat, lng]]}]`.

## Rules that are easy to get wrong

- Compliance: the Singapore Open Data Licence needs a conspicuous source notice (use each file's `meta.attribution`) and forbids implying government endorsement. URA's API key must stay in the `URA_ACCESS_KEY` Actions secret, never in the repo or the extension. Do not scrape URA's Property Market Information web pages: their Terms of Use allow personal, non-commercial use only. Never write the unlock passphrase into the repo; only its SHA-256 hash belongs in the extension.
- Treat the fetched JSON as untrusted: validate its shape and never insert its strings as HTML.
- Data formats differ: resale `flat_type` is `4 ROOM`, rental is `4-ROOM`; rental calls the town `CENTRAL` where resale says `CENTRAL AREA`. The script already normalises both.
- Benchmarks are town / district level and monthly. Do not present them as block- or project-level, and do not show a route or walking time as exact.
- Placeholders still to fill: `<owner>` and `<repo>` (Pages address), the Stripe Payment Link URL, the passphrase hash. Ask the user rather than guessing; also confirm the rental yield and stamp duty tool stay in v1.
