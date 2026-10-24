package org.batfish.simulation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.batfish.datamodel.Ip;
import org.batfish.datamodel.Prefix;
import org.batfish.datamodel.RoutingProtocol;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public final class SnapshotSimulationTest {
  @Rule public TemporaryFolder _folder = new TemporaryFolder();

  private static void config(Path root, String name, String text) throws IOException {
    Files.write(
        root.resolve("configs").resolve(name + ".cfg"), text.getBytes(StandardCharsets.UTF_8));
  }

  @Test
  public void testFinalCandidatesPoliciesAndEffectiveFib() throws IOException {
    Path root = _folder.newFolder().toPath();
    Files.createDirectory(root.resolve("configs"));
    config(
        root,
        "a",
        "hostname a\n"
            + "interface Ethernet0\n"
            + " ip address 10.0.0.1 255.255.255.0\n"
            + " ip access-group OUT out\n"
            + "!\n"
            + "interface Ethernet1\n"
            + " ip address 172.16.0.1 255.255.255.0\n"
            + "!\n"
            + "router bgp 65001\n"
            + " bgp router-id 1.1.1.1\n"
            + " neighbor 10.0.0.2 remote-as 65002\n"
            + " neighbor 10.0.0.2 route-map IMPORT in\n"
            + " neighbor 10.0.0.3 remote-as 65003\n"
            + "!\n"
            + "ip prefix-list BLOCK seq 10 permit 192.0.2.0/24\n"
            + "route-map IMPORT deny 10\n"
            + " match ip address prefix-list BLOCK\n"
            + "!\n"
            + "route-map IMPORT permit 20\n"
            + " set local-preference 200\n"
            + "!\n"
            + "ip access-list extended OUT\n"
            + " permit ip 192.168.0.0 0.0.255.255 any\n"
            + " permit ip 10.0.0.0 0.0.0.255 any\n"
            + " deny ip 10.0.0.0 0.255.255.255 any\n"
            + "!\n");
    config(
        root,
        "b",
        "hostname b\n"
            + "interface Ethernet0\n"
            + " ip address 10.0.0.2 255.255.255.0\n"
            + "!\n"
            + "ip route 203.0.113.0 255.255.255.0 Null0\n"
            + "ip route 198.51.100.0 255.255.255.0 Null0\n"
            + "ip route 192.0.2.0 255.255.255.0 Null0\n"
            + "router bgp 65002\n"
            + " bgp router-id 2.2.2.2\n"
            + " neighbor 10.0.0.1 remote-as 65001\n"
            + " neighbor 10.0.0.1 route-map EXPORT out\n"
            + " network 203.0.113.0 mask 255.255.255.0\n"
            + " network 198.51.100.0 mask 255.255.255.0\n"
            + " network 192.0.2.0 mask 255.255.255.0\n"
            + "!\n"
            + "ip prefix-list BLOCK seq 10 permit 198.51.100.0/24\n"
            + "route-map EXPORT deny 10\n"
            + " match ip address prefix-list BLOCK\n"
            + "!\n"
            + "route-map EXPORT permit 20\n"
            + "!\n");
    config(
        root,
        "c",
        "hostname c\ninterface Ethernet0\n ip address 10.0.0.3 255.255.255.0\n!\n"
            + "ip route 203.0.113.0 255.255.255.0 Null0\nrouter bgp 65003\n bgp router-id 3.3.3.3\n"
            + " neighbor 10.0.0.1 remote-as 65001\n network 203.0.113.0 mask 255.255.255.0\n!\n");
    try (SnapshotSimulation simulation = SnapshotSimulation.open(root)) {
      RibResult rib = simulation.getRib();
      Prefix prefix = Prefix.parse("203.0.113.0/24");
      RibResult.Entry selected =
          rib.getMainRoutes().stream()
              .filter(e -> e.getNode().equals("a") && e.getRoute().getNetwork().equals(prefix))
              .findFirst()
              .get();
      assertEquals(Ip.parse("10.0.0.2"), selected.getRoute().getNextHopIp());
      assertTrue(
          selected.getReferences().stream()
              .anyMatch(r -> r.getKind().equals("ROUTE_MAP") && r.getName().equals("IMPORT:20")));
      assertTrue(
          rib.getAlternativeRoutes().stream()
              .anyMatch(
                  e ->
                      e.getNode().equals("a")
                          && e.getRoute().getNetwork().equals(prefix)
                          && e.getRoute().getNextHopIp().equals(Ip.parse("10.0.0.3"))));
      assertTrue(
          rib.getBlockedRoutes().stream()
              .anyMatch(
                  e ->
                      "EXPORT".equals(e.getBlockedBy())
                          && e.getRoute().getNetwork().equals(Prefix.parse("198.51.100.0/24"))));
      assertTrue(
          rib.getBlockedRoutes().stream()
              .anyMatch(
                  e ->
                      "IMPORT".equals(e.getBlockedBy())
                          && e.getRoute().getNetwork().equals(Prefix.parse("192.0.2.0/24"))));
      EffectiveFibResult fib = simulation.getEffectiveFib();
      assertTrue(
          fib.getPermittedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "192.168.1.1", "203.0.113.1")
                          && e.getAction() == EffectiveFibResult.Action.FORWARD));
      assertTrue(
          fib.getDeniedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "10.1.1.1", "203.0.113.1")
                          && e.getReferences().stream()
                              .anyMatch(r -> r.getName().equals("OUT:line-2"))));
      assertTrue(
          fib.getDeniedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "8.8.8.8", "203.0.113.1")
                          && e.getReferences().stream()
                              .anyMatch(r -> r.getName().equals("OUT:implicit-deny"))));
      assertTrue(
          fib.getPermittedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "8.8.8.8", "10.0.0.1")
                          && e.getAction() == EffectiveFibResult.Action.ACCEPT));
      assertTrue(
          fib.getPermittedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "8.8.8.8", "11.0.0.1")
                          && e.getAction() == EffectiveFibResult.Action.NO_ROUTE));
      assertTrue(simulation.getEffectiveFib() == fib);
      assertTrue(simulation.getRib() == rib);
    }
    assertTrue(Files.exists(root.resolve("configs/a.cfg")));
  }

  private static boolean matches(EffectiveFibResult.Entry e, String source, String destination) {
    long src = Ip.parse(source).asLong();
    long dst = Ip.parse(destination).asLong();
    return e.getNode().equals("a")
        && "Ethernet1".equals(e.getIngressInterface())
        && src >= e.getSourceStart().asLong()
        && src <= e.getSourceEnd().asLong()
        && dst >= e.getDestinationStart().asLong()
        && dst <= e.getDestinationEnd().asLong();
  }

  @Test
  public void testIbgpMultipathAndStaticAlternatives() throws IOException {
    Path root = _folder.newFolder().toPath();
    Files.createDirectory(root.resolve("configs"));
    config(
        root,
        "a",
        "hostname a\ninterface Ethernet0\n ip address 10.0.0.1 255.255.255.0\n!\n"
            + "ip route 203.0.113.0 255.255.255.0 Null0 250\n"
            + "router bgp 65000\n bgp router-id 1.1.1.1\n maximum-paths ibgp 2\n"
            + " neighbor 10.0.0.2 remote-as 65000\n neighbor 10.0.0.3 remote-as 65000\n!\n");
    for (int i = 2; i <= 3; i++) {
      config(
          root,
          "r" + i,
          "hostname r"
              + i
              + "\ninterface Ethernet0\n ip address 10.0.0."
              + i
              + " 255.255.255.0\n!\n"
              + "ip route 203.0.113.0 255.255.255.0 Null0\n"
              + "router bgp 65000\n bgp router-id "
              + i
              + "."
              + i
              + "."
              + i
              + "."
              + i
              + "\n"
              + " neighbor 10.0.0.1 remote-as 65000\n network 203.0.113.0 mask 255.255.255.0\n!\n");
    }
    try (SnapshotSimulation simulation = SnapshotSimulation.open(root)) {
      Prefix prefix = Prefix.parse("203.0.113.0/24");
      assertEquals(
          2L,
          simulation.getRib().getMainRoutes().stream()
              .filter(
                  e ->
                      e.getNode().equals("a")
                          && e.getRoute().getNetwork().equals(prefix)
                          && e.getRoute().getProtocol() == RoutingProtocol.IBGP)
              .count());
      assertTrue(
          simulation.getRib().getAlternativeRoutes().stream()
              .anyMatch(
                  e ->
                      e.getNode().equals("a")
                          && e.getRoute().getNetwork().equals(prefix)
                          && e.getRoute().getProtocol() == RoutingProtocol.STATIC
                          && e.getProtocolBest()));
      long branches =
          simulation.getEffectiveFib().getPermittedEntries().stream()
              .filter(
                  e ->
                      e.getNode().equals("a")
                          && e.getIngressInterface() == null
                          && e.getAction() == EffectiveFibResult.Action.FORWARD
                          && e.getDestinationStart().equals(prefix.getStartIp()))
              .count();
      assertEquals(2L, branches);
    }
  }

  @Test
  public void testIngressAclAndLongestPrefix() throws IOException {
    Path root = _folder.newFolder().toPath();
    Files.createDirectory(root.resolve("configs"));
    config(
        root,
        "a",
        "hostname a\n"
            + "interface Ethernet0\n"
            + " ip address 10.0.0.1 255.255.255.0\n"
            + "!\n"
            + "interface Ethernet1\n"
            + " ip address 172.16.0.1 255.255.255.0\n"
            + " ip access-group IN in\n"
            + "!\n"
            + "ip route 0.0.0.0 0.0.0.0 Null0\n"
            + "ip route 203.0.113.0 255.255.255.0 10.0.0.2\n"
            + "ip access-list extended IN\n"
            + " deny ip host 8.8.8.8 any\n"
            + " permit ip any any\n"
            + "!\n");
    try (SnapshotSimulation simulation = SnapshotSimulation.open(root)) {
      EffectiveFibResult fib = simulation.getEffectiveFib();
      assertTrue(
          fib.getDeniedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "8.8.8.8", "10.0.0.1")
                          && e.getAction() == EffectiveFibResult.Action.DENIED_IN));
      assertTrue(
          fib.getPermittedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "9.9.9.9", "203.0.113.1")
                          && e.getAction() == EffectiveFibResult.Action.FORWARD));
      assertTrue(
          fib.getPermittedEntries().stream()
              .anyMatch(
                  e ->
                      matches(e, "9.9.9.9", "203.0.114.1")
                          && e.getAction() == EffectiveFibResult.Action.NULL_ROUTE));
      assertFalse(
          fib.getPermittedEntries().stream().anyMatch(e -> matches(e, "8.8.8.8", "10.0.0.1")));
    }
  }

  @Test
  public void testOspfAndIsis() throws IOException {
    Path root = _folder.newFolder().toPath();
    Files.createDirectory(root.resolve("configs"));
    for (int i = 1; i <= 2; i++) {
      config(
          root,
          "r" + i,
          "hostname r"
              + i
              + "\ninterface Ethernet0\n ip address 10.0.0."
              + i
              + " 255.255.255.0\n ip router isis CORE\n!\n"
              + "interface Loopback0\n ip address "
              + i
              + "."
              + i
              + "."
              + i
              + "."
              + i
              + " 255.255.255.255\n ip router isis CORE\n!\n"
              + "router ospf 1\n network 0.0.0.0 255.255.255.255 area 0\n!\n"
              + "router isis CORE\n net 49.0001.0000.0000.000"
              + i
              + ".00\n is-type level-1\n!\n");
    }
    try (SnapshotSimulation simulation = SnapshotSimulation.open(root)) {
      Prefix remote = Prefix.parse("2.2.2.2/32");
      assertTrue(
          simulation.getRib().getMainRoutes().stream()
              .anyMatch(
                  e ->
                      e.getNode().equals("r1")
                          && e.getRoute().getNetwork().equals(remote)
                          && e.getRoute().getProtocol() == RoutingProtocol.OSPF));
      assertTrue(
          simulation.getRib().getAlternativeRoutes().stream()
              .anyMatch(
                  e ->
                      e.getNode().equals("r1")
                          && e.getRoute().getNetwork().equals(remote)
                          && e.getRoute().getProtocol() == RoutingProtocol.ISIS_L1));
      assertFalse(simulation.getEffectiveFib().getPermittedEntries().isEmpty());
    }
  }
}
