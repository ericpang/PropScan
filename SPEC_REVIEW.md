# Spec review: README.MD

First review 31 Oct 2026; updated 1 Nov 2026 after the owner's v1 decisions (README Section 6). Claims were checked against primary documentation and, where possible, live endpoints. Git history only starts on 1 Nov 2026, after these changes were made, so this file records each change and the evidence behind it.

## Corrected in README.MD on 31 Oct (still in force)

1. **Manifest `matches` were invalid.** `https://propertyguru.com.sg*` has no path and was listed twice per country. Chrome's pattern structure is `<scheme>://<host>:<port>/<path>` and the path is required; live listings are on `www.` hosts. Now `https://*.propertyguru.com.sg/*` and `https://*.propertyguru.com.my/*`.
2. **Missing `icons` and `icon.png`.** The manifest referenced `icon.png`, which was not in the file tree, and lacked `icons`, a key the Chrome Web Store requires.
3. **Unused `activeTab` permission removed.** Nothing in the spec uses it. Add it back if a feature needs it.
4. **Lease warning text was not a real rule.** "Buyers under 39 years old" has no source. CPF's two published tests: the lease should cover the youngest buyer to age 95, and pro-rated usage is available when at least 20 years remain. Neither CPF page mentions 60 years or any buyer age cut-off. The age threshold is `95 - remaining lease` (36 at 59 years left, 45 at 50 years left; 39 only at 56). The 60-year figure looks like a leftover of pre-May-2019 HDB/CPF rules (from HDB material surfaced by search, not re-verified on the primary page). The warning now computes the age from the remaining lease; the 60-year trigger is kept and labelled a product choice. Calculation is limited to 99-year leasehold.
5. **BSD/ABSD rates were unspecified.** Added the current IRAS tables (BSD from 15 Feb 2023, ABSD from 27 Apr 2023) with an instruction to keep them in one dated table, because many sites still show pre-April-2023 ABSD. Charged on the higher of price and market value; the highest rate applies to joint purchasers of different profiles; Foreigner is disabled on HDB listings (HDB sells only to citizens and PRs).
6. **Smaller notes.** Content scripts cannot `import`; the Safari converter needs macOS with Xcode.

## Findings that shaped the live-API design (superseded, kept as evidence)

The 1 Nov decisions replaced live API calls with precompiled static data, but these facts still drive the data pipeline.

- **Content scripts cannot call these APIs freely.** Chrome: content scripts "initiate requests on behalf of the web origin", stay cross-origin "even if the extension has host permissions", and only service workers or extension pages with `host_permissions` are exempt. Live probes: data.gov.sg, OneMap and GitHub Pages send `access-control-allow-origin: *`, but URA's token endpoint sends none and its data endpoint answered an OPTIONS preflight with 404. The service worker survives as the extension's data layer.
- **HDB datasets.** Street names are upper case and abbreviated (`ANG MO KIO AVE 10`), flat types look like `4 ROOM` in the resale data but `4-ROOM` in the rental data, and the rental data calls the town `CENTRAL` where resale says `CENTRAL AREA`. Data.gov.sg limits anonymous Datastore Search to 4 calls per 10 seconds (8 with a developer key, 20 with a production key).
- **URA Data Service.** `PMI_Resi_Transaction` takes only `batch=1..4` (postal districts), returns five years of transactions, needs an `AccessKey` header plus a daily `Token`, and has no PSF field (`area` is sqm, `contractDate` is `MMYY`). Rent is `PMI_Resi_Rental_Median` (per sq ft per month, projects with 10+ contracts) or `PMI_Resi_Rental` (contracts, one quarter per call). URA's API Terms of Service (updated 17 Apr 2026) allow commercial use and require credentials to be kept "secure and confidential".
- **OneMap.** Routing without a token returns 401; tokens need a registered account. Search works without a token (verified live). "Barrier-free" routing was not found in any documentation I could read.

## Decisions applied on 1 Nov 2026

- **Malaysia:** analytics off on `.com.my`; placeholder card "Malaysia Analytics Coming Soon."; no data requests; not counted toward the free allowance.
- **Data:** static JSON on GitHub Pages (`data/hdb_transactions.json`, `data/private_psf.json`, `data/mrt_stations.json`), fetched and cached by the extension, instead of bundled. The owner's mid-session clarification moved delivery from "inside the extension folder" to Pages, which also removes the need to re-publish the extension for every monthly refresh. `host_permissions` are now OneMap and the Pages host (both optional in practice, see the README note).
- **Benchmarks are coarse by design:** HDB per town and flat type, private per URA district, replacing the block-level and project-level comparisons of the original spec.
- **MRT:** OneMap public search for coordinates plus a Haversine distance to station exits; walking time only as a labelled estimate. Routing, the token and the "walking distance" wording are gone.
- **Paywall:** unique listing IDs in `chrome.storage.local`; unlock by passphrase checked against hardcoded SHA-256 hashes; passphrase delivered through the Stripe Payment Link's custom confirmation message (Stripe docs: "replace the default message with a custom one"), which only the payer sees, instead of a public redirect page.
- **School badge dropped.** Rental yield and the stamp duty tool were not mentioned in the decision to "focus strictly" on MRT, lease decay and transaction variance, so they stay in v1 unless the owner says otherwise.
- **Store-facing wording corrected:** the manifest description no longer says "live government transaction logs" or "MRT walking distances" (129 of 132 characters); the intro now says "data-driven" and "estimated rental yields".
- **Licence compliance added:** the Singapore Open Data Licence requires "a conspicuous notice acknowledging the source of the datasets" with a link to the licence, and forbids implying official status. Each data file carries `meta.attribution`, the Pages index page shows the notices, and the sidebar footer must show them.
- **URA's web portal is not used.** The page at `eservice.ura.gov.sg/property-market-information/pmiResidentialTransactionSearch` is a two-step search form (one POST form, no export or download option). URA's Terms of Use (updated 24 Apr 2026) allow viewing, downloading and printing for "personal and non-commercial use" and require URA's prior written consent for anything else, including distributing or commercially exploiting the content. The Data Service API is the sanctioned programmatic route; registration is by email on the developer portal and the pages I read mention no fee (not confirmed either way).

## Data pipeline review (`scripts/fetch_gov_data.py`, `.github/workflows/update_data.yml`)

Defects found in the versions that were in the repo, and what changed:

- **Malformed URL.** `f"https://data.gov.sg{resource_id}&limit=5000"` evaluates to `https://data.gov.sgd_8b84...&limit=5000`, a host that does not exist. Replaced by the documented bulk download (initiate, then poll, on `api-open.data.gov.sg`), which fetched the 23 MB resale and 10 MB rental files in about 2 seconds each.
- **Wrong rows even with a correct URL.** Without a sort, `limit=5000` returns the oldest rows: the first rows of the 243,874-row dataset are January 2017, so the medians would have been about a decade old. Now each median covers the latest 6 months present in its own dataset (resale 2026-05..2026-10, rental 2026-04..2026-09).
- **Silent failure.** Every exception was swallowed and the script exited 0. Failures now stop the run.
- **Missing pieces.** No sample size, no rent, no street lookup, no MRT file, and `data/private_psf.json` was never created although the workflow `git add`s it (git errors on a missing path). The script now writes `n`, `median_rent`, `rent_n`, a street-to-town lookup (580 dataset names plus 519 spelled-out aliases), `mrt_stations.json` (188 stations, 613 exits) and, when `URA_ACCESS_KEY` is set, `private_psf.json`.
- **Workflow.** Could not push without `contents: write` under read-only default token permissions; commit message hard-coded "November 2026"; cron on the 1st at 00:00 UTC ran before the rental dataset refresh (resale was updated 1 Nov 02:10 SGT, rental on 2 Oct), now the 3rd at 02:00 UTC; Python 3.10 reaches end of life in October 2026, now 3.12; deploys to GitHub Pages with `actions/upload-pages-artifact` and `actions/deploy-pages` (documented minimum `pages: write` and `id-token: write`). In a public repository GitHub disables scheduled workflows after 60 days without repository activity, so the monthly data commit doubles as a keep-alive.

Checks run: all 127 HDB town/flat-type groups recomputed independently with plain Python (0 mismatches); street lookup matches the source for all 580 names and no alias points at a different town; the URA and MRT aggregation logic passes 18 checks against synthetic payloads shaped like the documented API (URA postal-district table from URA's own list: 81 sectors); `write_site` output inspected; the workflow YAML parsed and its structure checked.

## Checked, left unchanged

- JSON validity, `manifest_version` 3, name 48/75 characters, CSP string (valid, equals the MV3 default).
- Lease and gross-yield formulas (lease formula for 99-year leasehold only).
- BSD brackets and ABSD rates match IRAS.
- Listing URL shapes seen in search results: Singapore `/listing/hdb-for-sale-<slug>-<id>`, Malaysia `/property-listing/<slug>-for-sale-by-<agent>-<id>`.

## Not verified

- The workflow has not completed a run on GitHub yet (the first run failed because the script had not been pushed): the `GITHUB_TOKEN` push and the Pages deploy are untested.
- URA live calls (no access key here): only the aggregation logic was tested, with synthetic data.
- PropertyGuru's DOM (selectors, the "Built:" label, whether a tenure field exists) and whether its street spellings match the lookup keys.
- OneMap search rate limits; OneMap's official docs were not readable.
- CPF usage below 20 years of lease, and whether CPF can pay ABSD (IRAS defers to CPF Board terms), so the spec's "cash/CPF threshold" stays generic.
- Safari host-permission prompts; PropertyGuru's terms of use and branding; Section 1 marketing claims.

## Optional, not applied

- `styles.css` defines its tokens on `:root`, which leaks the `--propsnap-*` variables into the host page. Scoping them to `#propsnap-investor-sidebar` fits "never break the host" better; a Shadow DOM would isolate both ways but then the stylesheet must be loaded into the shadow root.

## Sources

- [Chrome match patterns](https://developer.chrome.com/docs/extensions/develop/concepts/match-patterns), [network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests), [manifest reference](https://developer.chrome.com/docs/extensions/reference/manifest)
- [Data.gov.sg API rate limits](https://guide.data.gov.sg/developer-guide/api-overview/api-rate-limits), [HDB resale dataset](https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view), [LTA MRT Station Exit dataset](https://data.gov.sg/datasets/d_b39d3a0871985372d7e1637193335da5/view), [Singapore Open Data Licence](https://data.gov.sg/open-data-licence)
- [URA Data Service API documentation](https://eservice.ura.gov.sg/maps/api/), [URA API Terms of Service](https://www.ura.gov.sg/ms/eservices/Maps/API-terms-of-service), [URA Terms of Use](https://www.ura.gov.sg/terms-of-use/), [URA postal districts (archived)](https://web.archive.org/web/20230309010306/https://www.ura.gov.sg/realEstateIIWeb/resources/misc/list_of_postal_districts.htm), [URA API sign-up](https://www.developer.tech.gov.sg/products/categories/data-and-apis/ura-apis/getting-started)
- [GitHub Actions: schedule event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [custom workflows for Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [Stripe Payment Links after payment](https://docs.stripe.com/payment-links/post-payment)
- [OneMap API write-up (third party)](https://sheshbabu.com/posts/exploring-singapore-onemap-api)
- [IRAS BSD](https://www.iras.gov.sg/taxes/stamp-duty/for-property/buying-or-acquiring-property/buyer's-stamp-duty-(bsd)), [IRAS ABSD](https://www.iras.gov.sg/taxes/stamp-duty/for-property/buying-or-acquiring-property/additional-buyer's-stamp-duty-(absd))
- [CPF: lease not covering the youngest buyer to 95](https://www.cpf.gov.sg/service/article/how-much-cpf-savings-can-i-use-to-buy-a-property-if-its-lease-does-not-cover-the-youngest-buyer-to-age-95), [CPF: how much CPF you can use](https://www.cpf.gov.sg/member/infohub/educational-resources/how-much-cpf-savings-you-can-use-for-your-home-purchase)
