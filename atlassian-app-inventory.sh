#!/usr/bin/env bash
# Atlassian connected-apps inventory: installed version + update-available.
#
# Connect apps  -> UPM REST      (one call per product)
# Forge apps    -> GraphQL       (paginated; one call per product context)
# MCP servers   -> not covered (separate GraphQL surface, and they carry no version)
#
# Usage:
#   export CLOUD_ID=...            # the <uuid> in admin.atlassian.com/s/<uuid>/user-connected-apps
#   export ATL_COOKIE="$(cat ~/.atlassian-cookie)"
#   ./atlassian-app-inventory.sh            # table
#   ./atlassian-app-inventory.sh --json     # raw json per source

set -uo pipefail

: "${CLOUD_ID:?set CLOUD_ID (the uuid in the admin URL)}"
: "${ATL_COOKIE:?set ATL_COOKIE (see README section: getting the cookie)}"

GW="https://admin.atlassian.com/gateway/api"
PRODUCTS="${PRODUCTS:-jira confluence jira-servicedesk bitbucket compass}"
JSON_MODE="${1:-}"

req() { curl -sS --compressed -b "$ATL_COOKIE" "$@"; }

# ---------- Connect apps (UPM REST) ----------
connect_apps() {
  local product="$1" root marketplace
  root=$(req -w '\n%{http_code}' \
      -H 'Accept: application/vnd.atl.plugins.installed+json' \
      "$GW/ex/$product/$CLOUD_ID/rest/plugins/1.0/")
  [ "$(printf '%s' "$root" | tail -n1)" = "200" ] || return 0
  root=$(printf '%s' "$root" | sed '$d')

  # second call carries updateAvailable (note: different Accept type)
  marketplace=$(req -H 'Accept: application/vnd.atl.plugins+json' \
      "$GW/ex/$product/$CLOUD_ID/rest/plugins/1.0/installed-marketplace?updates=true")

  jq -n --arg product "$product" \
        --argjson root "$root" \
        --argjson mkt "$marketplace" '
    ($mkt.plugins // [] | map({key: .key, value: .updateAvailable}) | from_entries) as $upd
    | $root.plugins
    | map(select(.remotable))          # remotable == Connect app; excludes ~200 internal plugins
    | map({product: $product, type: "connect", key, name, version,
           enabled, updateAvailable: ($upd[.key] // null)})'
}

# ---------- Forge apps (GraphQL, paginated) ----------
forge_apps() {
  local product="$1" after=null out='[]' page nodes has
  local ctx="ari:cloud:${product}::site/${CLOUD_ID}"
  local q='query Inv($ctx:String!,$after:String){ecosystem{appInstallationsByContext(
      filter:{appInstallations:{contexts:[$ctx]}},first:50,after:$after){
      pageInfo{hasNextPage endCursor}
      nodes{app{id name} appEnvironment{type} appEnvironmentVersion{version isLatest}}}}}'
  while :; do
    page=$(req -X POST "$GW/graphql" \
        -H 'Content-Type: application/json' \
        -H 'X-ExperimentalApi: AppEnvironmentVersionTrustSignal' \
        --data "$(jq -n --arg q "$q" --arg ctx "$ctx" --argjson after "$after" \
                  '{query:$q, operationName:"Inv", variables:{ctx:$ctx, after:$after}}')")
    nodes=$(printf '%s' "$page" | jq -c '.data.ecosystem.appInstallationsByContext.nodes // []' 2>/dev/null) || break
    [ "$nodes" = "[]" ] && [ "$out" = "[]" ] && break
    out=$(jq -n --argjson a "$out" --argjson b "$nodes" --arg product "$product" '
      $a + ($b | map({product:$product, type:"forge", key:.app.id, name:.app.name,
                      version:.appEnvironmentVersion.version,
                      environment:.appEnvironment.type,
                      updateAvailable:(if .appEnvironmentVersion.isLatest == null then null
                                       else (.appEnvironmentVersion.isLatest|not) end)}))')
    has=$(printf '%s' "$page" | jq -r '.data.ecosystem.appInstallationsByContext.pageInfo.hasNextPage')
    [ "$has" = "true" ] || break
    after=$(printf '%s' "$page" | jq '.data.ecosystem.appInstallationsByContext.pageInfo.endCursor')
  done
  printf '%s' "$out"
}

ALL='[]'
for p in $PRODUCTS; do
  for src in "$(connect_apps "$p")" "$(forge_apps "$p")"; do
    [ -z "$src" ] && continue
    ALL=$(jq -n --argjson a "$ALL" --argjson b "$src" '$a + $b' 2>/dev/null || printf '%s' "$ALL")
  done
done

if [ "$JSON_MODE" = "--json" ]; then
  printf '%s\n' "$ALL" | jq .
else
  printf '%s\n' "$ALL" | jq -r '
    (["PRODUCT","TYPE","NAME","VERSION","UPDATE?"] | @tsv),
    (.[] | [.product, .type, (.name // "-"), (.version // "-"),
            (if .updateAvailable == true then "YES" elif .updateAvailable == false then "-" else "?" end)] | @tsv)' \
    | column -t -s $'\t'
fi
