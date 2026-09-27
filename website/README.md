# Nettongia website

Static, dependency-free Cloudflare Pages site.

Cloudflare Pages settings:

- Production branch: `main`
- Root directory: `website`
- Framework preset: None
- Build command: leave empty
- Build output directory: `.`

The site intentionally uses no analytics, cookies, external scripts, external fonts or forms. Add the apex domain and `www` through Pages > Custom domains after Cloudflare DNS activation.

The homepage is available at `/` (English), `/cs/`, `/de/`, `/es/` and `/fr/`.
German, Spanish and French HTML are generated from `index.html` using
`python3 website/build_locales.py` (lxml is needed only for regeneration).
When English marketing text changes, update all three translations before
regenerating; the script checks the source strings. Commit the generated HTML
and run `python3 website/check_site.py` before deploying.
