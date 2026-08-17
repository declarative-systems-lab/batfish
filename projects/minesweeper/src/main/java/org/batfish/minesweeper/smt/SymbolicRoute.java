package org.batfish.minesweeper.smt;

import com.microsoft.z3.BitVecExpr;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Expr;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import javax.annotation.Nullable;
import org.batfish.minesweeper.CommunityVar;
import org.batfish.minesweeper.IDeepCopy;
import org.batfish.minesweeper.Protocol;

/**
 * {@link SymbolicRouteBase} with BGP communities modeled as one boolean variable per {@link
 * CommunityVar}.
 */
public final class SymbolicRoute extends SymbolicRouteBase implements IDeepCopy<SymbolicRoute> {

  private Map<CommunityVar, BoolExpr> _communities;

  SymbolicRoute(String name, Protocol proto) {
    super(name, proto);
    _communities = new HashMap<>();
  }

  SymbolicRoute(SymbolicRoute other) {
    super(other);
    _communities =
        new HashMap<>(other._communities); // TODO: use a persistent map to avoid this penalty
  }

  SymbolicRoute(
      EncoderSlice slice,
      String name,
      String router,
      Protocol proto,
      Optimizations opts,
      @Nullable SymbolicEnum<Protocol> h,
      boolean isAbstract) {
    super(slice, name, router, proto, opts, h, isAbstract);
  }

  /** Returns {@code route} if it is this bool-encoded type; otherwise throws. */
  public static SymbolicRoute cast(SymbolicRouteBase route) {
    if (route instanceof SymbolicRoute) {
      return (SymbolicRoute) route;
    }
    throw new IllegalArgumentException("Expected SymbolicRoute, got " + route.getClass());
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
    _communities = new HashMap<>();
    if (usesBgp) {
      Set<CommunityVar> allComms = slice.getAllCommunities();
      for (CommunityVar cvar : allComms) {
        String s = cvar.getRegex();
        if (cvar.getType() == CommunityVar.Type.REGEX) {
          s = s + "_REGEX";
        } else if (cvar.getType() == CommunityVar.Type.OTHER) {
          s = s + "_OTHER";
        }
        BoolExpr var = ctx.mkBoolConst(name + "_community_" + s);
        _communities.put(cvar, var);
      }
    }
  }

  @Override
  protected void addCommunityExprs(Map<String, Expr> all) {
    for (BoolExpr var : _communities.values()) {
      all.put(var.toString(), var);
    }
  }

  @Override
  public Map<CommunityVar, BoolExpr> getCommunities() {
    return _communities;
  }

  @Override
  public void setCommunities(Map<CommunityVar, BoolExpr> communities) {
    _communities = communities;
  }

  @Override
  public SymbolicRoute copy() {
    return new SymbolicRoute(this);
  }

  @Override
  public SymbolicRoute deepCopy() {
    return copy();
  }
}
