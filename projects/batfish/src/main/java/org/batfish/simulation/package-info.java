/**
 * Concrete snapshot simulation for route repair and dependency tracking.
 *
 * <pre>{@code
 * try (SnapshotSimulation simulation = SnapshotSimulation.open(snapshotDirectory)) {
 *   RibResult rib = simulation.getRib();
 *   EffectiveFibResult effectiveFib = simulation.getEffectiveFib();
 * }
 * }</pre>
 *
 * <p>The input directory contains {@code configs/} and optional ordinary Batfish snapshot inputs.
 * Batfish computes one converged dataplane in temporary storage. Main RIB entries come directly
 * from that dataplane, including all installed protocols and multipath routes. The additional
 * collection pass polls final BGP/OSPF/IS-IS advertisements and eligible static routes. It never
 * merges candidates into live RIBs, consumes message queues, or broadcasts them. This is a final
 * state polling pass inspired by RPVP, not an implementation of Plankton's exploration algorithm.
 *
 * <p>Alternatives exclude main RIB entries. Policy rejection is recorded separately as EXPORT or
 * IMPORT; core protocol rejection, such as an AS loop, is not mislabeled as policy rejection.
 * Protocol-best means selected by a protocol RIB, which can include multiple paths. Source
 * references identify executed route-map clauses, evaluated prefix/community-list entries, and
 * session identities. OSPF/IS-IS references additionally identify the adjacency, interface,
 * area/level, and metric. References describe local decisions rather than a complete upstream path
 * history. Source file/line locations are best effort for Cisco-style configurations; logical
 * identities remain available when a physical location cannot be resolved.
 *
 * <p>The effective FIB partitions source and destination IPv4 addresses into inclusive intervals on
 * which forwarding and ACL behavior are constant. It preserves separate ECMP branches, resolved
 * next hops, and matching ACL lines, including implicit deny. A null ingress interface denotes
 * device-originated traffic. Permitted entries mean not denied by ACLs: their action can still be
 * NO_ROUTE or NULL_ROUTE. FORWARD is a local forwarding decision, not proof of end-to-end delivery
 * or successful neighbor resolution.
 *
 * <p>The initial candidate collector supports ordinary IPv4 BGP, single-area OSPF, and IS-IS.
 * Additional protocol-specific candidate collection and cross-VRF policy provenance are extension
 * points. Effective FIB expansion supports stateless address-only IPv4 ACLs, including boolean
 * combinations, nested ACLs, and non-contiguous wildcards. Packet-field constraints, NAT, PBR,
 * stateful sessions, and next-VRF actions fail explicitly. Expansion has fixed budgets of 100,000
 * boundaries per address dimension and 5,000,000 result entries; exceeding a budget fails instead
 * of returning a truncated table. No new symbolic reachability or BDD analysis is performed.
 */
package org.batfish.simulation;
