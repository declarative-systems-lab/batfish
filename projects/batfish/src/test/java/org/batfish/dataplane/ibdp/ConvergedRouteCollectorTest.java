package org.batfish.dataplane.ibdp;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import com.google.common.collect.ImmutableSet;
import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.batfish.main.Batfish;
import org.batfish.main.BatfishTestUtils;
import org.batfish.main.TestrigText;
import org.batfish.simulation.ConfigurationSourceIndex;
import org.batfish.simulation.RibResult;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public final class ConvergedRouteCollectorTest {
  @Rule public TemporaryFolder _folder = new TemporaryFolder();

  @Test
  public void testCollectionDoesNotChangeConvergedProtocolState() throws IOException {
    String a =
        "hostname a\ninterface Ethernet0\n ip address 10.0.0.1 255.255.255.0\n!\n"
            + "router bgp 65001\n neighbor 10.0.0.2 remote-as 65002\n!\n";
    String b =
        "hostname b\n"
            + "interface Ethernet0\n"
            + " ip address 10.0.0.2 255.255.255.0\n"
            + "!\n"
            + "ip route 203.0.113.0 255.255.255.0 Null0\n"
            + "router bgp 65002\n"
            + " neighbor 10.0.0.1 remote-as 65001\n"
            + " network 203.0.113.0 mask 255.255.255.0\n"
            + "!\n";
    Batfish batfish =
        BatfishTestUtils.getBatfishFromTestrigText(
            TestrigText.builder()
                .setConfigurationText(ImmutableMap.of("a.cfg", a, "b.cfg", b))
                .build(),
            _folder);
    IncrementalDataPlanePlugin plugin = new IncrementalDataPlanePlugin();
    plugin.initialize(batfish);
    IbdpResult result = (IbdpResult) plugin.computeDataPlane(batfish.getSnapshot());
    Map<VirtualRouter, List<Object>> before = new HashMap<>();
    result
        .getNodes()
        .values()
        .forEach(node -> node.getVirtualRouters().forEach(vr -> before.put(vr, state(vr))));
    RibResult first = new ConvergedRouteCollector(new ConfigurationSourceIndex()).collect(result);
    RibResult second = new ConvergedRouteCollector(new ConfigurationSourceIndex()).collect(result);
    assertTrue(result._topologies.getBgpTopology().getGraph().edges().size() > 0);
    before.forEach((vr, state) -> assertEquals(state, state(vr)));
    assertEquals(first.getMainRoutes().size(), second.getMainRoutes().size());
    assertEquals(first.getAlternativeRoutes().size(), second.getAlternativeRoutes().size());
    assertEquals(first.getBlockedRoutes().size(), second.getBlockedRoutes().size());
  }

  private static List<Object> state(VirtualRouter vr) {
    return ImmutableList.of(
        ImmutableSet.copyOf(vr.getMainRib().getTypedRoutes()),
        ImmutableSet.copyOf(vr.getAllBgpRoutes()),
        vr.getBgpRoutingProcess().iterationHashCode(),
        vr.getBgpRoutingProcess().isDirty(),
        vr.getPrefixTracer().summarize());
  }
}
