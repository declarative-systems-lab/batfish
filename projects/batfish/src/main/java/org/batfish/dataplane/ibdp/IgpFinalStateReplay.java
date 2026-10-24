package org.batfish.dataplane.ibdp;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.batfish.datamodel.AbstractRoute;
import org.batfish.datamodel.Interface;
import org.batfish.datamodel.IsisRoute;
import org.batfish.datamodel.OspfExternalType1Route;
import org.batfish.datamodel.OspfExternalType2Route;
import org.batfish.datamodel.OspfIntraAreaRoute;
import org.batfish.datamodel.OspfRoute;
import org.batfish.datamodel.RoutingProtocol;
import org.batfish.datamodel.isis.IsisEdge;
import org.batfish.datamodel.isis.IsisInterfaceLevelSettings;
import org.batfish.datamodel.isis.IsisInterfaceMode;
import org.batfish.datamodel.isis.IsisLevel;
import org.batfish.datamodel.isis.IsisProcess;
import org.batfish.datamodel.ospf.OspfArea;
import org.batfish.datamodel.ospf.OspfNeighborConfigId;
import org.batfish.datamodel.ospf.OspfSessionProperties;
import org.batfish.dataplane.protocols.IsisProtocolHelper;
import org.batfish.dataplane.rib.RibDelta;
import org.batfish.simulation.ConfigurationReference;
import org.batfish.simulation.ConfigurationSourceIndex;
import org.batfish.simulation.PolicyReplay;

/** Read-only neighbor polling for single-area OSPF and IS-IS. */
final class IgpFinalStateReplay {
  @FunctionalInterface
  interface Recorder {
    void record(VirtualRouter router, AbstractRoute route, List<ConfigurationReference> references);
  }

  private final ConfigurationSourceIndex _sources;
  private final Recorder _recorder;
  private final IgpPolicyReplay _policies;

  IgpFinalStateReplay(
      ConfigurationSourceIndex sources,
      Recorder recorder,
      Map<String, PolicyReplay> policies,
      IgpPolicyReplay.BlockedRecorder blocked) {
    _sources = sources;
    _recorder = recorder;
    _policies = new IgpPolicyReplay(policies, recorder, blocked);
  }

  void collect(IbdpResult result) {
    result
        .getNodes()
        .values()
        .forEach(node -> node.getVirtualRouters().forEach(_policies::collect));
    result
        .getNodes()
        .values()
        .forEach(
            node ->
                node.getVirtualRouters()
                    .forEach(
                        vr ->
                            vr.getConfiguration()
                                .getVrfs()
                                .get(vr.getName())
                                .getOspfProcesses()
                                .values()
                                .forEach(
                                    process -> {
                                      if (process.getAreas().size() > 1) {
                                        throw new UnsupportedOperationException(
                                            "Alternative-route collection currently supports"
                                                + " single-area OSPF: "
                                                + vr.getHostname());
                                      }
                                    })));
    result
        ._topologies
        .getOspfTopology()
        .edges()
        .forEach(
            edge -> {
              OspfNeighborConfigId from = edge.getTail();
              OspfNeighborConfigId to = edge.getHead();
              VirtualRouter sender =
                  result
                      .getNodes()
                      .get(from.getHostname())
                      .getVirtualRouterOrThrow(from.getVrfName());
              VirtualRouter receiver =
                  result.getNodes().get(to.getHostname()).getVirtualRouterOrThrow(to.getVrfName());
              OspfRoutingProcess source = sender.getOspfProcesses().get(from.getProcName());
              OspfRoutingProcess target = receiver.getOspfProcesses().get(to.getProcName());
              OspfSessionProperties session =
                  result._topologies.getOspfTopology().getSession(edge).get();
              OspfArea area =
                  sender
                      .getConfiguration()
                      .getVrfs()
                      .get(sender.getName())
                      .getOspfProcesses()
                      .get(from.getProcName())
                      .getAreas()
                      .get(session.getArea());
              long cost = target.getIncrementalCost(to.getInterfaceName(), false);
              List<ConfigurationReference> refs = new ArrayList<>();
              refs.add(
                  _sources.reference(
                      to.getHostname(),
                      "OSPF",
                      to.getProcName()
                          + ":"
                          + to.getInterfaceName()
                          + ":area="
                          + session.getArea()
                          + ":cost="
                          + cost));
              refs.add(_sources.reference(from.getHostname(), "SESSION", from + "->" + to));
              for (OspfRoute route : source.getProtocolRoutes()) {
                List<ConfigurationReference> routeRefs = new ArrayList<>(refs);
                routeRefs.addAll(_policies.origin(sender, route));
                if (route instanceof OspfIntraAreaRoute) {
                  if (route.getArea() != session.getArea()) {
                    continue;
                  }
                  OspfIntraAreaRoute advertised =
                      ((OspfIntraAreaRoute) route)
                          .toBuilder().setNextHopIp(session.getIpLink().getIp1()).build();
                  OspfIntraAreaRoute.Builder imported =
                      target.transformIntraAreaRouteOnImport(advertised, cost);
                  _policies.importOspf(
                      receiver, sender, to.getInterfaceName(), imported, routeRefs);
                } else if (route instanceof OspfExternalType1Route) {
                  RibDelta<OspfExternalType1Route> delta =
                      RibDelta.<OspfExternalType1Route>builder()
                          .add((OspfExternalType1Route) route)
                          .build();
                  source
                      .transformType1RoutesOnExport(
                          source.filterExternalRoutesOnExport(delta, area), area)
                      .forEach(
                          advertisement -> {
                            OspfExternalType1Route.Builder imported =
                                target.transformType1RouteOnImport(
                                    advertisement.getRoute(), session.getIpLink().getIp1(), cost);
                            _policies.importOspf(
                                receiver, sender, to.getInterfaceName(), imported, routeRefs);
                          });
                } else if (route instanceof OspfExternalType2Route) {
                  RibDelta<OspfExternalType2Route> delta =
                      RibDelta.<OspfExternalType2Route>builder()
                          .add((OspfExternalType2Route) route)
                          .build();
                  OspfRoutingProcess.transformType2RoutesOnExport(
                          source.filterExternalRoutesOnExport(delta, area), area)
                      .forEach(
                          advertisement -> {
                            OspfExternalType2Route.Builder imported =
                                target.transformType2RouteOnImport(
                                    advertisement.getRoute(), session.getIpLink().getIp1(), cost);
                            _policies.importOspf(
                                receiver, sender, to.getInterfaceName(), imported, routeRefs);
                          });
                }
              }
            });
    result._topologies.getIsisTopology().getNetwork().edges().forEach(edge -> isis(result, edge));
  }

  private void isis(IbdpResult result, IsisEdge edge) {
    Node sourceNode = result.getNodes().get(edge.getNode1().getNode());
    Node targetNode = result.getNodes().get(edge.getNode2().getNode());
    Interface out =
        sourceNode.getConfiguration().getAllInterfaces().get(edge.getNode1().getInterfaceName());
    Interface in =
        targetNode.getConfiguration().getAllInterfaces().get(edge.getNode2().getInterfaceName());
    VirtualRouter source = sourceNode.getVirtualRouterOrThrow(out.getVrfName());
    VirtualRouter target = targetNode.getVirtualRouterOrThrow(in.getVrfName());
    IsisProcess process =
        source.getConfiguration().getVrfs().get(source.getName()).getIsisProcess();
    Set<IsisRoute> routes = new LinkedHashSet<>(source._isisL1Rib.getTypedRoutes());
    routes.addAll(source._isisL2Rib.getTypedRoutes());
    if (process.getLevel1() != null && process.getLevel2() != null && !process.getOverload()) {
      source
          ._isisL1Rib
          .getTypedRoutes()
          .forEach(
              route -> {
                RoutingProtocol protocol =
                    route.getProtocol() == RoutingProtocol.ISIS_L1
                        ? RoutingProtocol.ISIS_L2
                        : RoutingProtocol.ISIS_EL2;
                IsisProtocolHelper.convertRouteLevel1ToLevel2(
                        route,
                        protocol,
                        protocol.getDefaultAdministrativeCost(
                            source.getConfiguration().getConfigurationFormat()))
                    .ifPresent(routes::add);
              });
    }
    for (IsisRoute route : routes) {
      IsisLevel level = route.getLevel();
      IsisInterfaceLevelSettings outgoing =
          level == IsisLevel.LEVEL_1 ? out.getIsis().getLevel1() : out.getIsis().getLevel2();
      IsisInterfaceLevelSettings incoming =
          level == IsisLevel.LEVEL_1 ? in.getIsis().getLevel1() : in.getIsis().getLevel2();
      if (!edge.getCircuitType().includes(level)
          || incoming == null
          || outgoing == null
          || incoming.getMode() != IsisInterfaceMode.ACTIVE
          || outgoing.getMode() != IsisInterfaceMode.ACTIVE) {
        continue;
      }
      long cost = incoming.getCost() == null ? IsisRoute.DEFAULT_METRIC : incoming.getCost();
      IsisRoute imported =
          route.toBuilder()
              .setOverload(process.getOverload() || route.getOverload())
              .setAdmin(
                  route
                      .getProtocol()
                      .getDefaultAdministrativeCost(
                          target.getConfiguration().getConfigurationFormat()))
              .setMetric(route.getMetric() + cost)
              .setNextHopIp(out.getConcreteAddress().getIp())
              .setNonRouting(false)
              .build();
      List<ConfigurationReference> refs = new ArrayList<>();
      refs.add(
          _sources.reference(
              target.getHostname(), "ISIS", in.getName() + ":" + level + ":cost=" + cost));
      refs.add(_sources.reference(source.getHostname(), "SESSION", edge.toString()));
      refs.addAll(_policies.origin(source, route));
      _recorder.record(target, imported, refs);
    }
  }
}
