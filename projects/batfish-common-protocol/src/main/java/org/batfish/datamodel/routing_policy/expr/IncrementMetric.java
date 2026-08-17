package org.batfish.datamodel.routing_policy.expr;

import static com.google.common.base.Preconditions.checkArgument;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;
import javax.annotation.ParametersAreNonnullByDefault;

import com.microsoft.z3.ArithExpr;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.routing_policy.Environment;

@ParametersAreNonnullByDefault
public final class IncrementMetric extends LongExpr {
  private static final String PROP_ADDEND = "addend";
  private static final long MAX_INT_VALUE = 0xFFFFFFFFL;

  @Nonnull private long _addend;

  @JsonCreator
  private static IncrementMetric jsonCreator(@Nullable @JsonProperty(PROP_ADDEND) Long addend) {
    checkArgument(addend != null, "%s must be provided", PROP_ADDEND);
    return new IncrementMetric(addend);
  }

  public IncrementMetric(long addend) {
    _addend = addend;

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  @Override
  public <T, U> T accept(LongExprVisitor<T, U> visitor, U arg) {
    return visitor.visitIncrementMetric(this, arg);
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    } else if (!(obj instanceof IncrementMetric)) {
      return false;
    }
    IncrementMetric other = (IncrementMetric) obj;
    return _addend == other._addend;
  }

  @Override
  public long evaluate(Environment environment) {
    long oldMetric = environment.getOriginalRoute().getMetric();
    long newVal = Math.min(oldMetric + _addend, MAX_INT_VALUE);
    return newVal;
  }

  @JsonProperty(PROP_ADDEND)
  public long getAddend() {
    return _addend;
  }

  @Override
  public int hashCode() {
    final int prime = 31;
    int result = 1;
    result = prime * result + Long.hashCode(_addend);
    return result;
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  private transient ArithExpr _configVarLocalpreference;

  @Override
  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the literal long value is not shared object
    if (_enableSmtVariable) {
      throw new BatfishException("IncrementMetric.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // init smt variable for literal long value
    _configVarLocalpreference = context.mkIntConst(configVarPrefix);
    // add relevant configuration constant constraints
    BoolExpr configVarLpConstraint = context.mkEq(
        _configVarLocalpreference, context.mkInt(_addend));
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
    return String.valueOf(_addend);
  }
}
