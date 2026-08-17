package org.batfish.datamodel.routing_policy.expr;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.ArithExpr;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.routing_policy.Environment;

public class LiteralLong extends LongExpr {
  private static final String PROP_VALUE = "value";

  private long _value;

  @JsonCreator
  private LiteralLong() {}

  public LiteralLong(long value) {
    _value = value;

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  @Override
  public <T, U> T accept(LongExprVisitor<T, U> visitor, U arg) {
    return visitor.visitLiteralLong(this, arg);
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    }
    if (obj == null) {
      return false;
    }
    if (getClass() != obj.getClass()) {
      return false;
    }
    LiteralLong other = (LiteralLong) obj;
    if (_value != other._value) {
      return false;
    }
    return true;
  }

  @Override
  public long evaluate(Environment environment) {
    return _value;
  }

  @JsonProperty(PROP_VALUE)
  public long getValue() {
    return _value;
  }

  @Override
  public int hashCode() {
    final int prime = 31;
    int result = 1;
    result = prime * result + (int) (_value ^ (_value >>> 32));
    return result;
  }

  @JsonProperty(PROP_VALUE)
  public void setValue(long value) {
    _value = value;
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  private transient ArithExpr _configVarLocalpreference;

  @Override
  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the literal long value is not shared object
    if (_enableSmtVariable) {
      throw new BatfishException("LiteralLong.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // init smt variable for literal long value
    _configVarLocalpreference = context.mkIntConst(configVarPrefix);
    // add relevant configuration constant constraints
    BoolExpr configVarLpConstraint = context.mkEq(
        _configVarLocalpreference, context.mkInt(_value));
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
    return String.valueOf(_value);
  }
}
