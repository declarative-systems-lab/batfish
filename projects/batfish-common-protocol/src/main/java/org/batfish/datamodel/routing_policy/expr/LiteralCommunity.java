package org.batfish.datamodel.routing_policy.expr;

import static com.google.common.base.MoreObjects.toStringHelper;
import static com.google.common.base.Preconditions.checkArgument;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.google.common.collect.ImmutableSet;
import com.google.common.collect.ImmutableMap;
import java.util.Set;
import java.math.BigInteger;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;
import javax.annotation.ParametersAreNonnullByDefault;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.BitVecExpr;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.bgp.community.Community;
import org.batfish.datamodel.bgp.community.ExtendedCommunity;
import org.batfish.datamodel.bgp.community.StandardCommunity;
import org.batfish.datamodel.bgp.community.LargeCommunity;
import org.batfish.datamodel.routing_policy.Environment;
import org.batfish.datamodel.visitors.CommunitySetExprVisitor;
import org.batfish.datamodel.visitors.VoidCommunitySetExprVisitor;

import org.batfish.common.util.SymbolicUtil;

/**
 * A {@link CommunitySetExpr} matching community-sets that contain at least the community returned
 * by {@link #getCommunity()}.
 */
@ParametersAreNonnullByDefault
public class LiteralCommunity extends CommunitySetExpr {
  private static final String PROP_COMMUNITY = "community";

  @JsonCreator
  private static @Nonnull LiteralCommunity create(
      @Nullable @JsonProperty(PROP_COMMUNITY) Community community) {
    checkArgument(community != null);
    return new LiteralCommunity(community);
  }

  private /*final*/ Community _community;

  public LiteralCommunity(Community community) {
    _community = community;

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  @Override
  public <T> T accept(CommunitySetExprVisitor<T> visitor) {
    return visitor.visitLiteralCommunity(this);
  }

  @Override
  public void accept(VoidCommunitySetExprVisitor visitor) {
    visitor.visitLiteralCommunity(this);
  }

  /**
   * When treated as a literal set of communities, {@link LiteralCommunity} represents the singleton
   * set of the community returned by {@link #getCommunity}.
   */
  @Nonnull
  @Override
  public Set<Community> asLiteralCommunities(Environment environment) {
    return ImmutableSet.of(_community);
  }

  @Override
  public boolean dynamicMatchCommunity() {
    return false;
  }

  @Override
  public boolean equals(Object obj) {
    if (this == obj) {
      return true;
    }
    if (!(obj instanceof LiteralCommunity)) {
      return false;
    }
    return _community.equals(((LiteralCommunity) obj)._community);
  }

  @JsonProperty(PROP_COMMUNITY)
  public Community getCommunity() {
    return _community;
  }

  @Override
  public int hashCode() {
    return _community.hashCode();
  }

  @Override
  public boolean matchCommunities(Environment environment, Set<Community> communitySetCandidate) {
    return communitySetCandidate.contains(_community);
  }

  @Override
  public boolean matchCommunity(Environment environment, Community community) {
    return _community.equals(community);
  }

  @Override
  public boolean reducible() {
    return true;
  }

  @Override
  public String toString() {
    return toStringHelper(getClass()).add(PROP_COMMUNITY, _community).toString();
  }

  /** Add configuration constant - SMT symbolic variable */
  // private boolean _enableSmtVariable;    // Inherited from the parent class
  // private String _configVarPrefix;       // Inherited from the parent class

  public void initSmtVariable(
      Context context, Solver solver, String configVarPrefix, boolean isTrue,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth) {
    // assert that the literal community is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("LiteralCommunity.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // check and avoid shared object
    if (_community.getEnableSmtVariable()) {
      System.out.println("WARNING: LiteralCommunity.initSmtVariable: " +
          "found shared Community, cloning it.");

      Community communityBackup = _community;
      // clone community shared object
      _community = cloneCommunity(_community);

      // add additional assert for using shared object
      if (communityBackup.getEnableSmtVariable() == _community.getEnableSmtVariable()) {
        throw new BatfishException("LiteralCommunity.initSmtVariable: " +
            "cloning failed for shared object.");
      }
    }

    // init smt variable for literal community
    String configVarPrefixUpdated =
        configVarPrefix + SymbolicUtil.format(_community.getCommunityString()) + "_";
    BitVecExpr communityValue = null;
    if (null != commsIndex.get(_community)) {
      communityValue = context.mkBV(communityString(commsIndex.get(_community)), commsWidth);
    } else {
      throw new BatfishException("LiteralCommunity.initSmtVariable: " +
          "community not found in commsIndex: " + _community.getCommunityString());
    }
    _community.initSmtVariable(
        context, solver, configVarPrefixUpdated, isTrue, communityValue, commsWidth);

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
