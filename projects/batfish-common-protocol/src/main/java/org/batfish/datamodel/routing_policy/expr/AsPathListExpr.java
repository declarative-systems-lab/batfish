package org.batfish.datamodel.routing_policy.expr;

import com.fasterxml.jackson.annotation.JsonTypeInfo;
import java.io.Serializable;
import java.util.List;

import com.microsoft.z3.ArithExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.datamodel.routing_policy.Environment;

@JsonTypeInfo(use = JsonTypeInfo.Id.CLASS, property = "class")
public abstract class AsPathListExpr implements Serializable {

  @Override
  public abstract boolean equals(Object obj);

  public abstract List<Long> evaluate(Environment environment);

  @Override
  public abstract int hashCode();

  /** Add configuration constant - SMT symbolic variable */
  protected boolean _enableSmtVariable;
  protected String _configVarPrefix;

  protected transient ArithExpr _configVarPrepend;

  public abstract void initSmtVariable(Context context, Solver solver, String configVarPrefix);

  public boolean getEnableSmtVariable() {
    return _enableSmtVariable;
  }

  public String getConfigVarPrefix() {
    return _configVarPrefix;
  }

  public ArithExpr getConfigVarPrepend() {
    return _configVarPrepend;
  }
}
