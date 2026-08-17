package org.batfish.datamodel;

import static com.google.common.base.MoreObjects.toStringHelper;
import static java.util.Objects.requireNonNull;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.google.common.collect.ImmutableMap;
import java.io.Serializable;
import java.util.Objects;
import javax.annotation.Nonnull;

import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.RegexCommunitySet;
import org.batfish.datamodel.bgp.community.Community;
import org.batfish.datamodel.routing_policy.expr.CommunitySetExpr;
import org.batfish.datamodel.routing_policy.expr.NamedCommunitySet;
import org.batfish.datamodel.routing_policy.expr.LiteralCommunitySet;
import org.batfish.datamodel.routing_policy.expr.LiteralCommunity;

/** A line in a CommunityList */
public class CommunityListLine implements Serializable {
  private static final String PROP_ACTION = "action";
  private static final String PROP_MATCH_CONDITION = "matchCondition";

  public static @Nonnull CommunityListLine accepting(CommunitySetExpr matchCondition) {
    return new CommunityListLine(LineAction.PERMIT, matchCondition);
  }

  private final LineAction _action;

  private /*final*/ CommunitySetExpr _matchCondition;

  public CommunityListLine(@Nonnull LineAction action, @Nonnull CommunitySetExpr matchCondition) {
    _action = action;
    _matchCondition = matchCondition;

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  @JsonCreator
  private static @Nonnull CommunityListLine create(
      @JsonProperty(PROP_ACTION) LineAction action,
      @JsonProperty(PROP_MATCH_CONDITION) CommunitySetExpr matchCondition) {
    return new CommunityListLine(requireNonNull(action), requireNonNull(matchCondition));
  }

  @Override
  public boolean equals(Object o) {
    if (o == this) {
      return true;
    } else if (!(o instanceof CommunityListLine)) {
      return false;
    }
    CommunityListLine other = (CommunityListLine) o;
    return _action == other._action && _matchCondition.equals(other._matchCondition);
  }

  /** The action the underlying access-list will take when this line matches a route. */
  @JsonProperty(PROP_ACTION)
  public @Nonnull LineAction getAction() {
    return _action;
  }

  @JsonProperty(PROP_MATCH_CONDITION)
  public @Nonnull CommunitySetExpr getMatchCondition() {
    return _matchCondition;
  }

  @Override
  public int hashCode() {
    return Objects.hash(_action.ordinal(), _matchCondition);
  }

  @Override
  public String toString() {
    return toStringHelper(getClass())
        .add(PROP_ACTION, _action)
        .add(PROP_MATCH_CONDITION, _matchCondition)
        .toString();
  }

  /** Add configuration constant - SMT symbolic variable */
  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  private transient BoolExpr _configVarAction;
  // private transient BoolExpr _configLineEnable;

  public void initSmtVariable(
      Context context, Solver solver, String configVarPrefix, boolean isTrue,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth) {
    // assert that the community list line is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("CommunityListLine.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // check and avoid shared object
    if (_matchCondition.getEnableSmtVariable()) {
      System.out.println("WARNING: CommunityListLine.initSmtVariable: " +
              "found shared CommunitySetExpr, cloning it.");

      CommunitySetExpr matchConditionBackup = _matchCondition;

      if (_matchCondition instanceof NamedCommunitySet) {
        NamedCommunitySet namedCommunitySet = (NamedCommunitySet) _matchCondition;
        _matchCondition = new NamedCommunitySet(namedCommunitySet.getName());
      } else if (_matchCondition instanceof RegexCommunitySet) {
        RegexCommunitySet regexCommunitySet = (RegexCommunitySet) _matchCondition;
        _matchCondition = new RegexCommunitySet(regexCommunitySet.getRegex());
      } else if (_matchCondition instanceof LiteralCommunitySet) {
        LiteralCommunitySet literalCommunitySet = (LiteralCommunitySet) _matchCondition;
        _matchCondition = new LiteralCommunitySet(literalCommunitySet.getCommunities());
      } else if (_matchCondition instanceof LiteralCommunity) {
        LiteralCommunity literalCommunity = (LiteralCommunity) _matchCondition;
        _matchCondition = new LiteralCommunity(literalCommunity.getCommunity());
      } else if (_matchCondition instanceof CommunityList) {
        CommunityList communityList = (CommunityList) _matchCondition;
        _matchCondition =
            new CommunityList(
                communityList.getName(), communityList.getLines(), communityList.getInvertMatch());
      } else {
        throw new BatfishException(
            "CommunityListLine.initSmtVariable: unimplemented community set type: " +
            _matchCondition.getClass().getName());
      }

      // add additional assert for using shared object
      if (matchConditionBackup.getEnableSmtVariable() == _matchCondition.getEnableSmtVariable()) {
        throw new BatfishException(
            "CommunityListLine.initSmtVariable: cloning failed for shared object.");
      }
    }

    _matchCondition.initSmtVariable(context, solver, configVarPrefix, isTrue, commsIndex, commsWidth);

    // add relevant configuration constant constraint
    _configVarAction = context.mkBoolConst(configVarPrefix + "action");
    BoolExpr configVarActionConstraint = context.mkEq(
        _configVarAction, context.mkBool(_action == LineAction.PERMIT));
    solver.add(configVarActionConstraint);

    // add the line enable flag, and default configure to true
    // _configLineEnable = context.mkBoolConst(configVarPrefix + "enable");
    // BoolExpr configLineEnableConstraint = context.mkEq(_configLineEnable, context.mkTrue());
    // solver.add(configLineEnableConstraint);

    // configure the smt variable enable flag to true
    _enableSmtVariable = true;
    _configVarPrefix = configVarPrefix;
  }

  public void initSmtVariable(
      Context context, Solver solver, String configVarPrefix,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth) {
    initSmtVariable(context, solver, configVarPrefix, true, commsIndex, commsWidth);
  }

  public boolean getEnableSmtVariable() {
    return _enableSmtVariable;
  }

  public String getConfigVarPrefix() {
    return _configVarPrefix;
  }

  public BoolExpr getConfigVarAction() {
    return _configVarAction;
  }

  // public BoolExpr getConfigLineEnable() {
  //   return _configLineEnable;
  // }
}
