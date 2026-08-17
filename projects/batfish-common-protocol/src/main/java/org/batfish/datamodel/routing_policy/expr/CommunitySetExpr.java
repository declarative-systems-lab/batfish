package org.batfish.datamodel.routing_policy.expr;

import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.google.common.collect.ImmutableSet;
import com.google.common.collect.ImmutableMap;
import java.io.Serializable;
import java.util.Set;
import java.math.BigInteger;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;

import com.microsoft.z3.BoolExpr;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.bgp.community.Community;
import org.batfish.datamodel.routing_policy.Environment;
import org.batfish.datamodel.visitors.CommunitySetExprVisitor;
import org.batfish.datamodel.visitors.VoidCommunitySetExprVisitor;
import org.batfish.datamodel.bgp.community.ExtendedCommunity;
import org.batfish.datamodel.bgp.community.StandardCommunity;
import org.batfish.datamodel.bgp.community.LargeCommunity;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BitVecExpr;

@JsonTypeInfo(use = JsonTypeInfo.Id.CLASS, property = "class")
public abstract class CommunitySetExpr implements Serializable {

  public abstract <T> T accept(CommunitySetExprVisitor<T> visitor);

  public abstract void accept(VoidCommunitySetExprVisitor visitor);

  /**
   * Returns the set of all literal communities represented by this {@link CommunitySetExpr}.<br>
   * {@code environment} is used to resolve references to named {@link
   * org.batfish.datamodel.CommunityList}s.
   *
   * @throws UnsupportedOperationException if this {@link CommunitySetExpr} does not represent a set
   *     of literal communities.
   */
  public abstract @Nonnull Set<Community> asLiteralCommunities(@Nonnull Environment environment);

  /**
   * Whether membership of a single community in this {@link CommunitySetExpr} cannot be statically
   * determined.
   */
  public abstract boolean dynamicMatchCommunity();

  @Override
  public abstract boolean equals(Object obj);

  @Override
  public abstract int hashCode();

  /**
   * Returns true iff any of the given {@code communityCandidates} is matched by this {@link
   * CommunitySetExpr} under the provided {@code environment}.
   */
  public boolean matchAnyCommunity(Environment environment, Set<Community> communityCandidates) {
    for (Community communityCandidate : communityCandidates) {
      if (matchCommunity(environment, communityCandidate)) {
        return true;
      }
    }
    return false;
  }

  /**
   * Returns true iff the given {@code communitySetCandidate} as a whole is matched by this {@link
   * CommunitySetExpr} under the provided {@code environment}.
   */
  public abstract boolean matchCommunities(
      Environment environment, Set<Community> communitySetCandidate);

  /**
   * Returns true iff the given {@code community} is matched by this {@link CommunitySetExpr} under
   * the provided {@code environment}.
   */
  public abstract boolean matchCommunity(Environment environment, Community community);

  /**
   * Returns the subset of the given {@code communityCandidates} matched by this {@link
   * CommunitySetExpr} under the provided {@code environment}.
   */
  public Set<Community> matchedCommunities(
      @Nullable Environment environment, Set<Community> communityCandidates) {
    return communityCandidates.stream()
        .filter(communityCandidate -> matchCommunity(environment, communityCandidate))
        .collect(ImmutableSet.toImmutableSet());
  }

  /**
   * Whether checking membership of a candidate set of communities as a whole in this {@link
   * CommunitySetExpr} can be reduced to checking individual membership of any community from the
   * candidate set in. This must be {@code false} e.g. if this {@link CommunitySetExpr} only matches
   * community-sets with at least two elements.
   */
  public abstract boolean reducible();

  /** Add configuration constant - SMT symbolic variable */
  protected boolean _enableSmtVariable;
  protected String _configVarPrefix;

  public abstract void initSmtVariable(
      Context context, Solver solver, String configVarPrefix, boolean isTrue,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth);
  public abstract void initSmtVariable(
      Context context, Solver solver, String configVarPrefix,
      ImmutableMap<Community, Integer> commsIndex, int commsWidth);

  public boolean getEnableSmtVariable() {
    return _enableSmtVariable;
  }

  public String getConfigVarPrefix() {
    return _configVarPrefix;
  }

  // clone a community
  protected Community cloneCommunity(Community community) {
    if (community instanceof ExtendedCommunity) {
      ExtendedCommunity e = (ExtendedCommunity) community;
      return ExtendedCommunity.of(
          e.getSubType(), e.getGlobalAdministrator(), e.getLocalAdministrator());
    } else if (community instanceof StandardCommunity) {
      StandardCommunity s = (StandardCommunity) community;
      return StandardCommunity.of(s.asLong());
    } else if (community instanceof LargeCommunity) {
      LargeCommunity l = (LargeCommunity) community;
      return LargeCommunity.of(
          l.getGlobalAdministrator(), l.getLocalData1(), l.getLocalData2());
    }

    // only has three subclasses of Community
    throw new BatfishException(
            "CommunitySetExpr.cloneCommunity: unknown community type: " + community.getClass().getName());
  }

  // Community Index -> Community BitVec
  // TODO: improve long type to support more communities
  protected String communityString(Integer index) {
    BigInteger comm = BigInteger.ONE.shiftLeft(index);
    return comm.toString();
  }
}
