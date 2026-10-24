package org.batfish.simulation;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.annotation.Nullable;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.DataPlane;
import org.batfish.datamodel.FibEntry;
import org.batfish.datamodel.FibForward;
import org.batfish.datamodel.FibNextVrf;
import org.batfish.datamodel.FibNullRoute;
import org.batfish.datamodel.Flow;
import org.batfish.datamodel.Interface;
import org.batfish.datamodel.Ip;
import org.batfish.datamodel.IpProtocol;
import org.batfish.datamodel.IpSpace;
import org.batfish.simulation.EffectiveFibResult.Action;
import org.batfish.simulation.EffectiveFibResult.Entry;

/** Expands local FIB actions and ordered interface ACLs over exact IPv4 address regions. */
public final class EffectiveFibBuilder {
  private static final long MAX_ENTRIES = 5_000_000;
  private final ConfigurationSourceIndex _sources;

  public EffectiveFibBuilder(ConfigurationSourceIndex sources) {
    _sources = sources;
  }

  public EffectiveFibResult build(Map<String, Configuration> configurations, DataPlane dataPlane) {
    List<Entry> permitted = new ArrayList<>();
    List<Entry> denied = new ArrayList<>();
    dataPlane
        .getFibs()
        .forEach(
            (node, vrfs) ->
                vrfs.forEach(
                    (vrf, fib) -> {
                      Configuration configuration = configurations.get(node);
                      Ipv4Partition partition = new Ipv4Partition(configuration);
                      fib.allEntries()
                          .forEach(
                              e -> {
                                partition.destination(e.getTopLevelRoute().getNetwork());
                                if (e.getAction() instanceof FibNextVrf) {
                                  throw new UnsupportedOperationException(
                                      "Effective FIB does not yet expand next-VRF actions: "
                                          + node
                                          + "/"
                                          + vrf);
                                }
                              });
                      Map<String, IpSpace> accepts =
                          dataPlane.getForwardingAnalysis().getAcceptsIps().get(node).get(vrf);
                      accepts.values().forEach(partition::destination);
                      List<Interface> ingresses = new ArrayList<>();
                      configuration
                          .getActiveInterfaces(vrf)
                          .values()
                          .forEach(
                              iface -> {
                                validate(iface);
                                partition.acl(iface.getIncomingFilter());
                                partition.acl(iface.getPostTransformationIncomingFilter());
                                partition.acl(iface.getPreTransformationOutgoingFilter());
                                partition.acl(iface.getOutgoingFilter());
                                partition.acl(iface.getOutgoingOriginalFlowFilter());
                                ingresses.add(iface);
                              });
                      ingresses.add(null);
                      Long[] src = partition.sources();
                      Long[] dst = partition.destinations();
                      long cells = (long) (src.length - 1) * (dst.length - 1) * ingresses.size();
                      if (cells + permitted.size() + denied.size() > MAX_ENTRIES) {
                        throw new IllegalArgumentException(
                            "Effective FIB exceeds cell budget for "
                                + node
                                + "/"
                                + vrf
                                + ": "
                                + cells);
                      }
                      for (Interface ingress : ingresses) {
                        String input = ingress == null ? null : ingress.getName();
                        for (int s = 0; s < src.length - 1; s++) {
                          for (int d = 0; d < dst.length - 1; d++) {
                            Flow.Builder builder =
                                Flow.builder()
                                    .setIngressNode(node)
                                    .setSrcIp(Ip.create(src[s]))
                                    .setDstIp(Ip.create(dst[d]))
                                    .setIpProtocol(IpProtocol.TCP)
                                    .setSrcPort(0)
                                    .setDstPort(0);
                            if (input == null) {
                              builder.setIngressVrf(vrf);
                            } else {
                              builder.setIngressInterface(input);
                            }
                            Flow flow = builder.build();
                            List<ConfigurationReference> incoming = new ArrayList<>();
                            AclReplay replay =
                                new AclReplay(configuration, _sources, flow, input, incoming);
                            if (ingress != null
                                && (!replay.permit(ingress.getIncomingFilter(), input + ":in")
                                    || !replay.permit(
                                        ingress.getPostTransformationIncomingFilter(),
                                        input + ":post-in"))) {
                              denied.add(
                                  entry(
                                      node,
                                      vrf,
                                      input,
                                      src,
                                      dst,
                                      s,
                                      d,
                                      Action.DENIED_IN,
                                      null,
                                      incoming));
                              continue;
                            }
                            if (accepts.values().stream()
                                .anyMatch(
                                    space ->
                                        space.containsIp(
                                            flow.getDstIp(), configuration.getIpSpaces()))) {
                              permitted.add(
                                  entry(
                                      node,
                                      vrf,
                                      input,
                                      src,
                                      dst,
                                      s,
                                      d,
                                      Action.ACCEPT,
                                      null,
                                      incoming));
                              continue;
                            }
                            Set<FibEntry> entries = fib.get(flow.getDstIp());
                            if (entries.isEmpty()) {
                              permitted.add(
                                  entry(
                                      node,
                                      vrf,
                                      input,
                                      src,
                                      dst,
                                      s,
                                      d,
                                      Action.NO_ROUTE,
                                      null,
                                      incoming));
                            }
                            for (FibEntry fibEntry : entries) {
                              List<ConfigurationReference> references = new ArrayList<>(incoming);
                              Action action;
                              if (fibEntry.getAction() instanceof FibNullRoute) {
                                action = Action.NULL_ROUTE;
                              } else if (fibEntry.getAction() instanceof FibForward) {
                                String output =
                                    ((FibForward) fibEntry.getAction()).getInterfaceName();
                                Interface egress = configuration.getAllInterfaces().get(output);
                                AclReplay outgoing =
                                    new AclReplay(configuration, _sources, flow, input, references);
                                action =
                                    outgoing.permit(
                                                egress.getPreTransformationOutgoingFilter(),
                                                output + ":pre-out")
                                            && outgoing.permit(
                                                egress.getOutgoingFilter(), output + ":out")
                                            && outgoing.permit(
                                                egress.getOutgoingOriginalFlowFilter(),
                                                output + ":original-out")
                                        ? Action.FORWARD
                                        : Action.DENIED_OUT;
                              } else {
                                throw new UnsupportedOperationException(
                                    "Unsupported FIB action: " + fibEntry.getAction());
                              }
                              (action == Action.DENIED_OUT ? denied : permitted)
                                  .add(
                                      entry(
                                          node,
                                          vrf,
                                          input,
                                          src,
                                          dst,
                                          s,
                                          d,
                                          action,
                                          fibEntry,
                                          references));
                            }
                            if ((long) permitted.size() + denied.size() > MAX_ENTRIES) {
                              throw new IllegalArgumentException(
                                  "Effective FIB exceeds entry budget: " + MAX_ENTRIES);
                            }
                          }
                        }
                      }
                    }));
    return new EffectiveFibResult(permitted, denied);
  }

  private static void validate(Interface iface) {
    if (iface.getIncomingTransformation() != null
        || iface.getOutgoingTransformation() != null
        || iface.getRoutingPolicyName() != null
        || iface.getFirewallSessionInterfaceInfo() != null
        || iface.getInboundFilter() != null) {
      throw new UnsupportedOperationException(
          "Effective FIB requires stateless, untransformed forwarding: " + iface.getName());
    }
  }

  private static Entry entry(
      String node,
      String vrf,
      @Nullable String ingress,
      Long[] sources,
      Long[] destinations,
      int s,
      int d,
      Action action,
      @Nullable FibEntry fibEntry,
      List<ConfigurationReference> references) {
    return new Entry(
        node,
        vrf,
        ingress,
        sources[s],
        sources[s + 1] - 1,
        destinations[d],
        destinations[d + 1] - 1,
        action,
        fibEntry,
        references);
  }
}
