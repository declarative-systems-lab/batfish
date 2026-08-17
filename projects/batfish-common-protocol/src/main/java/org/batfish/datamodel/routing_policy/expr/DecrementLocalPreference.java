package org.batfish.datamodel.routing_policy.expr;

import static com.google.common.base.Preconditions.checkArgument;
import static org.batfish.datamodel.BgpRoute.MAX_LOCAL_PREFERENCE;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.microsoft.z3.ArithExpr;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.HasReadableLocalPreference;
import org.batfish.datamodel.routing_policy.Environment;

public final class DecrementLocalPreference extends LongExpr {

  private long _subtrahend;

  @JsonCreator
  private DecrementLocalPreference() {}

  public DecrementLocalPreference(long subtrahend) {
    checkArgument(
        subtrahend >= 0,
        "To subtract a negative number (%s), use IncrementLocalPreference",
        subtrahend);
    checkArgument(
        subtrahend <= MAX_LOCAL_PREFERENCE,
        "Value (%s) is out of range for local preference",
        subtrahend);
    _subtrahend = subtrahend;

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  @Override
  public <T, U> T accept(LongExprVisitor<T, U> visitor, U arg) {
    return visitor.visitDecrementLocalPreference(this, arg);
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    } else if (!(obj instanceof DecrementLocalPreference)) {
      return false;
    }
    return _subtrahend == ((DecrementLocalPreference) obj)._subtrahend;
  }

  @Override
  public long evaluate(Environment environment) {
    long oldLocalPreference;
    if (environment.getReadFromIntermediateBgpAttributes()) {
      oldLocalPreference = environment.getIntermediateBgpAttributes().getLocalPreference();
    } else if (!(environment.getOriginalRoute() instanceof HasReadableLocalPreference)) {
      oldLocalPreference = 0L;
    } else {
      HasReadableLocalPreference oldRoute =
          (HasReadableLocalPreference) environment.getOriginalRoute();
      oldLocalPreference = oldRoute.getLocalPreference();
    }
    return Math.max(oldLocalPreference - _subtrahend, 0L);
  }

  public long getSubtrahend() {
    return _subtrahend;
  }

  @Override
  public int hashCode() {
    return Long.hashCode(_subtrahend);
  }

  public void setSubtrahend(long subtrahend) {
    _subtrahend = subtrahend;
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  private transient ArithExpr _configVarLocalpreference;

  @Override
  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the literal long value is not shared object
    if (_enableSmtVariable) {
      throw new BatfishException("DecrementLocalPreference.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // init smt variable for literal long value
    _configVarLocalpreference = context.mkIntConst(configVarPrefix);
    // add relevant configuration constant constraints
    BoolExpr configVarLpConstraint = context.mkEq(
        _configVarLocalpreference, context.mkInt(_subtrahend));
    solver.add(configVarLpConstraint);

    // config the smt variable enable flag to true
    _enableSmtVariable = true;
    _configVarPrefix = configVarPrefix;
  }

  public ArithExpr getConfigVarLocalpreference() {
    return _configVarLocalpreference;
  }

  /** Add get literal long value for configVarPrefix */
  @Override
  public String getLiteralLongString() {
    return String.valueOf(_subtrahend);
  }
}
