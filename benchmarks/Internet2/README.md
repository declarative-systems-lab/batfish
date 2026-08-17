# Internet2 benchmark

Production-scale Internet2 core configs adapted for Batfish and Minesweeper.
Ten Juniper core routers peer with concrete external Cisco CONNECTOR peers; iBGP
between cores remains disabled.

## Layout

```text
Internet2/
  README.md
  configs/
    chic.cfg … wash.cfg          # 10 core routers (Juniper)
    chic-wiscr.cfg …             # 57 external peers (Cisco IOS)
```

| Role | Files | Count |
|------|-------|------:|
| Core (Juniper) | `{core}.cfg` | 10 |
| External (Cisco) | `{core}-{peer}.cfg` | 57 |
| **Total** | | **67** |

Core hostnames in Batfish: `chic-re1`, `atla-re1`, …, `wash-re1`.

## Core routers

| Core | Config | Batfish hostname |
|------|--------|------------------|
| Chicago | `chic.cfg` | `chic-re1` |
| Atlanta | `atla.cfg` | `atla-re1` |
| Cleveland | `clev.cfg` | `clev-re1` |
| Houston | `hous.cfg` | `hous-re1` |
| Kansas City | `kans.cfg` | `kans-re1` |
| Los Angeles | `losa.cfg` | `losa-re1` |
| New York | `newy32aoa.cfg` | `newy-re1` |
| Salt Lake City | `salt.cfg` | `salt-re1` |
| Seattle | `seat.cfg` | `seat-re1` |
| Washington | `wash.cfg` | `wash-re1` |

**iBGP:** `group INTERNET2` / `INTERNET2-IPv6` blocks are commented out
(`# [DISABLED iBGP]`) on all cores. Inter-core reachability is not modeled via
iBGP in this snapshot.

## External peers (Cisco)

Each external config is a minimal Cisco IOS router that **reuses an existing
production CONNECTOR session** from the original snapshot: same interface
subnet, BGP neighbor IP, and peer AS as on the core. Cores are not given
synthetic `100.64.x/30` stubs; only the external side is modeled.

**Pattern** (see `chic-wiscr.cfg`):

- `hostname` = production peer name (must not start with a digit)
- eBGP to the core on the production /30 or /31
- **10** `network` statements + matching `ip route … Null0`
- Empty export communities (tagging happens on core import policies)

**Per-core external count**

| Core | External configs | Notes |
|------|------------------:|-------|
| chic | 6 | incl. `chic-wiscr.cfg` (WiscRen) |
| atla | 6 | incl. `atla-indiana.cfg` |
| clev | 6 | incl. `clev-psc.cfg`, `clev-psc-pitt.cfg` |
| hous | 6 | |
| kans | 6 | |
| losa | 6 | |
| newy32aoa | 6 | |
| salt | 3 | CONNECTOR peers only (`salt-iron`, `salt-uen`, `salt-globalsummit`) |
| seat | 6 | |
| wash | 6 | |

**Representative production peerings** (one per core; others follow the same
template in `{core}-*.cfg` headers):

| Core | Example file | Peer | Subnet | ext IP | core IP | AS |
|------|--------------|------|--------|--------|---------|-----|
| chic | `chic-wiscr.cfg` | WiscRen | /30 | 205.213.118.5 | 205.213.118.6 | 2381 |
| atla | `atla-indiana.cfg` | Indiana Gigapop | /31 | 149.165.254.20 | 149.165.254.21 | 19782 |
| clev | `clev-psc.cfg` | PSC (3ROX) | /31 | 192.88.115.24 | 192.88.115.25 | 5050 |
| hous | `hous-learn.cfg` | LEARN | /30 | 74.200.187.10 | 74.200.187.9 | 14085 |
| kans | `kans-gpn.cfg` | GPN | /30 | 164.113.255.253 | 164.113.255.254 | 11317 |
| losa | `losa-calren.cfg` | CalREN | /30 | 137.164.26.133 | 137.164.26.134 | 2153 |
| newy | `newy32aoa-geresearch.cfg` | GE Research | /31 | 198.71.46.189 | 198.71.46.188 | 3921 |
| salt | `salt-iron.cfg` | IRON | /31 | 64.57.28.207 | 64.57.28.206 | 46435 |
| seat | `seat-pnwgp.cfg` | PNWGP | /30 | 64.57.28.54 | 64.57.28.53 | 101 |
| wash | `wash-oarnet.cfg` | OARnet | /30 | 192.88.192.137 | 192.88.192.138 | 3112 |

Import policy on each core is whatever the production `-IN` chain already
applies to that neighbor (e.g. `WISCREN-IN` on chic, `INDIANAGIGAPOP-IN` on
atla).

## BGP announcements (10 prefixes)

All external peers originate the **same 10 /24 prefixes**:

| Prefix | Typical import match | Cores |
|--------|----------------------|-------|
| `100.64.10.0/24` | CONNECTOR baseline | all |
| `205.213.200.0/24` | `WISCREN-PARTICIPANT` | chic |
| `74.115.8.0/24` | `WISCREN-SEGP` | chic |
| `128.10.50.0/24` | `INDIANAGIGAPOP-PARTICIPANT` | atla, clev, chic |
| `63.164.11.0/24` | `SOX-PARTICIPANT` | atla |
| `128.2.100.0/24` | `PSC-PARTICIPANT` | clev, wash |
| `128.206.50.0/24` | `GPN-PARTICIPANT` | kans, chic |
| `128.101.10.0/24` | `NORTHERNLIGHTS-PARTICIPANT` | kans, wash, chic |
| `63.193.200.0/24` | `CALREN-PARTICIPANT` | hous, losa, seat |
| `198.48.92.0/24` | `UWSCIENCE-PARTICIPANT` | seat |

On **chic**, the WiscRen session uses
`import [ SANITY-IN SET-PREF WISCREN-IN CONNECTOR-IN ]`. Prefixes that do not
match `WISCREN-PARTICIPANT` / `WISCREN-SEGP` fall through the **sponsored**
term (prefix-list commented out) into `CONNECTOR-IN`.

## Minesweeper reachability

Example in `SmtPropertyTest.java` — one case per prefix, all via the chic
WiscRen peering:

```java
question.setIngressNodeRegex("chic-re1");
question.setFinalNodeRegex("wiscr");
question.setDstIps(Set.of(IpWildcard.parse("100.64.10.0/24"))); // … nine others
```

Uncomment **one** block at a time when running the test. This exercises chic
import + forwarding to external host `wiscr`; it does not validate per-core
`-IN` policies on other POPs.

For a minimal chic + wiscr community-encoding repro, see
[`../Internet2-lite/README.md`](../Internet2-lite/README.md).

## Config hygiene

Production configs were trimmed so Batfish can parse them. Use `clean_config.py`
(where available) for bulk removal; remaining unparseable lines were removed
manually by re-running Batfish until the snapshot loads.

Forwarding equivalence classes that hit `null` are due to static routes for
large aggregates; more-specific routes inside those aggregates behave normally.

### Prefixes without sink

These prefixes appear only at one or two routers as static routes, so there is
no connected route and no sink:

| Prefix | Router | Note |
|--------|--------|------|
| `195.113.222.88/29` | CHIC | CzechLight / VINI |
| `193.251.128.23/32` | CHIC | FranceTelecom mcast MSDP |
| `193.251.128.3/32` | CHIC | FranceTelecom mcast MSDP |
| `192.73.48.23/32` | CHIC | |
| `192.73.48.17/32` | SEAT | |
| `171.67.234.0/24` | HOUS | 100x100 experimental net |
| `162.252.70.128/25` | CHIC | fragment of `162.252.70.0/24` |
| `162.252.70.0/26` | CHIC | fragment of `162.252.70.0/24` |
| `149.165.241.10/32` | CHIC | |
| `134.55.3.3/32` | NEWY | |
| `74.200.179.10/32` | ATLA | |
| `64.57.31.144/28` | NEWY | |
| `64.57.23.240/28` | CHIC | CIC oob; static beats BGP |
| `62.40.122.115/32` | NEWY, WASH | |
| `10.60.0.0/24` | NEWY | |

### Manual policy removals (Minesweeper)

Additional lines were removed because Minesweeper could not handle them:
community matches and `prefix-list-filter` terms whose prefix-lists were empty.

<details>
<summary>Per-router removed lines (incomplete list)</summary>

**KANS** — community: `BLOCK-TO-EXTERNAL`, `[ CONNECTOR-ONLY COMMERCIAL-PEER ]`, `[ FEDNET NONITN ]`

**CLEV** — community: `NLR-TELEPRESENCE`, `BLOCK-TO-EXTERNAL`; empty prefix-lists: `CEN-SPONSORED`, `CEN-SEGP`

**HOUS** — community: `NLR-TELEPRESENCE`, `BLOCK-TO-EXTERNAL`, `[ CONNECTOR-ONLY COMMERCIAL-PEER ]`, `[ ITN NONITN ]`, `[ FEDNET NONITN ]`, `[ FEDNET ITN NONITN ]`; empty prefix-lists: `MISSION-SEGP`, `MISSION-SPONSORED`, `HAWAII-SPONSORED`

**NEWY** — community: `NLR-TELEPRESENCE`, `BLOCK-TO-EXTERNAL`, several `CONNECTOR-ONLY` / `FEDNET` / `ITN-PREPEND*`, `NETPLUS-CLOUD`, `IFTN`; empty prefix-lists: `CEN-SPONSORED`, `CEN-SEGP`, `UPENN-SEGP`, `UPENN-SPONSORED`, `CAAREN-SEGP`

**SEAT** — many `NETPLUS-*` and `BLOCK-TO-*` community terms; empty prefix-lists: `UWSCIENCE-SPONSORED`, `UWSCIENCE-SEGP`, `HAWAII-SPONSORED`

**LOSA** — community: `NLR-TELEPRESENCE`, `BLOCK-TO-EXTERNAL`, `NETPLUS-CLOUD`, `[ CONNECTOR-ONLY COMMERCIAL-PEER ]`, `IFTN`, several `FEDNET` / `ITN-PREPEND*`; empty prefix-lists: `HAWAII-SPONSORED`

</details>
