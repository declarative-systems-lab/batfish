package org.batfish.datamodel.routing_policy.expr;

import static com.google.common.base.Preconditions.checkArgument;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Objects;
import javax.annotation.Nullable;
import javax.annotation.ParametersAreNonnullByDefault;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.Prefix;
import org.batfish.datamodel.RouteFilterList;
import org.batfish.datamodel.routing_policy.Environment;

/** Expression for matching a {@link Prefix} against a named {@link RouteFilterList}. */
@ParametersAreNonnullByDefault
public final class NamedPrefixSet extends PrefixSetExpr {
  private static final String PROP_NAME = "name";

  private final String _name;

  @JsonCreator
  private static NamedPrefixSet create(@Nullable @JsonProperty(PROP_NAME) String name) {
    checkArgument(name != null, "%s must be provided", PROP_NAME);
    return new NamedPrefixSet(name);
  }

  public NamedPrefixSet(String name) {
    _name = name;

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    }
    if (!(obj instanceof NamedPrefixSet)) {
      return false;
    }
    NamedPrefixSet other = (NamedPrefixSet) obj;
    return Objects.equals(_name, other._name);
  }

  @JsonProperty(PROP_NAME)
  public String getName() {
    return _name;
  }

  @Override
  public int hashCode() {
    return Objects.hashCode(_name);
  }

  @Override
  public boolean matches(Prefix prefix, Environment environment) {
    RouteFilterList list = environment.getRouteFilterLists().get(_name);
    if (list != null) {
      return list.permits(prefix);
    } else {
      environment.setError(true);
      return false;
    }
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  @Override
  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the named prefix set is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("NamedPrefixSet.initSmtVariable: shared object.\n" +
              "Previous configVarPrefix: " + _configVarPrefix + "\n" +
              "Current  configVarPrefix: " + configVarPrefix);
    }

    // do nothing, just refer to the RouteFilterList object according to parameter _name

    // configure the smt variable enable flag to true
    _enableSmtVariable = true;
  }
}
