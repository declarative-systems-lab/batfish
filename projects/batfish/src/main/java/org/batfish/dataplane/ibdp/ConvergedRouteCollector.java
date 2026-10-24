package org.batfish.dataplane.ibdp;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.batfish.datamodel.AbstractRoute;
import org.batfish.datamodel.AnnotatedRoute;
import org.batfish.datamodel.BgpPeerConfig;
import org.batfish.datamodel.BgpPeerConfigId;
import org.batfish.datamodel.BgpProcess;
import org.batfish.datamodel.BgpRoute;
import org.batfish.datamodel.BgpSessionProperties;
import org.batfish.datamodel.BgpTieBreaker;
import org.batfish.datamodel.Bgpv4Route;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.GeneratedRoute;
import org.batfish.datamodel.Interface;
import org.batfish.datamodel.MultipathEquivalentAsPathMatchMode;
import org.batfish.datamodel.NetworkConfigurations;
import org.batfish.datamodel.Route;
import org.batfish.datamodel.RoutingProtocol;
import org.batfish.datamodel.bgp.AddressFamily;
import org.batfish.datamodel.route.nh.NextHopDiscard;
import org.batfish.datamodel.route.nh.NextHopInterface;
import org.batfish.datamodel.route.nh.NextHopIp;
import org.batfish.datamodel.route.nh.NextHopVrf;
import org.batfish.datamodel.routing_policy.Environment.Direction;
import org.batfish.dataplane.protocols.BgpProtocolHelper;
import org.batfish.dataplane.protocols.GeneratedRouteHelper;
import org.batfish.dataplane.protocols.StaticRouteHelper;
import org.batfish.dataplane.rib.Bgpv4Rib;
import org.batfish.simulation.ConfigurationReference;
import org.batfish.simulation.ConfigurationSourceIndex;
import org.batfish.simulation.PolicyReplay;
import org.batfish.simulation.RibResult;

/**
 * Polls final neighbor advertisements once, without updating live RIBs or consuming protocol
 * deltas.
 */
final class ConvergedRouteCollector {
  private final ConfigurationSourceIndex _sources;
  private final Map<VirtualRouter, Map<AbstractRoute, List<ConfigurationReference>>> _routes =
      new LinkedHashMap<>();
  private final Map<VirtualRouter, Set<AbstractRoute>> _best = new HashMap<>();
  private final List<RibResult.Entry> _blocked = new ArrayList<>();
  private final Map<String, PolicyReplay> _policies = new HashMap<>();

  ConvergedRouteCollector(ConfigurationSourceIndex sources) {
    _sources = sources;
  }

  RibResult collect(IbdpResult result) {
    Map<String, Configuration> configurations = new HashMap<>();
    result
        .getNodes()
        .forEach(
            (name, node) -> {
              configurations.put(name, node.getConfiguration());
              _policies.put(name, new PolicyReplay(node.getConfiguration(), _sources));
              node.getVirtualRouters()
                  .forEach(
                      vr -> {
                        Set<AbstractRoute> selected = new LinkedHashSet<>();
                        selected.addAll(vr.getAllBgpRoutes());
                        if (vr._bgpRoutingProcess != null) {
                          selected.addAll(vr._bgpRoutingProcess._ebgpv4Rib.getTypedRoutes());
                          selected.addAll(vr._bgpRoutingProcess._ibgpv4Rib.getTypedRoutes());
                        }
                        vr.getOspfRoutes().stream()
                            .filter(route -> !route.getNonRouting())
                            .forEach(selected::add);
                        vr.getOspfProcesses()
                            .values()
                            .forEach(
                                process ->
                                    process.getProtocolRoutes().stream()
                                        .filter(route -> !route.getNonRouting())
                                        .forEach(selected::add));
                        vr._isisL1Rib.getTypedRoutes().stream()
                            .filter(route -> !route.getNonRouting())
                            .forEach(selected::add);
                        vr._isisL2Rib.getTypedRoutes().stream()
                            .filter(route -> !route.getNonRouting())
                            .forEach(selected::add);
                        _best.put(vr, selected);
                        _routes.put(vr, new LinkedHashMap<>());
                        selected.forEach(route -> record(vr, route, localReferences(vr, route)));
                        vr.getMainRib()
                            .getTypedRoutes()
                            .forEach(
                                route ->
                                    record(
                                        vr,
                                        route.getRoute(),
                                        localReferences(vr, route.getRoute())));
                        collectStatic(vr);
                      });
            });
    NetworkConfigurations nc = NetworkConfigurations.of(configurations);
    result
        ._topologies
        .getBgpTopology()
        .getGraph()
        .edges()
        .forEach(
            edge -> {
              BgpPeerConfigId senderId = edge.source();
              BgpPeerConfigId receiverId = edge.target();
              BgpPeerConfig sender = nc.getBgpPeerConfig(senderId);
              BgpPeerConfig receiver = nc.getBgpPeerConfig(receiverId);
              if (sender.getIpv4UnicastAddressFamily() == null
                  || receiver.getIpv4UnicastAddressFamily() == null) {
                return;
              }
              VirtualRouter source =
                  result
                      .getNodes()
                      .get(senderId.getHostname())
                      .getVirtualRouterOrThrow(senderId.getVrfName());
              VirtualRouter target =
                  result
                      .getNodes()
                      .get(receiverId.getHostname())
                      .getVirtualRouterOrThrow(receiverId.getVrfName());
              BgpSessionProperties incoming =
                  result
                      ._topologies
                      .getBgpTopology()
                      .getGraph()
                      .edgeValue(receiverId, senderId)
                      .get();
              BgpSessionProperties outgoing =
                  result
                      ._topologies
                      .getBgpTopology()
                      .getGraph()
                      .edgeValue(senderId, receiverId)
                      .get();
              replayBgp(source, target, senderId, receiverId, sender, receiver, incoming, outgoing);
            });
    new IgpFinalStateReplay(_sources, this::record, _policies, this::blocked).collect(result);
    List<RibResult.Entry> main = new ArrayList<>();
    List<RibResult.Entry> alternatives = new ArrayList<>();
    _routes.forEach(
        (vr, routes) -> {
          Set<AbstractRoute> installed = new LinkedHashSet<>();
          vr.getMainRib().getTypedRoutes().forEach(r -> installed.add(r.getRoute()));
          routes.forEach(
              (route, references) -> {
                boolean isMain = installed.contains(route);
                (isMain ? main : alternatives)
                    .add(
                        new RibResult.Entry(
                            vr.getHostname(),
                            vr.getName(),
                            route,
                            isMain || _best.get(vr).contains(route),
                            null,
                            null,
                            references));
              });
        });
    return new RibResult(main, alternatives, _blocked);
  }

  private void record(
      VirtualRouter vr, AbstractRoute route, List<ConfigurationReference> references) {
    List<ConfigurationReference> target =
        _routes.get(vr).computeIfAbsent(route, r -> new ArrayList<>());
    for (ConfigurationReference ref : references) {
      if (target.stream()
          .noneMatch(
              r ->
                  r.getNode().equals(ref.getNode())
                      && r.getKind().equals(ref.getKind())
                      && r.getName().equals(ref.getName()))) {
        target.add(ref);
      }
    }
  }

  private List<ConfigurationReference> localReferences(VirtualRouter vr, AbstractRoute route) {
    List<ConfigurationReference> refs = new ArrayList<>();
    String name =
        route.getProtocol() + ":" + route.getNetwork() + ":" + route.getNextHopInterface();
    refs.add(_sources.reference(vr.getHostname(), "ROUTE", name));
    if (route.getNextHop() instanceof NextHopInterface) {
      String iface = ((NextHopInterface) route.getNextHop()).getInterfaceName();
      refs.add(
          _sources.resolve(
              vr.getHostname(), "INTERFACE", iface, text -> text.equals("interface " + iface)));
    }
    return refs;
  }

  private void collectStatic(VirtualRouter vr) {
    vr.getConfiguration()
        .getVrfs()
        .get(vr.getName())
        .getStaticRoutes()
        .forEach(
            route -> {
              boolean active =
                  route.getNextHop() instanceof NextHopDiscard
                      || route.getNextHop() instanceof NextHopVrf;
              if (route.getNextHop() instanceof NextHopInterface) {
                Interface iface =
                    vr.getConfiguration().getAllInterfaces().get(route.getNextHopInterface());
                active = iface != null && iface.getActive();
              } else if (route.getNextHop() instanceof NextHopIp) {
                active = StaticRouteHelper.shouldActivateNextHopIpRoute(route, vr.getMainRib());
              }
              if (active) {
                _best.get(vr).add(route);
                record(vr, route, localReferences(vr, route));
              }
            });
  }

  private void replayBgp(
      VirtualRouter source,
      VirtualRouter target,
      BgpPeerConfigId senderId,
      BgpPeerConfigId receiverId,
      BgpPeerConfig sender,
      BgpPeerConfig receiver,
      BgpSessionProperties incoming,
      BgpSessionProperties outgoing) {
    BgpProcess sourceProcess =
        source.getConfiguration().getVrfs().get(source.getName()).getBgpProcess();
    BgpProcess targetProcess =
        target.getConfiguration().getVrfs().get(target.getName()).getBgpProcess();
    Set<AbstractRoute> candidates = new LinkedHashSet<>();
    source
        .getMainRib()
        .getTypedRoutes()
        .forEach(
            r -> {
              if (!(r.getRoute() instanceof BgpRoute)) {
                candidates.add(r.getRoute());
              }
            });
    source
        .getBgpRoutes()
        .forEach(
            r -> {
              if (incoming.getAdvertiseInactive()
                  || incoming.getAdditionalPaths()
                  || source
                      .getMainRib()
                      .containsRoute(new AnnotatedRoute<AbstractRoute>(r, source.getName()))) {
                candidates.add(r);
              }
            });
    if (incoming.getAdvertiseExternal()) {
      candidates.addAll(source._bgpRoutingProcess._ebgpv4Rib.getTypedRoutes());
    }
    sender
        .getGeneratedRoutes()
        .forEach(
            route -> {
              Configuration config = source.getConfiguration();
              GeneratedRoute.Builder activated =
                  GeneratedRouteHelper.activateGeneratedRoute(
                      route,
                      config.getRoutingPolicies().get(route.getGenerationPolicy()),
                      source.getMainRib().getTypedRoutes());
              if (activated != null) {
                candidates.add(
                    BgpProtocolHelper.convertGeneratedRouteToBgp(
                        activated.build(),
                        config.getRoutingPolicies().get(route.getAttributePolicy()),
                        sourceProcess.getRouterId(),
                        incoming.getHeadIp(),
                        false));
              }
            });
    for (AbstractRoute candidate : candidates) {
      List<ConfigurationReference> refs = new ArrayList<>();
      refs.add(_sources.reference(source.getHostname(), "SESSION", senderId + "->" + receiverId));
      Bgpv4Route.Builder exported;
      if (candidate instanceof Bgpv4Route) {
        exported =
            BgpProtocolHelper.transformBgpRoutePreExport(
                sender,
                receiver,
                incoming,
                sourceProcess,
                targetProcess,
                (Bgpv4Route) candidate,
                AddressFamily.Type.IPV4_UNICAST);
      } else if (candidate instanceof GeneratedRoute) {
        GeneratedRoute generated = (GeneratedRoute) candidate;
        exported =
            BgpProtocolHelper.convertGeneratedRouteToBgp(
                generated,
                source.getConfiguration().getRoutingPolicies().get(generated.getAttributePolicy()),
                sourceProcess.getRouterId(),
                incoming.getHeadIp(),
                false)
                .toBuilder();
      } else {
        RoutingProtocol protocol = incoming.isEbgp() ? RoutingProtocol.BGP : RoutingProtocol.IBGP;
        exported =
            BgpProtocolHelper.convertNonBgpRouteToBgpRoute(
                new AnnotatedRoute<>(candidate, source.getName()),
                sourceProcess.getRouterId(),
                incoming.getHeadIp(),
                sourceProcess.getAdminCost(protocol),
                protocol);
      }
      if (exported == null) {
        continue;
      }
      String exportPolicy = sender.getIpv4UnicastAddressFamily().getExportPolicy();
      if (!_policies
          .get(source.getHostname())
          .process(
              exportPolicy,
              candidate instanceof Bgpv4Route
                  ? candidate
                  : new AnnotatedRoute<>(candidate, source.getName()),
              exported,
              incoming,
              Direction.OUT,
              refs)) {
        blocked(target, candidate, source, "EXPORT", refs);
        continue;
      }
      record(source, candidate, refs);
      BgpProtocolHelper.transformBgpRoutePostExport(
          exported,
          incoming.isEbgp(),
          incoming.getConfedSessionType(),
          incoming.getHeadAs(),
          incoming.getHeadIp(),
          candidate instanceof Bgpv4Route
              ? candidate.getNextHopIp()
              : Route.UNSET_ROUTE_NEXT_HOP_IP);
      Bgpv4Route advertisement = exported.build();
      Bgpv4Route.Builder imported =
          BgpProtocolHelper.transformBgpRouteOnImport(
              advertisement,
              outgoing.getHeadAs(),
              receiver
                  .getIpv4UnicastAddressFamily()
                  .getAddressFamilyCapabilities()
                  .getAllowLocalAsIn(),
              outgoing.isEbgp(),
              targetProcess,
              outgoing.getTailIp(),
              receiverId.getPeerInterface());
      if (imported == null) {
        continue;
      }
      if (!_policies
          .get(target.getHostname())
          .process(
              receiver.getIpv4UnicastAddressFamily().getImportPolicy(),
              advertisement,
              imported,
              outgoing,
              Direction.IN,
              refs)) {
        blocked(target, advertisement, source, "IMPORT", refs);
        continue;
      }
      Bgpv4Route importedRoute = imported.build();
      // Use a scratch RIB to apply protocol admission without changing the converged process.
      Bgpv4Rib admission =
          new Bgpv4Rib(
              target.getMainRib(),
              BgpTieBreaker.ARRIVAL_ORDER,
              1,
              MultipathEquivalentAsPathMatchMode.EXACT_PATH,
              false,
              false);
      if (!admission.mergeRouteGetDelta(importedRoute).isEmpty()) {
        record(target, importedRoute, refs);
      }
    }
  }

  private void blocked(
      VirtualRouter target,
      AbstractRoute route,
      VirtualRouter source,
      String stage,
      List<ConfigurationReference> refs) {
    _blocked.add(
        new RibResult.Entry(
            target.getHostname(),
            target.getName(),
            route,
            false,
            source.getHostname(),
            stage,
            refs));
  }
}
