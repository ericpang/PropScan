# Product Specification: PropSnap Investor - Real Estate Intelligence Extension
## Target Systems: Google Chrome, Microsoft Edge, and Apple Safari (Manifest V3 Framework)

You are an expert browser extension developer and senior software engineer. Your task is to build **PropSnap Investor**, a cross-browser extension explicitly engineered for property buyers, retail investors, and house hunters in Singapore and Malaysia. The extension injects a clean, premium, data-driven analytics sidebar directly onto PropertyGuru listing pages (`propertyguru.com.sg` and `propertyguru.com.my`) to expose lease decay risks, historical pricing disparities, estimated rental yields, and spatial infrastructure data locally within the browser framework.

---

## 1. Product Vision & Monetization Strategy (Zero Ad Spend Model)
* **The Strategic Value Gap:** PropertyGuru listings feature heavily stylized marketing content. Buyers must manually look up disparate government data portals (URA/HDB/SLA) to verify actual transacted metrics. PropSnap Investor aggregates these hard data points directly on the active tab layout.
* **Organic Distribution Channel:** Homebuyers and retail investors are highly numbers-driven. They organically capture and share screenshots of data-heavy tool panels in local finance communities, investment subreddits (e.g., `r/singaporefi`, `r/malaysia`), HardwareZone, and investor Telegram channels, driving continuous viral growth with \$0 ad spend.
* **Freemium Tier Paywall:** The extension allows the user to analyze 5 unique property listings completely free (reloading a listing does not use up the allowance). On the 6th unique listing, a premium glassmorphic overlay locks the interface, redirecting them to a Stripe Payment Link (\$49 one-time lifetime key) to unlock unlimited data sweeps. Status metrics are stored locally via `chrome.storage.local` with zero database dependencies. Step 4 and Section 6 describe the counter and the unlock passphrase.

---

## 2. Project Directory Structure
Generate the following core files with clean, modular JavaScript, HTML, and CSS:
```text
propsnap-investor/
├── manifest.json         # Extension configuration (Manifest V3 Framework)
├── background.js         # Service worker: data layer (fetches and caches the GitHub Pages JSON files, calls the OneMap search endpoint)
├── content.js            # Page DOM scraping, analytics calculations, and Panel Injection
├── popup.html            # Extension Toolbar Dropdown UI (License key entry & profile)
├── popup.js              # Controls global user credentials & license verification variables
├── styles.css            # Scoped design tokens, typography rules, and container properties
├── icon.png              # Toolbar and store icon referenced by manifest.json (128x128 PNG)
└── README.md             # This specification document
```

The data files are not part of the extension. Tooling in the same repository generates them and publishes them to GitHub Pages:
```text
scripts/fetch_gov_data.py          # Builds data/*.json from Data.gov.sg (and from URA when URA_ACCESS_KEY is set)
.github/workflows/update_data.yml  # Monthly: runs the script, commits data/, deploys it to GitHub Pages
data/hdb_transactions.json         # HDB medians per town and flat type, plus a street -> town lookup
data/private_psf.json              # Private condo PSF and rent medians per URA postal district
data/mrt_stations.json             # MRT/LRT station exits (lat/lng)
```

---

## 3. Component Specifications

### A. Manifest File (`manifest.json`)
Must be strictly Manifest V3 compliant. Ensure match patterns safely cover both Singapore and Malaysia PropertyGuru listing variations.
```json
{
  "manifest_version": 3,
  "name": "PropSnap Investor - Property Analytics Assistant",
  "version": "1.0.0",
  "description": "Lease decay warnings, HDB and condo price benchmarks, rental yield estimates and MRT distance on PropertyGuru Singapore listings.",
  "permissions": [
    "storage"
  ],
  "host_permissions": [
    "https://www.onemap.gov.sg/*",
    "https://<owner>.github.io/*"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "icons": {
    "16": "icon.png",
    "48": "icon.png",
    "128": "icon.png"
  },
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icon.png",
      "48": "icon.png",
      "128": "icon.png"
    }
  },
  "content_scripts": [
    {
      "matches": [
        "https://*.propertyguru.com.sg/*",
        "https://*.propertyguru.com.my/*"
      ],
      "js": ["content.js"],
      "css": ["styles.css"]
    }
  ],
  "content_security_policy": {
    "extension_pages": "script-src 'self'; object-src 'self';"
  }
}
```

Manifest notes:
* Every match pattern needs a path (`/*`), and a `*.` host also matches the bare domain, so the two patterns above cover `www.` and any other subdomain. Keep `matches` at host level and have `content.js` detect listing URLs itself (Singapore: `/listing/...`, Malaysia: `/property-listing/...`): narrower patterns could miss client-side navigation from a search page to a listing.
* `host_permissions` apply to the service worker only (content-script requests are always cross-origin requests from the host page, whatever host permissions the extension holds). Replace `<owner>` with the GitHub account that serves the data. Both hosts currently send `Access-Control-Allow-Origin: *`, so the permissions could be dropped to shorten the install warning, at the cost of relying on that header.
* Provide `icon.png` as a 128x128 PNG; it is reused for the 16 and 48 sizes.

### B. Core Scraping & Analytics Engine (`content.js` and `background.js`)
When a listing page successfully builds, `content.js` must safely extract data via resilient selectors (with null fallbacks) and execute the following core processing tracks. Every network request is made by `background.js` and requested from `content.js` with `chrome.runtime.sendMessage`: content-script requests are bound by the host page's same-origin policy. The extension makes only two kinds of request: the JSON data files on GitHub Pages (data only, never code; cached in `chrome.storage.local` for about a day, with the stale copy used if a refresh fails) and the OneMap search endpoint (no token).

> **Scope:** every data source and rule in this section (HDB, URA, OneMap, BSD/ABSD, CPF) is specific to Singapore. On `propertyguru.com.my` v1 shows a placeholder card in the sidebar reading "Malaysia Analytics Coming Soon.", makes no data requests and does not count the listing toward the free allowance.

1. **Lease Decay Risk Matrix:**
   * Extract construction/TOP year text (e.g., "Built: 1983"). Only calculate for 99-year leasehold listings; skip freehold and other tenures.
   * Calculate remaining lease length: `Remaining Lease = 99 - (CurrentYear - BuiltYear)`. This is an approximation: the lease runs from lease commencement, not completion, so the true remaining lease can differ by a year or two.
   * **Conditional UI Rule:** If remaining lease is < 60 years, append a red warning label stating: *"Note: Remaining lease is {R} years. CPF can be used in full only if the lease lasts until the youngest buyer turns 95, i.e. the youngest buyer must be at least {95 - R} years old. Otherwise CPF usage is pro-rated (and needs at least 20 years of lease left) and loan financing may be reduced."* (`{R}` is the remaining lease in whole years.) The 60-year trigger is a product choice, not an official threshold: CPF's test is the youngest buyer's age plus the remaining lease being at least 95, and 60 years is the lease that exactly covers a 35-year-old.

2. **Transaction Variance & Location (Static Data Layer):**
   * **Data files:** `data/hdb_transactions.json`, `data/private_psf.json` and `data/mrt_stations.json` are generated monthly by `scripts/fetch_gov_data.py` and served from GitHub Pages at `https://<owner>.github.io/<repo>/data/`. Each file has a `meta` block with `generated_on`, the source datasets and the licence attribution. Treat the files as untrusted input: check their shape before use and never insert their strings into the page as HTML. If a file cannot be loaded and there is no cached copy, show "Market data unavailable" in place of the affected cards; lease decay and the stamp duty tool keep working.
   * **HDB Variance:** For public flats, upper-case the scraped street and look it up in `street_to_town` (it holds both the dataset's abbreviated names, e.g. `TAMPINES ST 41`, and the spelled-out forms, e.g. `TAMPINES STREET 41`) to get the town; if it is not found, leave the card out rather than guess. Then read `towns[town][flat_type]` (flat types look like `4 ROOM`): `median_price`, `median_psf` and `n` for the latest 6 months of resale transactions in that town and flat type. Compare like with like: `(Asking PSF - median_psf) / median_psf * 100`, where Asking PSF is the asking price divided by the listing's floor area in sq ft. Show the town, flat type, `n` and the data month, and flag a small `n`.
   * **Private Variance:** For condos/apartments, take the postal code from the OneMap result (`POSTAL`), map its first two digits to a URA district with `sector_to_district`, and read `districts[district]` in `private_psf.json`. Use the `freehold` or `leasehold` entry that matches the listing's tenure (fall back to `all`). `median_psf` is the median transacted PSF of resales and sub sales over the latest 12 months. Compare it with the asking PSF as above and highlight the listing's premium or discount tier. This is a district benchmark, not a project-level one, so label it that way (for example "District 15 median").
   * **MRT Distance (no routing):** Geocode the address or project name with the OneMap search endpoint (`https://www.onemap.gov.sg/api/common/elastic/search?searchVal=...&returnGeom=Y&getAddrDetails=Y&pageNum=1`; no token needed; use `LATITUDE`, `LONGITUDE` and `POSTAL` of the first result) and cache the result. Then use the Haversine formula (`Math.sin`, `Math.cos`, `Math.asin`, `Math.sqrt`) to find the nearest station exit in `mrt_stations.json`, considering `type: "MRT"` stations unless LRT is wanted. Show the station, the exit and the straight-line distance. A walking time may be shown only as an estimate, `distance * 1.3 / 80` minutes (assumed detour factor and walking speed), never as a route. If geocoding fails, omit the card.
   * **Attribution:** show a conspicuous footer in the sidebar with the `meta.attribution` text of the data files in use (or a short "Contains information from ... made available under the Singapore Open Data Licence version 1.0" with a link to https://data.gov.sg/open-data-licence) and a line saying the product is not endorsed by any Government agency. The licence requires the notice and forbids implying official status.

3. **Rental Yield Calculator Logic:**
   * **HDB Rental Stream:** Use `median_rent` and `rent_n` from the same `towns[town][flat_type]` entry: the median monthly rent of HDB rental approvals in that town and flat type over the latest 6 months. Multi-generation flats have no rent figure; skip the yield for them.
   * **Private Residential Rental Stream:** Use `median_rent_psf` (SGD per sq ft per month) and `rent_n` from `districts[district]`, multiplied by the listing's floor area, to get a monthly rent. It is the median of URA's project-level quarterly median rents over the latest 4 quarters; skip the yield if the district has no rent figure.
   * **Mathematical Execution:**
     * Extract the raw annual rental income cash flow: `Annual Rent = Monthly Median Rent * 12`.
     * Extract the raw listing asking price (`Listing Price`).
     * Calculate **Gross Rental Yield (%)** = `(Annual Rent / Listing Price) * 100`.
     * Display this dynamic percentage badge clearly within the main metrics section of the sidebar. Label it as an estimate based on a town or district median rent.

4. **Tax & Stamp Duty Matrix Tool:**
   * Program interactive selectors inside the injected panel:
     * **Buyer Identity:** Singapore Citizen | Permanent Resident | Foreigner.
     * **Property Count:** 1st Property | 2nd Property | 3rd+ Property.
   * Compute calculations against standard Buyer's Stamp Duty (BSD) brackets and Additional Buyer's Stamp Duty (ABSD) tiers to display the required upfront cash/CPF threshold framework. Both duties are charged on the higher of the purchase price and the market value, rounded down to the nearest dollar. The rates below are from IRAS (checked 31 Oct 2026); keep them in one dated constants table, because they change by government announcement.
     * **BSD (residential, on or after 15 Feb 2023), marginal brackets:** first \$180,000 at 1%; next \$180,000 at 2%; next \$640,000 at 3%; next \$500,000 at 4%; next \$1,500,000 at 5%; remainder at 6%.
     * **ABSD (on or after 27 Apr 2023), for the 1st / 2nd / 3rd+ property:** Singapore Citizen 0% / 20% / 30%; Permanent Resident 5% / 30% / 35%; Foreigner 60% on any residential property.
     * When buyers of different profiles purchase jointly, IRAS applies the highest applicable ABSD rate to the entire value. ABSD remission and refund schemes (e.g. for HDB upgraders) are not modelled. HDB flats can be bought only by Singapore Citizens and Permanent Residents, so disable "Foreigner" on HDB listings.

---

## 4. UI Style Tokens & Aesthetics (`styles.css`)
The overlay container (`id="propsnap-investor-sidebar"`) must reflect premium, minimalist design paradigms. It must completely encapsulate its own styles so it never breaks the host website's layout configuration:

```css
:root {
  --propsnap-bg: rgba(255, 255, 255, 0.9);
  --propsnap-blur: blur(24px);
  --propsnap-border: rgba(226, 232, 240, 0.8);
  --propsnap-dark: #0F172A; /* Slate 900 */
  --propsnap-blue: #2563EB; /* Premium Accent Blue */
  --propsnap-amber: #D97706; /* Warning Orange */
  --propsnap-red: #DC2626; /* Critical Alert Red */
  --propsnap-text-main: #334155;
  --propsnap-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.15);
  --propsnap-radius: 20px;
}

#propsnap-investor-sidebar {
  position: fixed;
  top: 32px;
  right: 32px;
  width: 340px;
  background: var(--propsnap-bg);
  backdrop-filter: var(--propsnap-blur);
  -webkit-backdrop-filter: var(--propsnap-blur);
  border: 1px solid var(--propsnap-border);
  border-radius: var(--propsnap-radius);
  box-shadow: var(--propsnap-shadow);
  padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
  z-index: 2147483647;
  color: var(--propsnap-text-main);
}

.propsnap-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--propsnap-dark);
  letter-spacing: -0.03em;
  margin-bottom: 12px;
}

.propsnap-alert-box {
  background: rgba(254, 226, 226, 0.5);
  border: 1px solid rgba(239, 68, 68, 0.3);
  padding: 12px;
  border-radius: 12px;
  font-size: 12px;
  color: var(--propsnap-red);
  line-height: 1.4;
  margin-bottom: 16px;
}

.propsnap-metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 16px;
}

.propsnap-metric-card {
  background: rgba(248, 250, 252, 0.6);
  border: 1px solid var(--propsnap-border);
  padding: 10px;
  border-radius: 10px;
}
```

---

## 5. Execution Step-by-Step Instructions for Claude
1. **Step 1:** Generate the structural implementation framework for `manifest.json`.
2. **Step 2:** Write the complete JavaScript text compilation parsing rules within `content.js` to parse element blocks containing prices, sizes, and build dates across both `propertyguru.com.sg` and `propertyguru.com.my`.
3. **Step 3:** Implement the data layer in `background.js` using modular layout classes: fetch and cache the three JSON files from GitHub Pages, geocode through the OneMap search endpoint, and expose both to `content.js` through `chrome.runtime.sendMessage`. Content scripts are classic scripts (no `import`), so keep `content.js` self-contained or list extra files in the manifest's `js` array. The data files come from `scripts/fetch_gov_data.py`; the extension must not call Data.gov.sg or URA itself.
4. **Step 4:** Implement the freemium gate inside `chrome.storage.local` with two keys: `seenListings` (array of unique listing IDs, at most 5) and `licensed` (boolean). The listing ID is the trailing number in the listing URL path (e.g. `.../hdb-for-sale-432-tampines-street-41-60195175` gives `60195175`). A listing already in `seenListings` stays unlocked when reloaded; a new Singapore listing is added only while the array holds fewer than 5 IDs. Otherwise, and while `licensed` is false, cleanly hide the analysis elements beneath a premium blurred billing shield displaying the Stripe Payment Link button and a passphrase field. The Malaysia placeholder never counts. To unlock, hash the entered passphrase with `crypto.subtle.digest('SHA-256')` and compare it with a hardcoded list of valid hashes (never ship the plaintext; a list lets the passphrase be rotated); on a match set `licensed` to true.
5. **Step 5:** Provide terminal compile configurations allowing effortless cross-browser builds across Google Chrome (Load unpacked folder), Microsoft Edge Add-ons, and local Safari translation packaging strings (`xcrun safari-web-extension-converter`, which runs only on macOS with Xcode installed).

---

## 6. Decisions for v1 and Known Limits
Decided on 1 Nov 2026 to keep v1 serverless and zero-cost:
1. **Malaysia (`propertyguru.com.my`):** live analytics are disabled in v1. The sidebar shows a "Malaysia Analytics Coming Soon." placeholder card (see the scope note in Section 3.B).
2. **Data and credentials:** the extension holds no credentials and calls no government API except OneMap's public search. Market data is precompiled into static JSON by `scripts/fetch_gov_data.py`, which the monthly workflow `.github/workflows/update_data.yml` runs and deploys to GitHub Pages. The URA AccessKey (register at https://www.developer.tech.gov.sg/products/categories/data-and-apis/ura-apis/getting-started; the sign-up pages mention no fee) exists only as the Actions secret `URA_ACCESS_KEY`; URA's API Terms of Service require it to stay "secure and confidential". An optional `DATA_GOV_SG_API_KEY` secret raises Data.gov.sg rate limits. Do not scrape URA's Property Market Information web pages as a substitute: URA's Terms of Use allow viewing, downloading and printing them for personal and non-commercial use only, and anything else (distributing, commercially exploiting) needs URA's prior written consent. MRT proximity is straight-line (Haversine), not a routed walk.
3. **License key and free counter:** the allowance counts unique listing IDs (Step 4). Unlocking uses a passphrase checked against SHA-256 hashes hardcoded in the extension. Put the passphrase in the Stripe Payment Link's custom confirmation message (Dashboard > Payment Links > After the payment > Confirmation page), which only the payer sees, rather than on a public page.
4. **Primary-school badge:** dropped from v1 to keep the data files small. The rental yield estimate and the stamp duty tool stay in v1 unless the owner says otherwise.

Owner to-do before release:
* In the repository settings set Pages > Source to "GitHub Actions", then run the workflow once from the Actions tab (a repository must be public to use Pages on a free GitHub plan).
* Register for a URA Data Service API access key and add it as the Actions secret `URA_ACCESS_KEY`; without it `data/private_psf.json` is never created and private-property benchmarks and rent estimates stay unavailable. Optionally add `DATA_GOV_SG_API_KEY`.
* Replace `<owner>` and `<repo>` in the manifest and `background.js` with the real Pages address.
* Generate a long random passphrase, keep only its SHA-256 hash in the extension, paste the plaintext into the Stripe confirmation message, and create the Payment Link.

Known limits (accepted for v1):
* The paywall is soft: the extension is readable and editable by anyone who installs it, the passphrase is one shared secret that can be passed around, and reinstalling resets the free allowance. Hashing only keeps the passphrase out of the source.
* Benchmarks are coarse and monthly: HDB at town and flat-type level, private property at URA-district level. They are not block- or project-level valuations.
* GitHub's Pages policy says Pages is not meant for sites primarily directed at commercial transactions or commercial SaaS. Static public data for a paid extension is a gray area; if it is questioned, the same files can move to another static host with only the base URL changed.
