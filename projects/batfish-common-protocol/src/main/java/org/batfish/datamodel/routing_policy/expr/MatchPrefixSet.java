package org.batfish.datamodel.routing_policy.expr;

import static com.google.common.base.Preconditions.checkArgument;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Objects;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;
import javax.annotation.ParametersAreNonnullByDefault;
import javax.print.attribute.standard.Destination;

import org.batfish.common.BatfishException;
import org.batfish.datamodel.CommunityListLine;
import org.batfish.datamodel.Prefix;
import org.batfish.datamodel.routing_policy.Environment;
import org.batfish.datamodel.routing_policy.Result;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;

/**
 * Boolean expression that tests whether an IPv4 prefix extracted from an {@link Environment} using
 * a given {@link PrefixExpr} matches a given {@link PrefixSetExpr}.
 */
@ParametersAreNonnullByDefault
public final class MatchPrefixSet extends BooleanExpr {

  private static final String PROP_PREFIX = "prefix";
  private static final String PROP_PREFIX_SET = "prefixSet";

  @Nonnull private final PrefixExpr _prefix;
  @Nonnull private /*final*/ PrefixSetExpr _prefixSet;

  @JsonCreator
  private static MatchPrefixSet jsonCreator(
      @Nullable @JsonProperty(PROP_PREFIX) PrefixExpr prefix,
      @Nullable @JsonProperty(PROP_PREFIX_SET) PrefixSetExpr prefixSet,
      @Nullable @JsonProperty(PROP_COMMENT) String comment) {
    checkArgument(prefix != null, "%s must be provided", PROP_PREFIX);
    checkArgument(prefixSet != null, "%s must be provided", PROP_PREFIX_SET);
    MatchPrefixSet ret = new MatchPrefixSet(prefix, prefixSet);
    ret.setComment(comment);
    return ret;
  }

  public MatchPrefixSet(PrefixExpr prefix, PrefixSetExpr prefixSet) {
    _prefix = prefix;
    _prefixSet = prefixSet;
  }

  @Override
  public <T, U> T accept(BooleanExprVisitor<T, U> visitor, U arg) {
    return visitor.visitMatchPrefixSet(this, arg);
  }

  @Override
  public Result evaluate(Environment environment) {
    Prefix prefix = _prefix.evaluate(environment);
    return new Result(_prefixSet.matches(prefix, environment));
  }

  @JsonProperty(PROP_PREFIX)
  @Nonnull
  public PrefixExpr getPrefix() {
    return _prefix;
  }

  @JsonProperty(PROP_PREFIX_SET)
  @Nonnull
  public PrefixSetExpr getPrefixSet() {
    return _prefixSet;
  }

  @Override
  public boolean equals(@Nullable Object obj) {
    if (this == obj) {
      return true;
    } else if (!(obj instanceof MatchPrefixSet)) {
      return false;
    }
    MatchPrefixSet other = (MatchPrefixSet) obj;
    return Objects.equals(_prefix, other._prefix) && Objects.equals(_prefixSet, other._prefixSet);
  }

  @Override
  public int hashCode() {
    return Objects.hash(_prefix, _prefixSet);
  }

  @Override
  public String toString() {
    return toStringHelper().add(PROP_PREFIX, _prefix).add(PROP_PREFIX_SET, _prefixSet).toString();
  }

  /** Add configuration constant - SMT symbolic variable */
  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  // private transient BoolExpr _configLineEnable;

  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the ip wildcard is not shared object
    if (_enableSmtVariable) {
      if (_prefix instanceof DestinationNetwork) {
        if (_configVarPrefix.contains("RoutingPolicy_BGP_COMMON_EXPORT_POLICY_default") &&
            configVarPrefix.contains("RoutingPolicy_BGP_REDISTRIBUTION_default")) {
          System.out.println("WARNING: MatchPrefixSet:initSmtVariable called twice, ignored.");
          return;
        }
      }

      throw new BatfishException("MatchPrefixSet.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // check and avoid shared object
    // assert that init smt variable for unimplemented prefix set type
    if (_prefixSet instanceof ExplicitPrefixSet) {
      ExplicitPrefixSet explicitPrefixSet = (ExplicitPrefixSet) _prefixSet;

      if (explicitPrefixSet.getEnableSmtVariable()) {
        System.out.println("WARNING: MatchPrefixSet:initSmtVariable: found shared PrefixSpace, cloning it.");

        ExplicitPrefixSet prefixSetBackup = (ExplicitPrefixSet) _prefixSet;
        _prefixSet = new ExplicitPrefixSet(explicitPrefixSet.getPrefixSpace());

        // add additional assert for using shared object
        if (prefixSetBackup.getEnableSmtVariable() == _prefixSet.getEnableSmtVariable()) {
          throw new BatfishException("MatchPrefixSet:initSmtVariable: " +
              "cloning failed for shared object.");
        }
      }

    } else if (_prefixSet instanceof NamedPrefixSet) {
      // NamedPrefixSet namedPrefixSet = (NamedPrefixSet) _prefixSet;
      {}  // do nothing

    } else {
      throw new BatfishException("MatchPrefixSet:initSmtVariable: Unimplemented prefix set type: " +
          _prefixSet.getClass().getName());
    }

    // init smt variable for prefix set configuration
    _prefixSet.initSmtVariable(context, solver, configVarPrefix);

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
