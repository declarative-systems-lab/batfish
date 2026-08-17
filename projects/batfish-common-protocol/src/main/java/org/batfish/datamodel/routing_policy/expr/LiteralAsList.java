package org.batfish.datamodel.routing_policy.expr;

import static com.google.common.base.MoreObjects.firstNonNull;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.google.common.collect.ImmutableList;
import java.util.List;
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
public final class LiteralAsList extends AsPathListExpr {
  private static final String PROP_LIST = "list";

  @Nonnull private List<AsExpr> _list;

  @JsonCreator
  private static LiteralAsList jsonCreator(@Nullable @JsonProperty(PROP_LIST) List<AsExpr> list) {
    return new LiteralAsList(firstNonNull(list, ImmutableList.of()));
  }

  public LiteralAsList(List<AsExpr> list) {
    _list = ImmutableList.copyOf(list);
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
    LiteralAsList other = (LiteralAsList) obj;
    return _list.equals(other._list);
  }

  @Override
  public List<Long> evaluate(Environment environment) {
    return _list.stream()
        .map(expr -> expr.evaluate(environment))
        .collect(ImmutableList.toImmutableList());
  }

  @JsonProperty(PROP_LIST)
  @Nonnull
  public List<AsExpr> getList() {
    return _list;
  }

  @Override
  public int hashCode() {
    final int prime = 31;
    int result = 1;
    result = prime * result + _list.hashCode();
    return result;
  }

  public void setList(List<AsExpr> list) {
    _list = ImmutableList.copyOf(list);
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  // private transient ArithExpr _configVarPrepend;    // Inherited from the parent class

  @Override
  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the prefix is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("LiteralAsList.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    _configVarPrepend = context.mkIntConst(configVarPrefix + "cost");
    BoolExpr configVarPrependConstraint =
        context.mkEq(_configVarPrepend, context.mkInt(_list.size()));
    solver.add(configVarPrependConstraint);

    // config the smt variable enable flag to true
    _enableSmtVariable = true;
    _configVarPrefix = configVarPrefix;
  }
}
