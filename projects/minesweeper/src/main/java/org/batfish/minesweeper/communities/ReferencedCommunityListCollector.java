package org.batfish.minesweeper.communities;

import com.google.common.collect.ImmutableSet;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import javax.annotation.Nonnull;
import javax.annotation.ParametersAreNonnullByDefault;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.routing_policy.RoutingPolicy;
import org.batfish.datamodel.routing_policy.expr.BooleanExpr;
import org.batfish.datamodel.routing_policy.expr.BooleanExprVisitor;
import org.batfish.datamodel.routing_policy.expr.BooleanExprs.StaticBooleanExpr;
import org.batfish.datamodel.routing_policy.expr.CallExpr;
import org.batfish.datamodel.routing_policy.expr.CommunitySetExpr;
import org.batfish.datamodel.routing_policy.expr.Conjunction;
import org.batfish.datamodel.routing_policy.expr.ConjunctionChain;
import org.batfish.datamodel.routing_policy.expr.Disjunction;
import org.batfish.datamodel.routing_policy.expr.FirstMatchChain;
import org.batfish.datamodel.routing_policy.expr.MatchCommunitySet;
import org.batfish.datamodel.routing_policy.expr.NamedCommunitySet;
import org.batfish.datamodel.routing_policy.expr.Not;
import org.batfish.datamodel.routing_policy.expr.WithEnvironmentExpr;
import org.batfish.datamodel.routing_policy.statement.AddCommunity;
import org.batfish.datamodel.routing_policy.statement.BufferedStatement;
import org.batfish.datamodel.routing_policy.statement.DeleteCommunity;
import org.batfish.datamodel.routing_policy.statement.If;
import org.batfish.datamodel.routing_policy.statement.SetCommunity;
import org.batfish.datamodel.routing_policy.statement.Statement;
import org.batfish.datamodel.routing_policy.statement.StatementVisitor;

/** Collects names of {@link org.batfish.datamodel.CommunityList}s referenced by routing policies. */
@ParametersAreNonnullByDefault
public final class ReferencedCommunityListCollector {

  private ReferencedCommunityListCollector() {}

  public static @Nonnull Set<String> collect(Configuration config) {
    Set<String> names = new HashSet<>();
    for (RoutingPolicy policy : config.getRoutingPolicies().values()) {
      for (Statement stmt : policy.getStatements()) {
        names.addAll(collectFromStatement(stmt));
      }
    }
    return names;
  }

  private static Set<String> collectFromStatement(Statement stmt) {
    return stmt.accept(STATEMENT_COLLECTOR, null);
  }

  private static void collectFromBooleanExpr(BooleanExpr expr, Set<String> names) {
    names.addAll(expr.accept(BOOLEAN_COLLECTOR, null));
  }

  private static void collectFromCommunitySetExpr(CommunitySetExpr expr, Set<String> names) {
    if (expr instanceof NamedCommunitySet) {
      names.add(((NamedCommunitySet) expr).getName());
    }
  }

  private static final StatementVisitor<Set<String>, Void> STATEMENT_COLLECTOR =
      new StatementVisitor<Set<String>, Void>() {
        @Override
        public Set<String> visitAddCommunity(AddCommunity addCommunity, Void arg) {
          Set<String> names = new HashSet<>();
          collectFromCommunitySetExpr(addCommunity.getExpr(), names);
          return names;
        }

        @Override
        public Set<String> visitBufferedStatement(BufferedStatement bufferedStatement, Void arg) {
          return collectFromStatement(bufferedStatement.getStatement());
        }

        @Override
        public Set<String> visitDeleteCommunity(DeleteCommunity deleteCommunity, Void arg) {
          Set<String> names = new HashSet<>();
          collectFromCommunitySetExpr(deleteCommunity.getExpr(), names);
          return names;
        }

        @Override
        public Set<String> visitIf(If if1, Void arg) {
          Set<String> names = new HashSet<>();
          collectFromBooleanExpr(if1.getGuard(), names);
          if1.getTrueStatements().forEach(s -> names.addAll(collectFromStatement(s)));
          if1.getFalseStatements().forEach(s -> names.addAll(collectFromStatement(s)));
          return names;
        }

        @Override
        public Set<String> visitSetCommunity(SetCommunity setCommunity, Void arg) {
          Set<String> names = new HashSet<>();
          collectFromCommunitySetExpr(setCommunity.getExpr(), names);
          return names;
        }

        private Set<String> empty() {
          return ImmutableSet.of();
        }

        @Override
        public Set<String> visitCallStatement(
            org.batfish.datamodel.routing_policy.statement.CallStatement callStatement, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitComment(
            org.batfish.datamodel.routing_policy.statement.Comment comment, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitPrependAsPath(
            org.batfish.datamodel.routing_policy.statement.PrependAsPath prependAsPath, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetAdministrativeCost(
            org.batfish.datamodel.routing_policy.statement.SetAdministrativeCost
                setAdministrativeCost,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetCommunities(
            org.batfish.datamodel.routing_policy.communities.SetCommunities setCommunities,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetDefaultPolicy(
            org.batfish.datamodel.routing_policy.statement.SetDefaultPolicy setDefaultPolicy,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetEigrpMetric(
            org.batfish.datamodel.routing_policy.statement.SetEigrpMetric setEigrpMetric,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetIsisLevel(
            org.batfish.datamodel.routing_policy.statement.SetIsisLevel setIsisLevel, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetIsisMetricType(
            org.batfish.datamodel.routing_policy.statement.SetIsisMetricType setIsisMetricType,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetLocalPreference(
            org.batfish.datamodel.routing_policy.statement.SetLocalPreference setLocalPreference,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetMetric(
            org.batfish.datamodel.routing_policy.statement.SetMetric setMetric, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetNextHop(
            org.batfish.datamodel.routing_policy.statement.SetNextHop setNextHop, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetOrigin(
            org.batfish.datamodel.routing_policy.statement.SetOrigin setOrigin, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetOspfMetricType(
            org.batfish.datamodel.routing_policy.statement.SetOspfMetricType setOspfMetricType,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetTag(
            org.batfish.datamodel.routing_policy.statement.SetTag setTag, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetVarMetricType(
            org.batfish.datamodel.routing_policy.statement.SetVarMetricType setVarMetricType,
            Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitSetWeight(
            org.batfish.datamodel.routing_policy.statement.SetWeight setWeight, Void arg) {
          return empty();
        }

        @Override
        public Set<String> visitStaticStatement(
            org.batfish.datamodel.routing_policy.statement.Statements.StaticStatement
                staticStatement,
            Void arg) {
          return empty();
        }
      };

  private static final BooleanExprVisitor<Set<String>, Void> BOOLEAN_COLLECTOR =
      new BooleanExprVisitor<Set<String>, Void>() {
        @Override
        public Set<String> visitBooleanExprs(StaticBooleanExpr staticBooleanExpr, Void arg) {
          return ImmutableSet.of();
        }

        @Override
        public Set<String> visitCallExpr(CallExpr callExpr, Void arg) {
          return ImmutableSet.of();
        }

        @Override
        public Set<String> visitConjunction(Conjunction conjunction, Void arg) {
          return visitAll(conjunction.getConjuncts());
        }

        @Override
        public Set<String> visitConjunctionChain(ConjunctionChain conjunctionChain, Void arg) {
          return visitAll(conjunctionChain.getSubroutines());
        }

        @Override
        public Set<String> visitDisjunction(Disjunction disjunction, Void arg) {
          return visitAll(disjunction.getDisjuncts());
        }

        @Override
        public Set<String> visitFirstMatchChain(FirstMatchChain firstMatchChain, Void arg) {
          return visitAll(firstMatchChain.getSubroutines());
        }

        @Override
        public Set<String> visitMatchCommunitySet(MatchCommunitySet matchCommunitySet, Void arg) {
          Set<String> names = new HashSet<>();
          collectFromCommunitySetExpr(matchCommunitySet.getExpr(), names);
          return names;
        }

        @Override
        public Set<String> visitNot(Not not, Void arg) {
          return not.getExpr().accept(this, arg);
        }

        @Override
        public Set<String> visitWithEnvironmentExpr(
            WithEnvironmentExpr withEnvironmentExpr, Void arg) {
          return withEnvironmentExpr.getExpr().accept(this, arg);
        }

        private Set<String> visitAll(List<BooleanExpr> exprs) {
          Set<String> names = new HashSet<>();
          for (BooleanExpr expr : exprs) {
            names.addAll(expr.accept(this, null));
          }
          return names;
        }

        private Set<String> unimplemented() {
          return ImmutableSet.of();
        }

        @Override
        public Set<String> visitHasRoute(
            org.batfish.datamodel.routing_policy.expr.HasRoute hasRoute, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitHasRoute6(
            org.batfish.datamodel.routing_policy.expr.HasRoute6 hasRoute6, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchAsPath(
            org.batfish.datamodel.routing_policy.expr.MatchAsPath matchAsPath, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchColor(
            org.batfish.datamodel.routing_policy.expr.MatchColor matchColor, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchCommunities(
            org.batfish.datamodel.routing_policy.communities.MatchCommunities matchCommunities,
            Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchIp6AccessList(
            org.batfish.datamodel.routing_policy.expr.MatchIp6AccessList matchIp6AccessList,
            Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchIpv4(
            org.batfish.datamodel.routing_policy.expr.MatchIpv4 matchIpv4, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchIpv6(
            org.batfish.datamodel.routing_policy.expr.MatchIpv6 matchIpv6, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchLocalPreference(
            org.batfish.datamodel.routing_policy.expr.MatchLocalPreference matchLocalPreference,
            Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchLocalRouteSourcePrefixLength(
            org.batfish.datamodel.routing_policy.expr.MatchLocalRouteSourcePrefixLength
                matchLocalRouteSourcePrefixLength,
            Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchMetric(
            org.batfish.datamodel.routing_policy.expr.MatchMetric matchMetric, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchPrefix6Set(
            org.batfish.datamodel.routing_policy.expr.MatchPrefix6Set matchPrefix6Set, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchPrefixSet(
            org.batfish.datamodel.routing_policy.expr.MatchPrefixSet matchPrefixSet, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchProcessAsn(
            org.batfish.datamodel.routing_policy.expr.MatchProcessAsn matchProcessAsn, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchProtocol(
            org.batfish.datamodel.routing_policy.expr.MatchProtocol matchProtocol, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchRouteType(
            org.batfish.datamodel.routing_policy.expr.MatchRouteType matchRouteType, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchSourceVrf(
            org.batfish.datamodel.routing_policy.expr.MatchSourceVrf matchSourceVrf, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitMatchTag(
            org.batfish.datamodel.routing_policy.expr.MatchTag matchTag, Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitNeighborIsAsPath(
            org.batfish.datamodel.routing_policy.expr.NeighborIsAsPath neighborIsAsPath,
            Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitOriginatesFromAsPath(
            org.batfish.datamodel.routing_policy.expr.OriginatesFromAsPath originatesFromAsPath,
            Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitPassesThroughAsPath(
            org.batfish.datamodel.routing_policy.expr.PassesThroughAsPath passesThroughAsPath,
            Void arg) {
          return unimplemented();
        }

        @Override
        public Set<String> visitRouteIsClassful(
            org.batfish.datamodel.routing_policy.expr.RouteIsClassful routeIsClassful, Void arg) {
          return unimplemented();
        }
      };
}
