package org.batfish.datamodel;

import static com.google.common.base.Preconditions.checkArgument;
import static org.batfish.datamodel.IpWildcard.ipWithWildcardMask;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.google.common.base.MoreObjects;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;

import java.io.Serializable;
import java.util.Objects;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;
import javax.annotation.ParametersAreNonnullByDefault;

import org.batfish.common.BatfishException;

/** A line in a {@link RouteFilterList}. */
@ParametersAreNonnullByDefault
public final class RouteFilterLine implements Serializable {
  private static final String PROP_ACTION = "action";
  private static final String PROP_LENGTH_RANGE = "lengthRange";
  private static final String PROP_IP_WILDCARD = "ipWildcard";

  private final @Nonnull LineAction _action;
  private /*final*/ @Nonnull IpWildcard _ipWildcard;
  private /*final*/ @Nonnull SubRange _lengthRange;

  /** Route filter line that permits all routes */
  public static final RouteFilterLine PERMIT_ALL =
      new RouteFilterLine(
          LineAction.PERMIT, Prefix.ZERO, new SubRange(0, Prefix.MAX_PREFIX_LENGTH));

  @JsonCreator
  private static RouteFilterLine create(
      @Nullable @JsonProperty(PROP_ACTION) LineAction action,
      @Nullable @JsonProperty(PROP_IP_WILDCARD) IpWildcard ipWildcard,
      @Nullable @JsonProperty(PROP_LENGTH_RANGE) SubRange lengthRange) {
    checkArgument(action != null, "% is missing", PROP_ACTION);
    checkArgument(ipWildcard != null, "% is missing", PROP_IP_WILDCARD);
    checkArgument(lengthRange != null, "% is missing", PROP_LENGTH_RANGE);
    return new RouteFilterLine(action, ipWildcard, lengthRange);
  }

  public RouteFilterLine(LineAction action, IpWildcard ipWildcard, SubRange lengthRange) {
    _action = action;
    _ipWildcard = ipWildcard;
    _lengthRange = lengthRange;

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  public RouteFilterLine(LineAction action, Prefix prefix, SubRange lengthRange) {
    this(action, IpWildcard.create(prefix), lengthRange);
  }

  public RouteFilterLine(LineAction action, PrefixRange prefixRange) {
    this(action, IpWildcard.create(prefixRange.getPrefix()), prefixRange.getLengthRange());
  }

  @Override
  public boolean equals(@Nullable Object o) {
    if (o == this) {
      return true;
    } else if (!(o instanceof RouteFilterLine)) {
      return false;
    }

    RouteFilterLine other = (RouteFilterLine) o;
    return _action == other._action
        && _lengthRange.equals(other._lengthRange)
        && _ipWildcard.equals(other._ipWildcard);
  }

  /** The action the underlying access-list will take when this line matches an IPV4 route. */
  @JsonProperty(PROP_ACTION)
  public @Nonnull LineAction getAction() {
    return _action;
  }

  /** The range of acceptable prefix-lengths for a route. */
  @JsonProperty(PROP_LENGTH_RANGE)
  public @Nonnull SubRange getLengthRange() {
    return _lengthRange;
  }

  /**
   * The bits against which to compare a route's prefix. The mask of this IP Wildcard determines
   * which bits must match.
   */
  @JsonProperty(PROP_IP_WILDCARD)
  public @Nonnull IpWildcard getIpWildcard() {
    return _ipWildcard;
  }

  @Override
  public int hashCode() {
    return Objects.hash(_action.ordinal(), _lengthRange, _ipWildcard);
  }

  @Override
  public String toString() {
    return MoreObjects.toStringHelper(getClass())
        .add("Action", _action)
        .add("IpWildCard", _ipWildcard)
        .add("LengthRange", _lengthRange)
        .toString();
  }

  /** Add configuration constant - SMT symbolic variable */
  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  private transient BoolExpr _configVarAction;
  // private transient BoolExpr _configLineEnable;

  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert the route filter list is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("RouteFilterLine.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // check and avoid shared object for IpWildcard
    if (_ipWildcard.getEnableSmtVariable()) {
      System.out.println("WARNING: RouteFilterLine.initSmtVariable: " +
          "found shared IpWildcard, cloning it.");

      IpWildcard ipWildcardBackup = _ipWildcard;
      _ipWildcard =
          IpWildcard.ipWithWildcardMask(_ipWildcard.getIp(), _ipWildcard.getWildcardMask());

      // add additional assert for using shared object
      if (ipWildcardBackup.getEnableSmtVariable() == _ipWildcard.getEnableSmtVariable()) {
        throw new BatfishException("RouteFilterLine.initSmtVariable: " +
            "cloning failed for shared object.");
      }
    }

    // check and avoid shared object for SubRange
    if (_lengthRange.getEnableSmtVariable()) {
      System.out.println("WARNING: RouteFilterLine.initSmtVariable: " +
          "found shared SubRange, cloning it.");

      SubRange lengthRangeBackup = _lengthRange;
      _lengthRange = new SubRange(_lengthRange.getStart(), _lengthRange.getEnd());

      // add additional assert for using shared object
      if (lengthRangeBackup.getEnableSmtVariable() == _lengthRange.getEnableSmtVariable()) {
        throw new BatfishException("RouteFilterLine.initSmtVariable: " +
            "cloning failed for shared object.");
      }
    }

    _ipWildcard.initSmtVariable(context, solver, configVarPrefix);
    _lengthRange.initSmtVariable(context, solver, configVarPrefix);

    _configVarAction = context.mkBoolConst(configVarPrefix + "action");

    // add relevant configuration constant constraint
    BoolExpr configVarActionConstraint = context.mkEq(
            _configVarAction, context.mkBool(_action == LineAction.PERMIT));
    solver.add(configVarActionConstraint);

    // add relevant configuration constant constraint (ge / le / eq with prefix length)
    BoolExpr rangeStartGePrefixLength =
        context.mkGe(_lengthRange.getConfigVarStart(), _ipWildcard.getConfigVarLength());
    BoolExpr rangeEndGePrefixLength =
        context.mkGe(_lengthRange.getConfigVarEnd(), _ipWildcard.getConfigVarLength());
    solver.add(rangeStartGePrefixLength);
    solver.add(rangeEndGePrefixLength);

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

  public BoolExpr getConfigVarAction() {
    return _configVarAction;
  }

  // public BoolExpr getConfigLineEnable() {
  //   return _configLineEnable;
  // }
}
