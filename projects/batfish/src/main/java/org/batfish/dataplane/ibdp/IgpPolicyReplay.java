package org.batfish.dataplane.ibdp;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.batfish.datamodel.AbstractRoute;
import org.batfish.datamodel.AbstractRouteBuilder;
import org.batfish.datamodel.AbstractRouteDecorator;
import org.batfish.datamodel.IsisRoute;
import org.batfish.datamodel.OspfExternalRoute;
import org.batfish.datamodel.OspfExternalType1Route;
import org.batfish.datamodel.OspfExternalType2Route;
import org.batfish.datamodel.isis.IsisProcess;
import org.batfish.datamodel.routing_policy.Environment.Direction;
import org.batfish.datamodel.routing_policy.RoutingPolicy;
import org.batfish.dataplane.protocols.IsisProtocolHelper;
import org.batfish.dataplane.rib.OspfExternalType1Rib;
import org.batfish.dataplane.rib.OspfExternalType2Rib;
import org.batfish.simulation.ConfigurationReference;
import org.batfish.simulation.PolicyReplay;

/** Collects redistribution and OSPF distribute-list decisions against the final main RIB. */
final class IgpPolicyReplay {
  @FunctionalInterface
  interface BlockedRecorder {
    void record(
        VirtualRouter target,
        AbstractRoute route,
        VirtualRouter source,
        String stage,
        List<ConfigurationReference> references);
  }

  private final Map<String, PolicyReplay> _policies;
  private final IgpFinalStateReplay.Recorder _recorder;
  private final BlockedRecorder _blocked;
  private final Map<VirtualRouter, Map<AbstractRoute, List<ConfigurationReference>>> _origins =
      new HashMap<>();

  IgpPolicyReplay(
      Map<String, PolicyReplay> policies,
      IgpFinalStateReplay.Recorder recorder,
      BlockedRecorder blocked) {
    _policies = policies;
    _recorder = recorder;
    _blocked = blocked;
  }

  void collect(VirtualRouter vr) {
    Map<AbstractRoute, List<ConfigurationReference>> origins = new HashMap<>();
    _origins.put(vr, origins);
    vr.getOspfProcesses()
        .forEach(
            (name, process) -> {
              String policyName = vr._vrf.getOspfProcesses().get(name).getExportPolicy();
              if (policyName == null) {
                return;
              }
              vr.getMainRib()
                  .getTypedRoutes()
                  .forEach(
                      input -> {
                        List<ConfigurationReference> refs = new ArrayList<>();
                        RoutingPolicy policy =
                            new RoutingPolicy(policyName, vr.getConfiguration()) {
                              @Override
                              public boolean process(
                                  AbstractRouteDecorator route,
                                  AbstractRouteBuilder<?, ?> output,
                                  Direction direction) {
                                return _policies
                                    .get(vr.getHostname())
                                    .process(policyName, route, output, null, direction, refs);
                              }
                            };
                        Optional<OspfExternalRoute> output =
                            process.convertToExternalRoute(input, policy);
                        if (output.isPresent()) {
                          origins.put(output.get(), refs);
                          _recorder.record(vr, input.getRoute(), refs);
                        } else {
                          _blocked.record(vr, input.getRoute(), vr, "EXPORT", refs);
                        }
                      });
            });
    IsisProcess process = vr._vrf.getIsisProcess();
    if (process == null
        || process.getExportPolicy() == null
        || (process.getLevel1() == null && process.getLevel2() == null)) {
      return;
    }
    vr.getMainRib()
        .getTypedRoutes()
        .forEach(
            input -> {
              if (input.getRoute() instanceof IsisRoute) {
                return;
              }
              List<ConfigurationReference> refs = new ArrayList<>();
              IsisRoute.Builder output =
                  IsisProtocolHelper.convertNonIsisRouteToIsisRoute(
                      input.getRoute(),
                      process,
                      process.getLevel1() != null,
                      vr.getConfiguration());
              if (_policies
                  .get(vr.getHostname())
                  .process(process.getExportPolicy(), input, output, null, Direction.OUT, refs)) {
                origins.put(output.build(), refs);
                _recorder.record(vr, input.getRoute(), refs);
              } else {
                _blocked.record(vr, input.getRoute(), vr, "EXPORT", refs);
              }
            });
  }

  List<ConfigurationReference> origin(VirtualRouter router, AbstractRoute route) {
    return _origins
        .getOrDefault(router, Collections.emptyMap())
        .getOrDefault(route, Collections.emptyList());
  }

  void importOspf(
      VirtualRouter receiver,
      VirtualRouter sender,
      String iface,
      AbstractRouteBuilder<?, ?> route,
      List<ConfigurationReference> references) {
    List<ConfigurationReference> refs = new ArrayList<>(references);
    String policy =
        receiver
            .getConfiguration()
            .getAllInterfaces()
            .get(iface)
            .getOspfInboundDistributeListPolicy();
    if (_policies
        .get(receiver.getHostname())
        .process(policy, route.build(), route, null, Direction.IN, refs)) {
      route.setNonRouting(false);
      AbstractRoute imported = route.build();
      if (imported instanceof OspfExternalType1Route
          && new OspfExternalType1Rib(receiver.getHostname())
              .mergeRouteGetDelta((OspfExternalType1Route) imported)
              .isEmpty()) {
        return;
      }
      if (imported instanceof OspfExternalType2Route
          && new OspfExternalType2Rib(receiver.getHostname())
              .mergeRouteGetDelta((OspfExternalType2Route) imported)
              .isEmpty()) {
        return;
      }
      _recorder.record(receiver, imported, refs);
    } else {
      _blocked.record(receiver, route.build(), sender, "IMPORT", refs);
    }
  }
}
