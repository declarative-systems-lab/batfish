package org.batfish.datamodel.routing_policy.expr;

import com.fasterxml.jackson.annotation.JsonTypeInfo;
import java.io.Serializable;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.datamodel.routing_policy.Environment;

@JsonTypeInfo(use = JsonTypeInfo.Id.CLASS, property = "class")
public abstract class LongExpr implements Serializable {

  public abstract <T, U> T accept(LongExprVisitor<T, U> visitor, U arg);

  @Override
  public abstract boolean equals(Object obj);

  public abstract long evaluate(Environment environment);

  @Override
  public abstract int hashCode();

  /** Add configuration constant - SMT symbolic variable */
  public abstract void initSmtVariable(Context context, Solver solver, String configVarPrefix);

  /** Add get literal long value for configVarPrefix */
  protected boolean _enableSmtVariable;
  protected String _configVarPrefix;

  public abstract String getLiteralLongString();

  public boolean getEnableSmtVariable() {
    return _enableSmtVariable;
  }

  public String getConfigVarPrefix() {
    return _configVarPrefix;
  }
}
