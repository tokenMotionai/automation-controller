# Atlassian Cloud connected-apps: version + update endpoints

The Admin Hub "Connected apps → Installed apps" page is backed by the **UPM
(Universal Plugin Manager) REST API** on the product itself, proxied through the
admin gateway. Verified by capturing the page's network traffic on
`admin.atlassian.com/s/<cloudId>/user-connected-apps/tab/installed`.

## Auth

Basic auth: `<atlassian-account-email>:<api-token>` (token from
https://id.atlassian.com/manage-profile/security/api-tokens).
The account must be a **site admin** (org admin alone is not enough — UPM is a
product-level API).

Send `Accept: */*`. UPM rejects `Accept: application/json` with **406**.

Base URL (Jira):        `https://<site>.atlassian.net/rest/plugins/1.0`
Base URL (Confluence):  `https://<site>.atlassian.net/wiki/rest/plugins/1.0`

Each product has its own app list — query both if you run both.

## 1. Installed version of every app (one call)

```
GET {base}/
```

Returns `{ "plugins": [ ... ] }`, one entry per app:

| field           | meaning |
|-----------------|---------|
| `key`           | app key, e.g. `com.codebarrel.addons.automation` |
| `name`          | display name |
| `version`       | **the version your site is on** |
| `userInstalled` | `true` = admin-installed, `false` = bundled/system |
| `enabled`       | enabled state |
| `vendor.name`   | vendor |

## 2. Which apps have an update (one call)

```
GET {base}/installed-marketplace?updates=true
```

Returns `{ "plugins": [ { "key", "name", "updateAvailable", ... } ] }`.

`updateAvailable: true` is Atlassian's own "needs updating" flag — it already
accounts for host/product compatibility, so it is more accurate than comparing
raw Marketplace version strings yourself. No version numbers here, just the flag.

## 3. Latest available version for one app (one call per app)

```
GET {base}/available/{appKey}-key
```

Note the literal **`-key` suffix** appended to the app key — required, else 400
`"Cannot unescape the given app key. It must end in a \"-key\" suffix."`

Response contains both numbers side by side:

| field                       | meaning |
|-----------------------------|---------|
| `version`                   | **latest version available to update to** |
| `installedVersion`          | version currently installed on your site |
| `installed`                 | boolean |
| `name`, `vendor.name`       | display info |
| `marketplaceType`           | e.g. `PAID_VIA_ATLASSIAN` |
| `versionDetails.releaseDate`| epoch ms |
| `versionDetails.releaseNotes` | release-notes URL |

## Recommended call pattern for the Slack report

1. `GET {base}/` → map `key → {name, version}` (installed version), filter to
   `userInstalled == true` to drop bundled system apps.
2. `GET {base}/installed-marketplace?updates=true` → set of keys where
   `updateAvailable == true`.
3. For **only** those keys: `GET {base}/available/{key}-key` → read `version`
   (latest) and `installedVersion` (current).
4. Post the resulting list to Slack.

Two bulk calls plus one call per outdated app — no per-app fan-out across all
several-dozen apps, and no need for the public Marketplace API at all. If you
still want the public Marketplace latest version for cross-checking:
`https://marketplace.atlassian.com/rest/2/addons/{appKey}/versions/latest?application=jira&applicationBuild=100000`

## Other endpoints seen

- `GET {base}/{appKey}/marketplace` — per-app `updateAvailable` flag (no `-key` suffix)
- `GET {base}/{appKey}-key/summary` — per-app installed `version`
- `GET {base}/pending` — in-flight install/update tasks

## Admin-gateway variant (browser session only)

What the Admin Hub page actually calls; needs browser cookies, not an API token,
so it is not useful from a script — listed only for reference:

```
https://admin.atlassian.com/gateway/api/ex/jira/<cloudId>/rest/plugins/1.0/
https://admin.atlassian.com/gateway/api/ex/jira/<cloudId>/rest/plugins/1.0/installed-marketplace?updates=true
https://admin.atlassian.com/gateway/api/ex/confluence/<cloudId>/rest/plugins/1.0/
```
