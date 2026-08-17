package org.batfish.datamodel.routing_policy.statement;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import javax.annotation.ParametersAreNonnullByDefault;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.HasWritableLocalPreference;
import org.batfish.datamodel.routing_policy.Environment;
import org.batfish.datamodel.routing_policy.Result;
import org.batfish.datamodel.routing_policy.expr.ExplicitPrefixSet;
import org.batfish.datamodel.routing_policy.expr.LongExpr;
import org.batfish.datamodel.routing_policy.expr.NamedPrefixSet;

@ParametersAreNonnullByDefault
public final class SetLocalPreference extends Statement {
  private static final String PROP_LOCAL_PREFERENCE = "localPreference";

  private LongExpr _localPreference;

  @JsonCreator
  private SetLocalPreference() {}

  public SetLocalPreference(LongExpr localPreference) {
    _localPreference = localPreference;
  }

  @Override
  public <T, U> T accept(StatementVisitor<T, U> visitor, U arg) {
    return visitor.visitSetLocalPreference(this, arg);
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    }
    if (!(obj instanceof SetLocalPreference)) {
      return false;
    }
    return _localPreference.equals(((SetLocalPreference) obj)._localPreference);
  }

  @Override
  public Result execute(Environment environment) {
    if (!(environment.getOutputRoute() instanceof HasWritableLocalPreference)) {
      return new Result();
    }
    Result result = new Result();
    HasWritableLocalPreference<?, ?> outputRoute =
        (HasWritableLocalPreference<?, ?>) environment.getOutputRoute();
    long localPreference = _localPreference.evaluate(environment);
    outputRoute.setLocalPreference(localPreference);
    if (environment.getWriteToIntermediateBgpAttributes()) {
      environment.getIntermediateBgpAttributes().setLocalPreference(localPreference);
    }
    return result;
  }

  @JsonProperty(PROP_LOCAL_PREFERENCE)
  public LongExpr getLocalPreference() {
    return _localPreference;
  }

  @Override
  public int hashCode() {
    return _localPreference.hashCode();
  }

  @JsonProperty(PROP_LOCAL_PREFERENCE)
  public void setLocalPreference(LongExpr localPreference) {
    _localPreference = localPreference;
  }

  /** Add configuration constant - SMT symbolic variable */
  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  // private transient BoolExpr _configLineEnable;

  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    if (_enableSmtVariable) {
      throw new BatfishException("SetLocalPreference.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // init smt variable for local preference
    _localPreference.initSmtVariable(context, solver, configVarPrefix);

    // add the line enable flag, and default configure to true
    // _configLineEnable = context.mkBoolConst(configVarPrefix + "enable");
    // BoolExpr configLineEnableConstraint = context.mkEq(_configLineEnable, context.mkTrue());
    // solver.add(configLineEnableConstraint);

    // config the smt variable enable flag to true
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
