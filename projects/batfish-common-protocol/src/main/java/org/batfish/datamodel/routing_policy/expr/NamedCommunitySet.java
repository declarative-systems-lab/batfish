package org.batfish.datamodel.routing_policy.expr;

import static java.util.Objects.requireNonNull;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.google.common.collect.ImmutableMap;
import java.util.Set;
import javax.annotation.Nonnull;

import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.bgp.community.Community;
import org.batfish.datamodel.routing_policy.Environment;
import org.batfish.datamodel.visitors.CommunitySetExprVisitor;
import org.batfish.datamodel.visitors.VoidCommunitySetExprVisitor;

public class NamedCommunitySet extends CommunitySetExpr {
  private static final String PROP_NAME = "name";

  @JsonCreator
  private static NamedCommunitySet create(@JsonProperty(PROP_NAME) String name) {
    return new NamedCommunitySet(requireNonNull(name));
  }

  private final String _name;

  public NamedCommunitySet(@Nonnull String name) {
    _name = name;

    // initialize enable smt variable flag to true
    _enableSmtVariable = false;
  }

  @Override
  public <T> T accept(CommunitySetExprVisitor<T> visitor) {
    return visitor.visitNamedCommunitySet(this);
  }

  @Override
  public void accept(VoidCommunitySetExprVisitor visitor) {
    visitor.visitNamedCommunitySet(this);
  }

  @Nonnull
  @Override
  public Set<Community> asLiteralCommunities(@Nonnull Environment environment) {
    return resolve(environment).asLiteralCommunities(environment);
  }

  @Override
  public final boolean dynamicMatchCommunity() {
    return true;
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    }
    if (!(obj instanceof NamedCommunitySet)) {
      return false;
    }
    return _name.equals(((NamedCommunitySet) obj)._name);
  }

  @JsonProperty(PROP_NAME)
  public String getName() {
    return _name;
  }

  @Override
  public int hashCode() {
    return _name.hashCode();
  }

  @Override
  public boolean matchAnyCommunity(Environment environment, Set<Community> communityCandidates) {
    return resolve(environment).matchAnyCommunity(environment, communityCandidates);
  }

  @Override
  public boolean matchCommunities(Environment environment, Set<Community> communitySetCandidate) {
    return resolve(environment).matchCommunities(environment, communitySetCandidate);
  }

  @Override
  public boolean matchCommunity(Environment environment, Community community) {
    return environment.getCommunityLists().get(_name).matchCommunity(environment, community);
  }

  @Override
  public Set<Community> matchedCommunities(
      Environment environment, Set<Community> communityCandidates) {
    return resolve(environment).matchedCommunities(environment, communityCandidates);
  }

  @Override
  public boolean reducible() {
    return false;
  }

  private @Nonnull CommunitySetExpr resolve(@Nonnull Environment environment) {
    return requireNonNull(environment.getCommunityLists().get(_name));
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  @Override
  public void initSmtVariable(
      Context context, Solver solver, String configVarPrefix, boolean isTrue,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth) {
    // assert that the named community set is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("NamedCommunitySet.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // NOTE: do nothing, just refer to the RouteFilterList object
    //       according to the parameter _name

    // configure the smt variable enable flag to true
    _enableSmtVariable = true;
    _configVarPrefix = configVarPrefix;
  }

  @Override
  public void initSmtVariable(
      Context context, Solver solver, String configVarPrefix,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth) {
    initSmtVariable(context, solver, configVarPrefix, true, commsIndex, commsWidth);
  }
}
