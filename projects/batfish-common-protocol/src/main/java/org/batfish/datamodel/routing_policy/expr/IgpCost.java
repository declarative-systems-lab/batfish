package org.batfish.datamodel.routing_policy.expr;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.routing_policy.Environment;

public class IgpCost extends LongExpr {

  @Override
  public <T, U> T accept(LongExprVisitor<T, U> visitor, U arg) {
    return visitor.visitIgpCost(this, arg);
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
    return true;
  }

  @Override
  public long evaluate(Environment environment) {
    return environment.getOriginalRoute().getMetric();
  }

  @Override
  public int hashCode() {
    final int prime = 31;
    int result = 1;
    result = prime * result + 0x12345678;
    return result;
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  @Override
  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // TODO: implement me when needed
    throw new BatfishException("IgpCost.initSmtVariable: not implemented yet.");
  }

  /** Add get literal long value for configVarPrefix */
  @Override
  public String getLiteralLongString() {
    // TODO: implement ne when needed
    throw new BatfishException("IgpCost.getLiteralLongString: not implemented yet.");
  }
}
