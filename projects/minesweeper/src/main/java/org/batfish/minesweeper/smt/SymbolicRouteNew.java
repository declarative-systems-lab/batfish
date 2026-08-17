package org.batfish.minesweeper.smt;

import com.microsoft.z3.BitVecExpr;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Expr;
import java.util.Map;
import java.util.Set;
import javax.annotation.Nullable;
import org.batfish.minesweeper.CommunityVar;
import org.batfish.minesweeper.IDeepCopy;
import org.batfish.minesweeper.Protocol;

/**
 * {@link SymbolicRouteBase} with BGP communities modeled as a single fixed-width bit-vector (one bit
 * per {@link CommunityVar} in slice order). Transfer and equality logic for this encoding are not
 * wired through {@link TransferSSA} yet; use {@link SymbolicRoute} for the legacy path.
 */
public final class SymbolicRouteNew extends SymbolicRouteBase
    implements IDeepCopy<SymbolicRouteNew> {

  private BitVecExpr _communitiesBitVec;

  SymbolicRouteNew(String name, Protocol proto) {
    super(name, proto);
    _communitiesBitVec = null;
  }

  SymbolicRouteNew(SymbolicRouteNew other) {
    super(other);
    _communitiesBitVec = other._communitiesBitVec;
  }

  SymbolicRouteNew(
      EncoderSlice slice,
      String name,
      String router,
      Protocol proto,
      Optimizations opts,
      @Nullable SymbolicEnum<Protocol> h,
      boolean isAbstract) {
    super(slice, name, router, proto, opts, h, isAbstract);
  }

  /** Returns {@code route} if it is BitVec-encoded; otherwise throws. */
  public static SymbolicRouteNew cast(SymbolicRouteBase route) {
    if (route instanceof SymbolicRouteNew) {
      return (SymbolicRouteNew) route;
    }
    throw new IllegalArgumentException("Expected SymbolicRouteNew, got " + route.getClass());
  }

  @Override
  protected void initCommunities(
      EncoderSlice slice,
      String name,
      String router,
      Protocol proto,
      Optimizations opts,
      Context ctx,
      boolean usesBgp) {
    _communitiesBitVec = null;
    if (usesBgp) {
      Set<CommunityVar> allComms = slice.getAllCommunities();
      _communitiesBitVec = ctx.mkBVConst(name + "_community", allComms.size());
    }
  }

  @Override
  protected void addCommunityExprs(Map<String, Expr> all) {
    if (_communitiesBitVec != null) {
      all.put(_communitiesBitVec.toString(), _communitiesBitVec);
    }
  }

  @Override
  public Map<CommunityVar, BoolExpr> getCommunities() {
    throw new UnsupportedOperationException(
        "SymbolicRouteNew uses BitVec community encoding; use getCommunitiesBitVec()");
  }

  @Override
  public void setCommunities(Map<CommunityVar, BoolExpr> communities) {
    throw new UnsupportedOperationException(
        "SymbolicRouteNew uses BitVec community encoding; use setCommunitiesBitVec");
  }

  @Nullable
  public BitVecExpr getCommunitiesBitVec() {
    return _communitiesBitVec;
  }

  public void setCommunitiesBitVec(@Nullable BitVecExpr communitiesBitVec) {
    _communitiesBitVec = communitiesBitVec;
  }

  @Override
  public SymbolicRouteNew copy() {
    return new SymbolicRouteNew(this);
  }

  @Override
  public SymbolicRouteNew deepCopy() {
    return copy();
  }
}
