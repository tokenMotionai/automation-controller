# Bridging Slack and Teams

**Decision memo — 20 August 2026**

We use Slack. Several teams we work with use Microsoft Teams. Today there is no way to send one of them a direct message without leaving the tools we already have open.

---

## Recommendation

**Pilot SlackBridge at $600/year.** It is the cheapest way to find out whether people actually use this.

If the pilot lands and we need enterprise controls, the step up is Conclude at $2,400/yr, or the enterprise tier at $15,000–$50,000/yr. Spending that money first means paying for company-wide rollout before we know anyone wants it.

---

## What we found

**There is no built-in option.** Slack Connect only links Slack to Slack. Microsoft's external access only links Teams to Teams. Nothing from either vendor crosses the gap, so reaching a Teams user from Slack means buying a third-party bridge.

**Every option routes our messages through someone else's servers.** Three of the four host on Google Cloud. All four say they relay messages without keeping them. That claim is the whole compliance question, and right now we have it only from their marketing.

**This market moves under you.** Mio was the best-known Slack–Teams bridge and no longer offers the pairing at all — only Google Chat and Zoom. Vendor stability is a real risk, which is another argument for starting small rather than signing a five-figure annual contract.

---

## The four options

| Tool | Annual cost | DMs | Hosted on | Commitment | Sensible for |
|---|---|---|---|---|---|
| **SlackBridge** | **$600** | Yes | Vendor relay | Monthly | Proving the idea |
| **Conclude** | $2,400+ | Yes | Google Cloud | Annual | One or two teams |
| **SyncRivo** | $15k–$50k | Yes | Google Cloud | Annual | Company-wide |
| **NextPlane OpenHub** | $15k–$50k | Yes | Google Cloud | Annual | Company-wide |

SlackBridge is billed at $49.99/month. Conclude's figure is its entry tier. SyncRivo and NextPlane both scale with org size and are negotiated.

All four support the thing we actually need: a person in Slack starting a direct message with a person in Teams.

**What each says about retention** — all taken from vendor documentation, none independently verified:

- **SlackBridge** — relays in transit only; message history stays in Slack and Teams.
- **Conclude** — does not retain message content.
- **SyncRivo** — does not retain content; cites GDPR compliance.
- **NextPlane** — never saves chat content, media or conversation logs.

---

## The trade-off, in short

**SlackBridge — $600/yr, monthly**
- *For:* Twenty-five times cheaper than the next tier up. Month to month, so a failed pilot costs us $50 and a cancelled subscription.
- *Against:* Smallest and least established vendor. Support terms, uptime commitments and admin controls are unproven.

**Conclude — $2,400+/yr, annual**
- *For:* A middle option. Established product with a broader collaboration suite behind it.
- *Against:* Four times the pilot cost and an annual commitment, for a question we can answer for less.

**SyncRivo & NextPlane — $15,000–$50,000/yr, annual**
- *For:* Built for company-wide deployment, with the compliance and administration story that implies.
- *Against:* Five figures and a procurement cycle spent before we know whether anyone uses the feature.

---

## Before we sign anything

- [ ] **SOC 2 Type II report** — the actual report, not the badge on the website.
- [ ] **Data processing agreement** — turns "we don't store your messages" from a marketing line into a contractual obligation.
- [ ] **Subprocessor list** — who else handles our message data once it leaves the vendor.
- [ ] **An explanation of the price gap** — ask the enterprise vendors what $50,000 buys that $600 does not. If the answer is single sign-on, an uptime guarantee and named support, that is a real difference worth paying for later. If there is no clear answer, that is worth knowing too.

---

## What a pilot takes

**Slack side:** we already have admin access. No blocker.

**Teams side:** installing the app needs tenant approval from Harini, who administers Teams. This is the gate, and it is worth asking early — it is usually slower than the technical setup.

**Scope:** three to five people who genuinely need cross-platform contact, running for one month. Success is simple — did they keep using it, or drift back to email?

---

### One option we considered and set aside

Matterbridge is open source and self-hosted, which would keep every message on our own infrastructure and remove the data residency question entirely. We are not recommending it now because the build and ongoing maintenance cost outweighs the benefit for a first step — but it stays on the table if compliance review rules out the hosted vendors.

---

*Pricing and retention details are drawn from vendor documentation as of August 2026 and should be confirmed in writing before purchase.*
