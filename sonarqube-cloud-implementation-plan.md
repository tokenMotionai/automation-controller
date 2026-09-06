# SonarQube Cloud — draft implementation plan

**Draft — 31 August 2026**

Two questions to answer: what does scanning a GitHub repo with SonarQube Cloud actually look like, and how far does that picture drift from the on-prem SonarQube Server we already run at `https://<localurl>`.

Short answer: the two environments differ almost entirely in *onboarding and plumbing*, not in *scanning*. The scan step itself can be one shared reusable workflow with a swapped host URL and token. Everything expensive is in the authorization path.

---

## Recommendation

**Standardise on one central reusable workflow, parameterised by environment.** App teams call it in three lines and never learn which backend they hit. We keep control of the scanner version, the quality gate behaviour, and the token wiring in one place.

The only genuine per-repo work on our side is deciding a repo is allowed to send code to SonarSource's servers, and toggling it into the GitHub App installation. That is a checkbox once the process exists.

---

## The big picture — SonarQube Cloud

```
GitHub org
  │
  │ (1) "SonarQube Cloud" GitHub App installed on the org
  │     └── repository access list  ◄── THIS is the authorization gate
  │
  ├── repo A  (in the list)          repo B  (not in the list)
  │     │                                  └── invisible to SonarQube Cloud
  │     │
  │     │ (2) push / PR fires GitHub Actions
  │     ▼
  │   runner (GitHub-hosted)
  │     │  sonarqube-scan-action
  │     │  SONAR_TOKEN + SONAR_HOST_URL=https://sonarcloud.io
  │     ▼
  │   ══════════ outbound HTTPS ══════════►  SonarQube Cloud
  │                                            │  analysis, quality gate
  │     ◄──── PR check + inline comments ──────┘  (posted back via the App)
```

Three things to notice:

- **Traffic is outbound only.** GitHub-hosted runners work fine; no VPN, no self-hosted runners, no firewall exception.
- **The GitHub App is doing double duty** — it is both the access-control boundary and the mechanism that writes PR decoration back. There is no second integration to configure.
- **Code leaves our network.** Source is uploaded to SonarSource for analysis. That is the whole reason an approval step exists.

---

## 1. What we have to do — authorizing a repo

**One-time, org level:**

| Step | Where | Notes |
|---|---|---|
| Create the SonarQube Cloud organization | sonarcloud.io | Bind it to the GitHub org. Pick the org key now — it becomes part of every project key. |
| Install the **SonarQube Cloud** GitHub App | GitHub org settings → Applications | Choose **"Only select repositories"**, not "All repositories". This is the control point; "All" gives away the gate. |
| Decide who can approve | us | Restrict who can edit the App installation — GitHub org owners only. |
| Set the org-level `SONAR_TOKEN` | GitHub org secrets, scoped to selected repos | Or per-repo. Org-scoped with a repo allowlist mirrors the App allowlist and is less work. |
| Pick the default quality gate | SonarQube Cloud → Quality Gates | Recommend starting with **Sonar way** on new code only, non-blocking, then tighten. |
| Licensing | SonarQube Cloud billing | Private repos are priced per lines of code across the org. Every repo we authorize adds to the bill — worth a rough LOC estimate before opening the door. |

**Per repo, on request:**

1. Team raises a request (ticket / PR against a repo list — see open questions).
2. We check: no restricted data in the repo, LOC headroom, licence and export review passes.
3. Add the repo to the GitHub App's selected-repositories list.
4. Add the repo to the org secret's allowlist.
5. In SonarQube Cloud, **Analyze new project** → the repo now appears → create it. Project key defaults to `<org-key>_<repo-name>`.
6. Turn **Automatic Analysis off** if the team is using CI (they cannot both run; CI-based analysis is the one that can import coverage).

That is the entire "authorize a repo" story. Steps 3–5 are five minutes and are scriptable against the GitHub and SonarQube Cloud APIs once the approval decision is made.

---

## 2. What the user team has to do

Once authorized, the team owns three files-worth of work.

**a) `sonar-project.properties` at the repo root** (skip for Maven/Gradle — the build plugin supplies these):

```properties
sonar.projectKey=<org-key>_<repo-name>
sonar.organization=<org-key>
sonar.sources=src
sonar.tests=tests
sonar.exclusions=**/vendor/**,**/node_modules/**,.venv/**,**/*.generated.*
```

The file must be named exactly `sonar-project.properties` and sit in the base
directory. Any other name is ignored silently — the scan still runs, with no
org key and default scope, which is a confusing failure to debug.

**Make `sonar.exclusions` a required field in the team-facing template, not an
optional one.** Vendored dependency trees — `node_modules`, `.venv`, `vendor` —
are the default failure mode of a self-serve rollout. Cloud is priced on lines
of code, so an unexcluded dependency tree inflates the invoice and buries the
team's real issues under third-party noise on their first run. That first run
is the one that decides whether they keep using it.

**b) A workflow that calls the shared one:**

```yaml
name: sonar
on:
  push:
    branches: [main]
  pull_request:

jobs:
  scan:
    uses: <our-org>/.github/.github/workflows/sonar-scan.yml@v1
    with:
      environment: cloud       # or: onprem
    secrets: inherit
```

**c) Produce a coverage report before the scan**, and point Sonar at it. This is the step teams actually get wrong. Coverage is not computed by Sonar — it is imported. Language-dependent: `sonar.python.coverage.reportPaths`, `sonar.javascript.lcov.reportPaths`, `sonar.coverage.jacoco.xmlReportPaths`, and so on.

Then: open a PR, see the Sonar check and inline comments, fix what the gate flags.

**What they do *not* have to do:** create the project, manage a token, choose a scanner version, know the host URL, or configure PR decoration.

---

## The same scenario on-prem (`https://<localurl>`)

The scan command is identical. The surroundings are not.

```
GitHub org                                    our network
  │                                             │
  ├── repo A ── GitHub Actions                   │
  │               │                              │
  │               ▼                              │
  │         self-hosted runner  ═══════════►  SonarQube Server
  │         (inside the network)                 │  at <localurl>
  │                                              │
  │     ◄─── PR decoration ──── GitHub App ──────┘  (server calls out to
  │                                                  github.com API)
```

**Deltas that matter:**

| | SonarQube Cloud | On-prem Server (`<localurl>`) |
|---|---|---|
| Repo authorization | GitHub App selected-repos list | None needed — anyone with a token and network reach can push a project. Access control is inside Sonar, after the fact. |
| Network path | Outbound HTTPS from GitHub-hosted runners | Runner must reach `<localurl>`. Self-hosted runners, or expose the server / allowlist GitHub's ranges. **The main integration cost.** |
| Project creation | Import from GitHub, App-gated | Create manually or via API; project key is ours to choose |
| PR decoration | Free with the App | Requires a separate GitHub App configured in Sonar (App ID, private key, client secret) **and** the server able to reach `api.github.com`. Also a paid-edition feature — check our licence tier. |
| `sonar.organization` | Required | Not used |
| Token | Org secret from SonarQube Cloud | Global or project analysis token from `<localurl>` |
| Upgrades, DB, backups | SonarSource | Us |
| Code leaves the network | Yes | No |

The honest summary: on-prem is harder to *plumb* and easier to *approve*. Cloud is the reverse.

---

## Is there a shared action? Yes.

Put one reusable workflow in the org's `.github` repo. Everything that differs between environments is a variable.

Pin action versions deliberately: this is the file every team inherits, so a stale pin propagates org-wide. Verify the current major before circulating (`sonarqube-scan-action` was v8.2.1 as of September 2026).

```yaml
# .github/workflows/sonar-scan.yml
name: sonar-scan
on:
  workflow_call:
    inputs:
      environment:
        type: string
        default: cloud          # 'cloud' | 'onprem'
      runs-on:
        type: string
        default: ''             # override for self-hosted
      args:
        type: string
        default: ''

jobs:
  scan:
    runs-on: ${{ inputs.runs-on != '' && inputs.runs-on || (inputs.environment == 'onprem' && 'self-hosted' || 'ubuntu-latest') }}
    environment: sonar-${{ inputs.environment }}   # supplies SONAR_HOST_URL + SONAR_TOKEN
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0        # required: blame data for new-code detection

      - uses: SonarSource/sonarqube-scan-action@v8
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          SONAR_HOST_URL: ${{ vars.SONAR_HOST_URL }}
        with:
          args: ${{ inputs.args }}

      - uses: SonarSource/sonarqube-quality-gate-action@v1
        timeout-minutes: 5
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          SONAR_HOST_URL: ${{ vars.SONAR_HOST_URL }}
```

Two GitHub **Environments**, `sonar-cloud` and `sonar-onprem`, each carrying its own `SONAR_HOST_URL` variable and `SONAR_TOKEN` secret. Switching a repo between backends is a one-word change in the caller. Environments also give us a native approval gate if we want one on the cloud side.

**The one thing that is not shared:** `sonar.organization` in `sonar-project.properties`. It is required by Cloud and meaningless to the Server. Options, in order of preference:

1. Leave it in the properties file. The Server logs an unknown-property warning and carries on. Simplest, and lets a repo scan against both.
2. Pass it as `-Dsonar.organization=...` from the shared workflow only when `environment == 'cloud'`. Cleaner, slightly more workflow logic.

Set `SONAR_HOST_URL` explicitly for **both** environments rather than relying on the action's default — it makes the two paths symmetric and the logs unambiguous. One caveat: `SONAR_HOST_URL` is strictly required only for self-hosted Server. On Cloud the instance is selected by `sonar.region` (unset → `sonarcloud.io`, `us` → `sonarqube.us`). So if we do set it centrally, the `sonar-cloud` Environment **must** actually define the variable — an undefined `vars.SONAR_HOST_URL` expands to an empty string and passes an empty host to the scanner rather than falling back to the default. Symmetry is worth having, but only if both Environments are populated before the first repo onboards.

Also note: `sonarqube-scan-action` is the generic scanner. For Maven, Gradle, .NET and C/C++ the team uses the build-specific scanner instead, so the shared workflow needs sibling variants (`sonar-scan-maven.yml`, etc.) rather than one workflow for everything. Same environment/secret pattern, different scan step.

---

## Open questions

- **Which repos are eligible for cloud at all?** We need a written rule, not case-by-case judgement. Suggested starting line: no repo containing customer data fixtures, credentials-adjacent code, or anything under an export-control or contractual on-prem obligation.
- **Who approves?** Security, the repo owner, or both. And is it a ticket or a PR against a checked-in allowlist? A PR gives us the audit trail for free.
- **Do we run both, or migrate?** Running both is defensible during a pilot and expensive as a permanent state — two quality gate definitions, two sets of rules, two dashboards, and no single view of org-wide debt. Pick an end state before onboarding the second team.
- **Cost ceiling.** Cloud is priced on total private LOC. Need an estimate across candidate repos before we agree to an open onboarding process.
- **On-prem licence tier.** PR decoration and branch analysis are not in Community edition. Confirm what `<localurl>` is licensed for, because it changes the on-prem comparison materially.
- **Quality gate policy.** Blocking or advisory at first? Recommend advisory for one sprint per team, then blocking on new code only.

---

## Suggested sequence

1. Write the eligibility rule and the approval path. Nothing else starts until this exists.
2. Create the SonarQube Cloud org, install the App with **zero** repos selected.
3. Build the shared reusable workflow + the two GitHub Environments.
4. Pilot: one low-risk repo on cloud, one on-prem, using the same caller workflow with different `environment:` values. This is the real test of the shared-action claim.
5. Write the team-facing page: the ten-line caller workflow, the properties file, and the coverage-report step.
6. Decide blocking-vs-advisory, then open onboarding.

---

*Replace `<localurl>`, `<org-key>` and `<our-org>` before circulating.*
