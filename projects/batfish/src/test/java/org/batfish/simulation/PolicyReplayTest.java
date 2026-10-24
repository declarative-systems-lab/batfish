package org.batfish.simulation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.google.common.collect.ImmutableList;
import java.util.ArrayList;
import java.util.List;
import org.batfish.datamodel.Bgpv4Route;
import org.batfish.datamodel.CommunityList;
import org.batfish.datamodel.CommunityListLine;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.ConfigurationFormat;
import org.batfish.datamodel.LineAction;
import org.batfish.datamodel.Prefix;
import org.batfish.datamodel.bgp.community.StandardCommunity;
import org.batfish.datamodel.routing_policy.Environment.Direction;
import org.batfish.datamodel.routing_policy.RoutingPolicy;
import org.batfish.datamodel.routing_policy.expr.BooleanExprs;
import org.batfish.datamodel.routing_policy.expr.LiteralCommunity;
import org.batfish.datamodel.routing_policy.expr.LiteralLong;
import org.batfish.datamodel.routing_policy.expr.MatchCommunitySet;
import org.batfish.datamodel.routing_policy.expr.NamedCommunitySet;
import org.batfish.datamodel.routing_policy.statement.If;
import org.batfish.datamodel.routing_policy.statement.SetLocalPreference;
import org.batfish.datamodel.routing_policy.statement.Statements;
import org.junit.Test;

public final class PolicyReplayTest {
  @Test
  public void testCommunityDecisionAndDefaultDeny() {
    Configuration c = new Configuration("node", ConfigurationFormat.CISCO_IOS);
    c.getCommunityLists()
        .put(
            "GOOD",
            new CommunityList(
                "GOOD",
                ImmutableList.of(
                    new CommunityListLine(
                        LineAction.PERMIT, new LiteralCommunity(StandardCommunity.of(65000, 1)))),
                false));
    RoutingPolicy policy = new RoutingPolicy("IMPORT", c);
    policy.setStatements(
        ImmutableList.of(
            new If(
                "~RMCLAUSE~IMPORT~10~",
                new MatchCommunitySet(new NamedCommunitySet("GOOD")),
                ImmutableList.of(
                    new SetLocalPreference(new LiteralLong(200)),
                    Statements.ReturnTrue.toStaticStatement()),
                ImmutableList.of(Statements.ReturnFalse.toStaticStatement()))));
    c.getRoutingPolicies().put(policy.getName(), policy);
    PolicyReplay replay = new PolicyReplay(c, new ConfigurationSourceIndex());
    for (int community = 1; community <= 2; community++) {
      Bgpv4Route route =
          Bgpv4Route.testBuilder()
              .setNetwork(Prefix.parse("203.0.113.0/24"))
              .setLocalPreference(100)
              .setCommunities(ImmutableList.of(StandardCommunity.of(65000, community)))
              .build();
      Bgpv4Route.Builder ordinary = route.toBuilder();
      Bgpv4Route.Builder traced = route.toBuilder();
      List<ConfigurationReference> refs = new ArrayList<>();
      boolean permit = replay.process("IMPORT", route, traced, null, Direction.IN, refs);
      assertEquals(policy.processBgpRoute(route, ordinary, null, Direction.IN), permit);
      assertEquals(ordinary.build(), traced.build());
      assertEquals(100L, route.getLocalPreference());
      assertEquals(community == 1, permit);
      assertTrue(refs.stream().anyMatch(r -> r.getKind().equals("COMMUNITY_LIST")));
      assertTrue(
          refs.stream()
              .anyMatch(r -> r.getName().equals(permit ? "IMPORT:10" : "IMPORT:default-deny")));
      if (!permit) {
        assertFalse(refs.stream().anyMatch(r -> r.getName().equals("IMPORT:10")));
      }
    }
  }

  @Test
  public void testUnconditionalClauseSurvivesSimplification() {
    Configuration c = new Configuration("node", ConfigurationFormat.CISCO_IOS);
    RoutingPolicy policy = new RoutingPolicy("IMPORT", c);
    policy.setStatements(
        ImmutableList.of(
            new If(
                "~RMCLAUSE~IMPORT~20~",
                BooleanExprs.TRUE,
                ImmutableList.of(Statements.ReturnTrue.toStaticStatement()),
                ImmutableList.of())));
    c.getRoutingPolicies().put("IMPORT", policy.simplify());
    Bgpv4Route route = Bgpv4Route.testBuilder().setNetwork(Prefix.ZERO).build();
    List<ConfigurationReference> refs = new ArrayList<>();
    assertTrue(
        new PolicyReplay(c, new ConfigurationSourceIndex())
            .process("IMPORT", route, route.toBuilder(), null, Direction.IN, refs));
    assertTrue(refs.stream().anyMatch(r -> r.getName().equals("IMPORT:20")));
  }
}
