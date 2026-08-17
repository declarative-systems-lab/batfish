package org.batfish.datamodel.routing_policy.expr;

import static com.google.common.base.Preconditions.checkArgument;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.google.common.collect.ImmutableMap;
import java.util.Objects;
import java.util.Set;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.BgpRoute;
import org.batfish.datamodel.RegexCommunitySet;
import org.batfish.datamodel.bgp.community.Community;
import org.batfish.datamodel.routing_policy.Environment;
import org.batfish.datamodel.routing_policy.Result;

import org.batfish.datamodel.CommunityList;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;

/**
 * Boolean expression that tests whether an {@link Environment} contains a BGP route with a
 * community matching a given {@link CommunitySetExpr}.
 */
public final class MatchCommunitySet extends BooleanExpr {
  private static final String PROP_EXPR = "expr";

  private final CommunitySetExpr _expr;

  @JsonCreator
  private static MatchCommunitySet create(@JsonProperty(PROP_EXPR) CommunitySetExpr expr) {
    checkArgument(expr != null, "%s must be provided", PROP_EXPR);
    return new MatchCommunitySet(expr);
  }

  public MatchCommunitySet(CommunitySetExpr expr) {
    _expr = expr;
  }

  @Override
  public <T, U> T accept(BooleanExprVisitor<T, U> visitor, U arg) {
    return visitor.visitMatchCommunitySet(this, arg);
  }

  @Override
  public Result evaluate(Environment environment) {
    Set<Community> inputCommunities = null;
    if (environment.getUseOutputAttributes()
        && environment.getOutputRoute() instanceof BgpRoute.Builder<?, ?>) {
      BgpRoute.Builder<?, ?> bgpRouteBuilder =
          (BgpRoute.Builder<?, ?>) environment.getOutputRoute();
      inputCommunities = bgpRouteBuilder.getCommunitiesAsSet();
    } else if (environment.getReadFromIntermediateBgpAttributes()) {
      inputCommunities = environment.getIntermediateBgpAttributes().getCommunitiesAsSet();
    } else if (environment.getOriginalRoute() instanceof BgpRoute) {
      BgpRoute<?, ?> bgpRoute = (BgpRoute<?, ?>) environment.getOriginalRoute();
      inputCommunities = bgpRoute.getCommunities().getCommunities();
    }
    return inputCommunities == null
        ? new Result(false)
        : new Result(_expr.matchAnyCommunity(environment, inputCommunities));
  }

  @JsonProperty(PROP_EXPR)
  public CommunitySetExpr getExpr() {
    return _expr;
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    }
    if (!(obj instanceof MatchCommunitySet)) {
      return false;
    }
    MatchCommunitySet other = (MatchCommunitySet) obj;
    return Objects.equals(_expr, other._expr);
  }

  @Override
  public int hashCode() {
    return Objects.hashCode(_expr);
  }

  /** Add configuration constant - SMT symbolic variable */
  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  // private transient BoolExpr _configLineEnable;

  public void initSmtVariable(
      Context context, Solver solver, String configVarPrefix,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth) {
    // assert that the community list line is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("MatchCommunitySet.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // TODO: handle shared object case properly, now is just throw exception
    if (_expr.getEnableSmtVariable()) {
      throw new BatfishException(
          "MatchCommunitySet.initSmtVariable: shared object CommunitySetExpr.");
    }

    // init smt variable for community set configuration
    _expr.initSmtVariable(context, solver, configVarPrefix, commsIndex, commsWidth);

    // add the line enable flag, and default configure to true
    // _configLineEnable = context.mkBoolConst(configVarPrefix + "enable");
    // BoolExpr configLineEnableConstraint = context.mkEq(_configLineEnable, context.mkTrue());
    // solver.add(configLineEnableConstraint);

    // configure the smt variable enable flag to true
    _enableSmtVariable = true;
    _configVarPrefix = configVarPrefix;
  }

  public boolean getEnableSmtVariable() {
    return _enableSmtVariable;
  }

  public String getConfigVarPrefix() {
    return _configVarPrefix;
  }

  // public BoolExpr getConfigLineEnable() {
  //   return _configLineEnable;
  // }
}
