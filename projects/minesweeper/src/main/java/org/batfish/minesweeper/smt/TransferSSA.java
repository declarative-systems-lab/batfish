package org.batfish.minesweeper.smt;

import static org.batfish.minesweeper.CommunityVarCollector.collectCommunityVars;
import static org.batfish.minesweeper.bdd.CommunityVarConverter.toCommunityVar;

import com.google.common.collect.ImmutableMap;
import com.google.common.collect.Iterables;
import com.microsoft.z3.ArithExpr;
import com.microsoft.z3.BitVecExpr;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Expr;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.*;
import org.batfish.datamodel.ospf.OspfMetricType;
import org.batfish.datamodel.routing_policy.RoutingPolicy;
import org.batfish.datamodel.routing_policy.expr.AsPathListExpr;
import org.batfish.datamodel.routing_policy.expr.BooleanExpr;
import org.batfish.datamodel.routing_policy.expr.BooleanExprs;
import org.batfish.datamodel.routing_policy.expr.CallExpr;
import org.batfish.datamodel.routing_policy.expr.CommunitySetExpr;
import org.batfish.datamodel.routing_policy.expr.LiteralCommunity;
import org.batfish.datamodel.routing_policy.expr.Conjunction;
import org.batfish.datamodel.routing_policy.expr.ConjunctionChain;
import org.batfish.datamodel.routing_policy.expr.DecrementLocalPreference;
import org.batfish.datamodel.routing_policy.expr.DecrementMetric;
import org.batfish.datamodel.routing_policy.expr.Disjunction;
import org.batfish.datamodel.routing_policy.expr.ExplicitPrefixSet;
import org.batfish.datamodel.routing_policy.expr.FirstMatchChain;
import org.batfish.datamodel.routing_policy.expr.IncrementLocalPreference;
import org.batfish.datamodel.routing_policy.expr.IncrementMetric;
import org.batfish.datamodel.routing_policy.expr.IntExpr;
import org.batfish.datamodel.routing_policy.expr.LiteralAsList;
import org.batfish.datamodel.routing_policy.expr.LiteralInt;
import org.batfish.datamodel.routing_policy.expr.LiteralLong;
import org.batfish.datamodel.routing_policy.expr.LongExpr;
import org.batfish.datamodel.routing_policy.expr.MatchAsPath;
import org.batfish.datamodel.routing_policy.expr.MatchCommunitySet;
import org.batfish.datamodel.routing_policy.expr.MatchIpv4;
import org.batfish.datamodel.routing_policy.expr.MatchIpv6;
import org.batfish.datamodel.routing_policy.expr.MatchPrefix6Set;
import org.batfish.datamodel.routing_policy.expr.MatchPrefixSet;
import org.batfish.datamodel.routing_policy.expr.MatchProtocol;
import org.batfish.datamodel.routing_policy.expr.MultipliedAs;
import org.batfish.datamodel.routing_policy.expr.NamedCommunitySet;
import org.batfish.datamodel.routing_policy.expr.NamedPrefixSet;
import org.batfish.datamodel.routing_policy.expr.Not;
import org.batfish.datamodel.routing_policy.expr.PrefixSetExpr;
import org.batfish.datamodel.routing_policy.expr.WithEnvironmentExpr;
import org.batfish.datamodel.routing_policy.statement.AddCommunity;
import org.batfish.datamodel.routing_policy.statement.DeleteCommunity;
import org.batfish.datamodel.routing_policy.statement.If;
import org.batfish.datamodel.routing_policy.statement.PrependAsPath;
import org.batfish.datamodel.routing_policy.statement.SetCommunity;
import org.batfish.datamodel.routing_policy.statement.SetDefaultPolicy;
import org.batfish.datamodel.routing_policy.statement.SetLocalPreference;
import org.batfish.datamodel.routing_policy.statement.SetMetric;
import org.batfish.datamodel.routing_policy.statement.SetNextHop;
import org.batfish.datamodel.routing_policy.statement.SetOrigin;
import org.batfish.datamodel.routing_policy.statement.SetOspfMetricType;
import org.batfish.datamodel.routing_policy.statement.Statement;
import org.batfish.datamodel.routing_policy.statement.Statements.StaticStatement;
import org.batfish.datamodel.routing_policy.communities.MatchCommunities;
import org.batfish.datamodel.routing_policy.communities.SetCommunities;
import org.batfish.minesweeper.CommunityVar;
import org.batfish.minesweeper.CommunityVar.Type;
import org.batfish.minesweeper.Graph;
import org.batfish.minesweeper.GraphEdge;
import org.batfish.minesweeper.OspfType;
import org.batfish.minesweeper.Protocol;
import org.batfish.minesweeper.TransferParam;
import org.batfish.minesweeper.TransferResult;
import org.batfish.minesweeper.collections.PList;
import org.batfish.minesweeper.utils.MsPair;

/**
 * Class that computes a symbolic transfer function between two symbolic control plane records. The
 * transfer function is used to encode both import and export filters.
 *
 * <p>Batfish represents the AST much like vendors where there is a simple imperative language for
 * matching fields and making modifications to fields. Since this is not a good fit for a
 * declarative symbolic encoding of the network, we convert this stateful representation into a
 * stateless representation.
 *
 * <p>The TransferSSA class makes policies stateless by converting the vendor-independent format to
 * a Static Single Assignment (SSA) form where all updates are reflected in new variables. Rather
 * than create a full control flow graph (CFG) as is typically done in SSA, we use a simple
 * conversion based on adding join points for every variable modified in an if statement.
 *
 * <p>The joint point defined as the [phi] function from SSA merges variables that may differ across
 * different branches of an if statement. For example, if there is the following filter:
 *
 * <p>if match(c1) then add community c2 else prepend path 2
 *
 * <p>Then this function will introduce a new variable at the end of the if statement that updates
 * the value of each variable modified based on the branch taken. For example:
 *
 * <p>c2' = (c1 ? true : c2) metric' = (c1 ? metric : metric + 2)
 RoutingPolicy.java *
 * <p>To model the return value of functions, we introduce three new variables: [fallthrough],
 * [returnValue] and [returnAssigned]. For example, if we have the following AST function in
 * Batfish:
 *
 * <p>function foo() if match(c1) then reject accept
 *
 * <p>This is modeled by introducing [returnValue] - the value that the function returns, and the
 * [returnAssigned] variable - whether a return or fallthrough statement has been hit so far in the
 * control flow.
 *
 * <p>Naturally, this kind of encoding can grow quite large since we introduce a large number of
 * extra variables. To make formula much simpler, we use a term size heuristic to inline variable
 * equalities when the inlined term will not be too large. Thus, additional variables are still
 * introduced, but only to keep the encoding compact. The 'simplify' and 'propagate-values' tactics
 * for z3 will further improve the encoding by removing any unnecessary variables. In this example,
 * the encoding will be simplified to [returnValue''' = not c1], which removes all intermediate
 * variables
 *
 * @author Ryan Beckett
 */
class TransferSSA {

  private static final int INLINE_HEURISTIC = 3000;

  private static int id = 0;

  private EncoderSlice _enc;

  private Configuration _conf;

  private SymbolicRouteBV _current;

  private SymbolicRouteBV _other;

  private Protocol _proto;

  private List<Statement> _statements;

  private Integer _addedCost;

  private Interface _iface;

  private GraphEdge _graphEdge;

  private Map<Prefix, Boolean> _aggregates;

  private boolean _isExport;

  private ImmutableMap<CommunityVar, Integer> _commsIndex;

  TransferSSA(
      EncoderSlice encoderSlice,
      Configuration conf,
      SymbolicRouteBV other,
      SymbolicRouteBV current,
      Protocol proto,
      List<Statement> statements,
      Integer addedCost,
      GraphEdge ge,
      boolean isExport,
      ImmutableMap<CommunityVar, Integer> commsIndex) {
    _enc = encoderSlice;
    _conf = conf;
    _current = current;
    _other = other;
    _proto = proto;
    _statements = statements;
    _addedCost = addedCost;
    _graphEdge = ge;
    _iface = ge.getStart();
    _isExport = isExport;
    _aggregates = null;
    _commsIndex = commsIndex;
  }

  /*
   * Returns and increments a unique id for adding additional SSA variables
   */
  private static int generateId() {
    int result = TransferSSA.id;
    TransferSSA.id = result + 1;
    return result;
  }

  /*
   * Determines whether to model each aggregate route as
   * suppressing a more specific, or including the more specific
   */
  private Map<Prefix, Boolean> aggregateRoutes() {
    Map<Prefix, Boolean> acc = new HashMap<>();
    String name = _conf.getHostname();
    List<GeneratedRoute> aggregates = _enc.getOptimizations().getRelevantAggregates().get(name);
    Set<Prefix> suppressed = _enc.getOptimizations().getSuppressedAggregates().get(name);
    for (GeneratedRoute gr : aggregates) {
      Prefix p = gr.getNetwork();
      acc.put(p, suppressed.contains(p));
    }
    return acc;
  }

  /*
   * Converts a route filter list to a boolean expression.
   */
  private BoolExpr matchFilterList(RouteFilterList x, SymbolicRouteBV other) {
    BoolExpr acc = _enc.mkFalse();

    List<RouteFilterLine> lines = new ArrayList<>(x.getLines());
    Collections.reverse(lines);

    // both or neither enable SMT variable
    boolean allEnableSmtVariable =
        Iterables.all(lines, RouteFilterLine::getEnableSmtVariable);
    boolean noneEnableSmtVariable =
        Iterables.all(lines, r -> !r.getEnableSmtVariable());
    if (!(allEnableSmtVariable || noneEnableSmtVariable)) {
      throw new BatfishException(
          "Inconsistent enableSmtVariable flags in List<RouteFilterLine>");
    }

    for (RouteFilterLine line : lines) {
      if (!line.getIpWildcard().isPrefix()) {
        throw new BatfishException("non-prefix IpWildcards are unsupported");
      }

      if (!line.getEnableSmtVariable())  {
        Prefix p = line.getIpWildcard().toPrefix();
        SubRange r = line.getLengthRange();
        PrefixRange range = new PrefixRange(p, r);
        BoolExpr matches = _enc.isRelevantFor(other.getPrefixLength(), range);
        BoolExpr action = _enc.mkBool(line.getAction() == LineAction.PERMIT);
        acc = _enc.mkIf(matches, action, acc);
      } else {
        Prefix p = line.getIpWildcard().toPrefixWithSymbolicVariables();
        SubRange r = line.getLengthRange();
        PrefixRange range = new PrefixRange(p, r);
        BoolExpr matches = _enc.isRelevantFor(other.getPrefixLength(), range);
        BoolExpr action = line.getConfigVarAction();
        acc = _enc.mkIf(matches, action, acc);
        // NOTE: symbolic encoding for the line enable
        // BoolExpr lineEnable = line.getConfigLineEnable();
        // acc = _enc.mkIf(_enc.mkAnd(lineEnable, matches), action, acc);
      }
    }

    return acc;
  }

  /*
   * Converts a prefix set to a boolean expression.
   */
  private TransferResult<BoolExpr, BoolExpr> matchPrefixSet(
      Configuration conf, MatchPrefixSet mps, SymbolicRouteBV other) {

    PrefixSetExpr e = mps.getPrefixSet();
    ArithExpr otherLen = other.getPrefixLength();

    TransferResult<BoolExpr, BoolExpr> result = new TransferResult<>();

    // BoolExpr lineEnable = mps.getConfigLineEnable();

    if (e instanceof ExplicitPrefixSet) {
      ExplicitPrefixSet x = (ExplicitPrefixSet) e;

      Set<PrefixRange> ranges = x.getPrefixSpace().getPrefixRanges();
      if (ranges.isEmpty()) {
        return result.setReturnValue(_enc.mkTrue());
      }

      // both or neither enable SMT variable
      boolean allEnableSmtVariable =
          Iterables.all(ranges, PrefixRange::getEnableSmtVariable);
      boolean noneEnableSmtVariable =
          Iterables.all(ranges, r -> !r.getEnableSmtVariable());
      if (!(allEnableSmtVariable || noneEnableSmtVariable)) {
        throw new BatfishException(
            "Inconsistent enableSmtVariable flags in Set<PrefixRange>");
      }

      // This is a total hack to deal with the fact that
      // we keep only a single FIB entry. Since BGP exporting a network
      // depends on the existence of an IGP route, we become more precise
      // by checking for static/connected/OSPF routes specifically.
      if (ranges.size() == 1) {
        for (PrefixRange r : ranges) {
          int start = r.getLengthRange().getStart();
          int end = r.getLengthRange().getEnd();
          Prefix pfx = r.getPrefix();

          if (start == end && start == pfx.getPrefixLength()) {
            String router = _conf.getHostname();
            Set<Prefix> origin = _enc.getOriginatedNetworks().get(router, Protocol.BGP);

            if (origin != null && origin.contains(pfx)) {
              // Compute static and connected routes
              Set<Prefix> ostatic = _enc.getOriginatedNetworks().get(router, Protocol.STATIC);
              Set<Prefix> oconn = _enc.getOriginatedNetworks().get(router, Protocol.CONNECTED);
              boolean hasStatic = ostatic != null && ostatic.contains(pfx);
              boolean hasConnected = oconn != null && oconn.contains(pfx);

              ArithExpr originLength;
              if (pfx.getEnableSmtVariable()) {
                originLength = pfx.getConfigVarLength();
              } else {
                originLength = _enc.mkInt(pfx.getPrefixLength());
              }

              if (hasStatic || hasConnected) {
                BoolExpr directRoute = _enc.isRelevantFor(originLength, r);
                ArithExpr newLength = _enc.mkIf(directRoute, originLength, otherLen);
                result = result.addChangedVariable("PREFIX-LEN", newLength);
                if (!mps.getEnableSmtVariable()) {
                  return result.setReturnValue(directRoute);
                } else {
                  return result.setReturnValue(directRoute);
                  // NOTE: symbolic encoding for the line enable
                  // directRoute = _enc.mkIf(lineEnable, directRoute, _enc.mkTrue());
                  // return result.setReturnValue(directRoute);
                }
              } else {
                // Also use network statement if OSPF has a route with the correct length
                SymbolicRouteBV rec = _enc.getBestNeighborPerProtocol(router, Protocol.OSPF);
                if (rec != null) {
                  BoolExpr ospfRelevant = _enc.isRelevantFor(rec.getPrefixLength(), r);
                  ArithExpr newLength = _enc.mkIf(ospfRelevant, originLength, otherLen);
                  result = result.addChangedVariable("PREFIX-LEN", newLength);
                  if (!mps.getEnableSmtVariable()) {
                    return result.setReturnValue(ospfRelevant);
                  } else {
                    return result.setReturnValue(ospfRelevant);
                    // NOTE: symbolic encoding for the line enable
                    // ospfRelevant = _enc.mkIf(lineEnable, ospfRelevant, _enc.mkTrue());
                    // return result.setReturnValue(ospfRelevant);
                  }
                }
              }
            }
          }
        }
      }

      // Compute if the other best route is relevant for this match statement
      BoolExpr acc = _enc.mkFalse();
      for (PrefixRange range : ranges) {
        acc = _enc.mkOr(acc, _enc.isRelevantFor(otherLen, range));
      }

      if (!mps.getEnableSmtVariable()) {
        return result.setReturnValue(acc);
      } else {
        return result.setReturnValue(acc);
        // NOTE: symbolic encoding for the line enable
        // acc = _enc.mkIf(lineEnable, acc, _enc.mkTrue());
        // return result.setReturnValue(acc);
      }

    } else if (e instanceof NamedPrefixSet) {
      NamedPrefixSet x = (NamedPrefixSet) e;
      String name = x.getName();
      RouteFilterList fl = conf.getRouteFilterLists().get(name);
      if (!mps.getEnableSmtVariable()) {
        return result.setReturnValue(matchFilterList(fl, other));
      } else {
        BoolExpr bgpRelevant = matchFilterList(fl, other);
        return result.setReturnValue(bgpRelevant);
        // NOTE: symbolic encoding for the line enable
        // bgpRelevant = _enc.mkIf(lineEnable, bgpRelevant, _enc.mkTrue());
        // return result.setReturnValue(bgpRelevant);
      }

    } else {
      throw new BatfishException("TODO: match prefix set: " + e);
    }
  }

  private String regexToString(String r) {
    char first = r.charAt(0);
    int len = r.length();
    char last = r.charAt(len - 1);
    if ((first == '^') && (last == '$')) {
      return r.substring(1,len-1);
    }
    return r;
  }

  // This code is copied and adapted from the `minesweeper-ibgp-new` branch of the Batfish repository:
  // https://github.com/batfish/batfish
  private BoolExpr matchCommunity(Map<CommunityVar, BoolExpr> comms, CommunityVar c) {
    Type commType = c.getType();
    String cstring = c.getRegex().toString();
    /* Equality check between exact matches. */
    BoolExpr cbool = comms.get(c);
    if (cbool != null) {
      return cbool;
    }
    // Regexp checking, if it's a regexp try to match it with a regexp or an exact.
    Map<CommunityVar, BoolExpr> exact = new HashMap<>();
    Map<CommunityVar, BoolExpr> regex = new HashMap<>();
    Map<CommunityVar, BoolExpr> other = new HashMap<>();
    for (Map.Entry<CommunityVar, BoolExpr> e : comms.entrySet()) {
      switch (e.getKey().getType()) {
        case EXACT:
          exact.put(e.getKey(), e.getValue());
          break;
        case REGEX:
          regex.put(e.getKey(), e.getValue());
          break;
        case OTHER:
          other.put(e.getKey(), e.getValue());
          break;
      }
    }

    if (commType.equals(Type.EXACT)) {
      // No point in checking the exact list, cbool would have caught it.
      for (Map.Entry<CommunityVar, BoolExpr> e : regex.entrySet()) {
        String ostring = regexToString(e.getKey().getRegex().toString());
        if (Pattern.matches(ostring, cstring)) {
          return e.getValue();
        }
      }
      for (Map.Entry<CommunityVar, BoolExpr> e : other.entrySet()) {
        String ostring = regexToString(e.getKey().getRegex().toString());
        if (Pattern.matches(ostring, cstring)) {
          return e.getValue();
        }
      }
    } else {
      // Other checking
      for (Map.Entry<CommunityVar, BoolExpr> e : exact.entrySet()) {
        String ostring = regexToString(e.getKey().getRegex().toString());
        if (Pattern.matches(cstring, ostring)) {
          return e.getValue();
        }
      }
      for (Map.Entry<CommunityVar, BoolExpr> e : regex.entrySet()) {
        String ostring = regexToString(e.getKey().getRegex().toString());
        if (cstring.equals(ostring)) {
          return e.getValue();
        }
      }
      for (Map.Entry<CommunityVar, BoolExpr> e : other.entrySet()) {
        String ostring = regexToString(e.getKey().getRegex().toString());
        if (cstring.equals(ostring)) {
          return e.getValue();
        }
      }
    }
    return null;
  }

  private BoolExpr matchCommunityExtend(SymbolicRouteBV other, CommunityVar cvar) {
    BoolExpr c1 = other.getCommunities().get(cvar);
    BoolExpr c2 = matchCommunity(other.getCommunities(), cvar);
    if (null != c1) {
      return c1;
    } else if (null != c2) {
      return c2;
    } else {
      throw new BatfishException(
          "TransferSSA.matchCommunityExtend: cannot match community in SymbolicRouteBV.");
    }
  }

  /**
   * Converts a community list to a boolean expression.
   */
  private BoolExpr matchCommunityList(CommunityList cl, SymbolicRouteBV other) {
    // List<CommunityListLine> lines = new ArrayList<>(cl.getLines());
    // Collections.reverse(lines);
    // BoolExpr acc = _enc.mkFalse();
    //
    // if (!cl.getEnableSmtVariable()) {
    //   for (CommunityListLine line : lines) {
    //     CommunityVar cvar = toCommunityVar(line.getMatchCondition());
    //     BoolExpr c = matchCommunityExtend(other, cvar);
    //     boolean action = (line.getAction() == LineAction.PERMIT);
    //     acc = _enc.mkIf(c, _enc.mkBool(action), acc);
    //   }
    // } else {
    //   for (CommunityListLine line : lines) {
    //     CommunityVar cvar = toCommunityVar(line.getMatchCondition());
    //     BoolExpr c = matchCommunityExtend(other, cvar);
    //
    //     BoolExpr community = null;
    //     CommunitySetExpr communitySetExpr = line.getMatchCondition();
    //     if (communitySetExpr instanceof RegexCommunitySet) {
    //       RegexCommunitySet rcs = (RegexCommunitySet) communitySetExpr;
    //       community = rcs.getConfigVarCommunity();
    //     } else if (communitySetExpr instanceof LiteralCommunity) {
    //       LiteralCommunity lc = (LiteralCommunity) communitySetExpr;
    //       community = lc.getConfigVarCommunity();
    //     } else {
    //       throw new BatfishException("Unimplemented community condition: " + communitySetExpr);
    //     }
    //     BoolExpr matchCommunityLine = _enc.mkEq(community, c);
    //     BoolExpr action = line.getConfigVarAction();
    //     // acc = _enc.mkIf(matchCommunityLine, action, acc);
    //     // NOTE: symbolic encoding for the line enable
    //     BoolExpr lineEnable = line.getConfigLineEnable();
    //     acc = _enc.mkIf(_enc.mkAnd(lineEnable, matchCommunityLine), action, acc);
    //   }
    // }
    //
    // return acc;

    // NOTE: modified match community list (BoolExpr -> BitVecExpr communities)

    List<CommunityListLine> lines = new ArrayList<>(cl.getLines());
    Collections.reverse(lines);
    BoolExpr acc = _enc.mkFalse();

    for (CommunityListLine line : lines) {
      CommunityVar cvar = toCommunityVar(line.getMatchCondition());
      List<CommunityVar> comms = new ArrayList<>();
      if (Type.REGEX == cvar.getType()) {
        comms = _enc.getGraph().getCommunityDependencies(cvar);
      } else {
        comms.add(cvar);
      }

      if (!cl.getEnableSmtVariable()) {
        BitVecExpr commsMask = SymbolicRouteBV.communitiesMask(_enc.getCtx(), _commsIndex, comms);
        BitVecExpr commsMatch = _enc.getCtx().mkBVAND(other.getCommunitiesBitVec(), commsMask);
        BoolExpr c = SymbolicRouteBV.communitiesMatch(_enc.getCtx(), commsMatch, _commsIndex.size());
        boolean action = (line.getAction() == LineAction.PERMIT);
        acc = _enc.mkIf(c, _enc.mkBool(action), acc);

      } else {
        BitVecExpr commsMask = null;
        for (CommunityVar ccvar : comms) {
          if (!ccvar.getLiteralValue().getEnableSmtVariable() ||
              null == ccvar.getLiteralValue().getConfigVarCommunity()) {
            throw new BatfishException("matchCommunityList: " +
                "does not have a config variable for communities");
          }
          // TODO: modify constraint (or X1 (or X2 (or X3 X4))) to (or X1 X2 X3 X4)
          BitVecExpr commMask = ccvar.getLiteralValue().getConfigVarCommunity();
          if (null == commsMask)  commsMask = commMask;
          else                    commsMask = _enc.getCtx().mkBVOR(commsMask, commMask);
        }

        BitVecExpr commsMatch = _enc.getCtx().mkBVAND(other.getCommunitiesBitVec(), commsMask);

        BoolExpr c = SymbolicRouteBV.communitiesMatch(_enc.getCtx(), commsMatch, _commsIndex.size());
        BoolExpr action = line.getConfigVarAction();
        acc = _enc.mkIf(c, action, acc);
        // NOTE: symbolic encoding for the line enable
        // BoolExpr lineEnable = line.getConfigLineEnable();
        // acc = _enc.mkIf(_enc.mkAnd(lineEnable, c), action, acc);
      }
    }

    return acc;
  }

  /**
   * Converts a community set to a boolean expression
   */
  private BoolExpr matchCommunitySet(Configuration conf, CommunitySetExpr e, SymbolicRouteBV other) {
    // if (e instanceof CommunityList) {
    //   Set<CommunityVar> comms = collectCommunityVars(conf, e);
    //   BoolExpr acc = _enc.mkTrue();
    //   for (CommunityVar comm : comms) {
    //     BoolExpr c = other.getCommunities().get(comm);
    //     if (c == null) {
    //       throw new BatfishException("matchCommunitySet: should not be null");
    //     }
    //     acc = _enc.mkAnd(acc, c);
    //   }
    //   return acc;
    // }
    //
    // if (e instanceof NamedCommunitySet) {
    //   NamedCommunitySet x = (NamedCommunitySet) e;
    //   CommunityList cl = conf.getCommunityLists().get(x.getName());
    //   return matchCommunityList(cl, other);
    // }
    //
    // throw new BatfishException("TODO: match community set");

    // NOTE: modified match community set (BoolExpr -> BitVec communities)

    if (e instanceof CommunityList) {
      return matchCommunityList((CommunityList) e, other);
    }

    if (e instanceof NamedCommunitySet) {
      NamedCommunitySet x = (NamedCommunitySet) e;
      CommunityList cl = conf.getCommunityLists().get(x.getName());
      return matchCommunityList(cl, other);
    }

    if (e instanceof LiteralCommunity) {
      LiteralCommunity x = (LiteralCommunity) e;
      CommunityVar cvar = toCommunityVar(x);
      List<CommunityVar> comms = new ArrayList<>();
      if (Type.REGEX == cvar.getType()) {
        comms = _enc.getGraph().getCommunityDependencies(cvar);
      } else {
        comms.add(cvar);
      }
      if (!e.getEnableSmtVariable()) {
        // FIXME: unimplemented
        return _enc.mkTrue();
      } else {
        BitVecExpr commsMask = SymbolicRouteBV.communitiesMask(_enc.getCtx(), _commsIndex, comms);
        BitVecExpr commsMatch = _enc.getCtx().mkBVAND(other.getCommunitiesBitVec(), commsMask);
        return SymbolicRouteBV.communitiesMatch(_enc.getCtx(), commsMatch, _commsIndex.size());
      }
    }

    throw new BatfishException("TODO: match community set");
  }

  /**
   * Expand community variables for add/set/delete community statements.
   */
  private Set<CommunityVar> resolveConfigurationCommunityVars(Set<CommunityVar> comms, String configVarPrefix) {
    Set<CommunityVar> resolved = new HashSet<>();
    for (CommunityVar cvar : comms) {
      if (cvar.getType() != CommunityVar.Type.REGEX) {
        if (CommunityVar.Type.OTHER == cvar.getType()) {
          continue;   // skip OTHER type community variables
        }
        resolved.add(cvar);
        continue;
      }

      List<CommunityVar> dependencies = _enc.getGraph().getCommunityDependencies(cvar);
      for (CommunityVar dep : dependencies) {
        if (dep.getType() == CommunityVar.Type.OTHER) {
          continue;   // skip OTHER type community variables
        }
        if (dep.getLiteralValue().getEnableSmtVariable()) {
          dep.cloneCommunity();
        }
        // symbolic configuration for community (regex dependencies)
        Encoder.initConfigurationConstantsComm(_enc.getEncoder(), dep, configVarPrefix);
        resolved.add(dep);
      }
    }
    return resolved;
  }

  /**
   * Configure communities (AddCommunity, SetCommunity, and DeleteCommunity)
   */
  private BitVecExpr configCommunities(
      TransferParam<SymbolicRouteBV> curP, TransferResult<BoolExpr, BoolExpr> curResult,
      boolean enableSmtVariable, BoolExpr lineEnable, Set<CommunityVar> comms,
      String configVarPrefix, String stmtName) {
    // resolve configuration and initConfigurationConstants
    comms = resolveConfigurationCommunityVars(comms, configVarPrefix);

    for (CommunityVar cvar : comms) {
      if (cvar.getType() == CommunityVar.Type.REGEX) {
        throw new BatfishException("configCommunities: " +
            stmtName + "does not support regex community " +
            "(dependencies already resolved to exact / other communities)");
      }
    }

    BitVecExpr commsMask = null;

    if (!enableSmtVariable) {
      commsMask = SymbolicRouteBV.communitiesMask(_enc.getCtx(), _commsIndex, comms);

    } else {
      for (CommunityVar cvar : comms) {
        if (!cvar.getLiteralValue().getEnableSmtVariable() ||
            null == cvar.getLiteralValue().getConfigVarCommunity()) {
          throw new BatfishException("configCommunities: " +
              stmtName + " does not have a config variable for communities");
        }
        // TODO: modify constraint (or X1 (or X2 (or X3 X4))) to (or X1 X2 X3 X4)
        BitVecExpr commMask = cvar.getLiteralValue().getConfigVarCommunity();
        if (null == commsMask)  commsMask = commMask;
        else                    commsMask = _enc.getCtx().mkBVOR(commsMask, commMask);
      }
    }

    if (null == commsMask) {
      throw new BatfishException("configCommunities: " + stmtName + "communities mask is null");
    }

    BitVecExpr commsBv = curP.getData().getCommunitiesBitVec();
    BitVecExpr commsBvUpdated = null;

    if (AddCommunity.class.getName().equals(stmtName)) {
      // commsBv OR commsMask will set the bits in commsMask and keep the rest unchanged.
      commsBvUpdated = _enc.getCtx().mkBVOR(commsBv, commsMask);

    } else if (SetCommunity.class.getName().equals(stmtName)) {
      // commsBV = commsMask will set the bits in commsMask and clear the rest.
      commsBvUpdated = commsMask;

    } else if (DeleteCommunity.class.getName().equals(stmtName)) {
      // commsBV AND (NOT commsMask) will clear the bits in commsMask and keep the rest unchanged.
      commsBvUpdated = _enc.getCtx().mkBVAND(commsBv, _enc.getCtx().mkBVNot(commsMask));

    } else {
      throw new BatfishException("configCommunities: " +
          "stmtName should be AddCommunity, SetCommunity, or DeleteCommunity");
    }

    BitVecExpr commsBvNew;
    if (AddCommunity.class.getName().equals(stmtName)) {
      // BUGFIX: gate AddCommunity on current If-term guard, not returnAssigned from prior terms
      BoolExpr applyGuard =
          curP.getTermGuard() != null ? curP.getTermGuard() : _enc.mkTrue();
      commsBvNew = _enc.mkIf(applyGuard, commsBvUpdated, commsBv);
    } else {
      commsBvNew = _enc.mkIf(curResult.getReturnAssignedValue(), commsBv, commsBvUpdated);
    }
    BitVecExpr x = null;
    if (!enableSmtVariable) {
      x = createBitVecVariableWith(curP, "COMMUNITIES", _commsIndex.size(), commsBvNew);
    } else {
      // if (null == lineEnable) {
      //   throw new BatfishException("configCommunities: " +
      //       stmtName + " enable SMT variable but line enable flag is null");
      // }
      BitVecExpr newX = createBitVecVariableWith(curP, "COMMUNITIES", _commsIndex.size(), commsBvNew);
      BitVecExpr oldX = curP.getData().getCommunitiesBitVec();
      x = newX;
      // NOTE: symbolic encoding for the line enable
      // x = _enc.mkIf(lineEnable, newX, oldX);
    }

    return x;
  }

  /*
   * Wrap a simple boolean expression return value in a transfer function result
   */
  private TransferResult<BoolExpr, BoolExpr> fromExpr(BoolExpr b) {
    return new TransferResult<BoolExpr, BoolExpr>()
        .setReturnAssignedValue(_enc.mkTrue())
        .setReturnValue(b);
  }

  private TransferResult<BoolExpr, BoolExpr> initialResult() {
    return new TransferResult<BoolExpr, BoolExpr>()
        .setReturnValue(_enc.mkFalse())
        .setFallthroughValue(_enc.mkFalse())
        .setReturnAssignedValue(_enc.mkFalse());
  }

  /*
   * Convert a Batfish AST boolean expression to a symbolic Z3 boolean expression
   * by performing inlining of stateful side effects.
   */
  private TransferResult<BoolExpr, BoolExpr> compute(
      BooleanExpr expr, TransferParam<SymbolicRouteBV> p) {
    TransferParam<SymbolicRouteBV> pCur = p;
    // TODO: right now everything is IPV4
    if (expr instanceof MatchIpv4) {
      pCur.debug("MatchIpv4");
      return fromExpr(_enc.mkTrue());
    }
    if (expr instanceof MatchIpv6) {
      pCur.debug("MatchIpv6");
      return fromExpr(_enc.mkFalse());
    }

    if (expr instanceof Conjunction) {
      pCur.debug("Conjunction");
      Conjunction c = (Conjunction) expr;
      BoolExpr acc = _enc.mkTrue();
      TransferResult<BoolExpr, BoolExpr> result = new TransferResult<>();
      for (BooleanExpr be : c.getConjuncts()) {
        TransferResult<BoolExpr, BoolExpr> r = compute(be, pCur.indent());
        result = result.addChangedVariables(r);
        acc = _enc.mkAnd(acc, r.getReturnValue());
      }
      pCur.debug("has changed variable");
      return result.setReturnValue(acc);
    }

    if (expr instanceof Disjunction) {
      pCur.debug("Disjunction");
      Disjunction d = (Disjunction) expr;
      BoolExpr acc = _enc.mkFalse();
      TransferResult<BoolExpr, BoolExpr> result = new TransferResult<>();
      for (BooleanExpr be : d.getDisjuncts()) {
        TransferResult<BoolExpr, BoolExpr> r = compute(be, pCur.indent());
        result = result.addChangedVariables(r);
        acc = _enc.mkOr(acc, r.getReturnValue());
      }
      pCur.debug("has changed variable");
      return result.setReturnValue(acc);
    }

    if (expr instanceof ConjunctionChain) {
      pCur.debug("ConjunctionChain");
      ConjunctionChain d = (ConjunctionChain) expr;
      List<BooleanExpr> conjuncts = new ArrayList<>(d.getSubroutines());
      if (pCur.getDefaultPolicy() != null) {
        BooleanExpr be = new CallExpr(pCur.getDefaultPolicy().getDefaultPolicy());
        conjuncts.add(be);
      }
      if (conjuncts.isEmpty()) {
        return fromExpr(_enc.mkTrue());
      } else {
        TransferResult<BoolExpr, BoolExpr> result = new TransferResult<>();
        BoolExpr acc = _enc.mkFalse();
        for (int i = conjuncts.size() - 1; i >= 0; i--) {
          BooleanExpr conjunct = conjuncts.get(i);
          TransferParam<SymbolicRouteBV> param =
              pCur.setDefaultPolicy(null).setChainContext(TransferParam.ChainContext.CONJUNCTION);
          TransferResult<BoolExpr, BoolExpr> r = compute(conjunct, param);
          result = result.addChangedVariables(r);
          acc = _enc.mkIf(r.getFallthroughValue(), acc, r.getReturnValue());
        }
        pCur.debug("ConjunctionChain Result: " + acc);
        return result.setReturnValue(acc);
      }
    }

    if (expr instanceof FirstMatchChain) {
      pCur.debug("FirstMatchChain");
      FirstMatchChain chain = (FirstMatchChain) expr;
      List<BooleanExpr> chainPolicies = new ArrayList<>(chain.getSubroutines());
      if (pCur.getDefaultPolicy() != null) {
        BooleanExpr be = new CallExpr(pCur.getDefaultPolicy().getDefaultPolicy());
        chainPolicies.add(be);
      }
      if (chainPolicies.isEmpty()) {
        // No identity for an empty FirstMatchChain; default policy should always be set.
        throw new BatfishException("Default policy is not set");
      }
      TransferResult<BoolExpr, BoolExpr> result = new TransferResult<>();
      // BUGFIX: thread route state through chain like TransferBDD, not reuse initial pCur
      TransferParam<SymbolicRouteBV> record = pCur;
      BoolExpr acc = _enc.mkFalse();
      for (int i = chainPolicies.size() - 1; i >= 0; i--) {
        BooleanExpr policyMatcher = chainPolicies.get(i);
        TransferParam<SymbolicRouteBV> param =
            record
                .setDefaultPolicy(null)
                .setChainContext(TransferParam.ChainContext.CONJUNCTION)
                .indent();
        TransferResult<BoolExpr, BoolExpr> r = compute(policyMatcher, param);
        record = param;
        for (MsPair<String, Expr> changed : r.getChangedVariables()) {
          if (!changed.getFirst().equals("COMMUNITIES")) {
            result = result.addChangedVariable(changed.getFirst(), changed.getSecond());
          }
        }
        acc = _enc.mkIf(r.getFallthroughValue(), acc, r.getReturnValue());
      }
      // BUGFIX: accumulate community side effects along fallthrough chain, not last step only
      result =
          result.addChangedVariable("COMMUNITIES", record.getData().getCommunitiesBitVec());
      pCur.debug("FirstMatchChain Result: " + acc);
      return result.setReturnValue(acc);
    }

    if (expr instanceof Not) {
      pCur.debug("mkNot");
      Not n = (Not) expr;
      TransferResult<BoolExpr, BoolExpr> result = compute(n.getExpr(), pCur);
      return result.setReturnValue(_enc.mkNot(result.getReturnValue()));
    }

    if (expr instanceof MatchProtocol) {
      pCur.debug("MatchProtocol");
      MatchProtocol mp = (MatchProtocol) expr;
      Set<RoutingProtocol> rps = mp.getProtocols();
      if (rps.size() > 1) {
        // Hack: Minesweeper doesn't support MatchProtocol with multiple arguments.
        List<BooleanExpr> mps = rps.stream().map(MatchProtocol::new).collect(Collectors.toList());
        return compute(new Disjunction(mps), p);
      }
      RoutingProtocol rp = Iterables.getOnlyElement(mp.getProtocols());
      Protocol proto = Protocol.fromRoutingProtocol(rp);
      if (proto == null) {
        pCur.debug("MatchProtocol(" + rp.protocolName() + "): false");
        return fromExpr(_enc.mkFalse());
      }
      if (_other.getProtocolHistory() == null) {
        BoolExpr protoMatch = _enc.mkBool(proto.equals(_proto));
        pCur.debug("MatchProtocol(" + rp.protocolName() + "): " + protoMatch);
        return fromExpr(protoMatch);
      }
      BoolExpr protoMatch = _other.getProtocolHistory().checkIfValue(proto);
      pCur.debug("MatchProtocol(" + rp.protocolName() + "): " + protoMatch);
      return fromExpr(protoMatch);
    }

    if (expr instanceof MatchPrefixSet) {
      pCur.debug("MatchPrefixSet");
      MatchPrefixSet mps = (MatchPrefixSet) expr;
      // For BGP, may change prefix length
      if (!mps.getEnableSmtVariable()) {
        TransferResult<BoolExpr, BoolExpr> result = matchPrefixSet(_conf, mps, pCur.getData());
        return result.setReturnAssignedValue(_enc.mkTrue());
      } else {
        // callee matchPrefixSet handle the line enable flag
        TransferResult<BoolExpr, BoolExpr> result = matchPrefixSet(_conf, mps, pCur.getData());
        return result.setReturnAssignedValue(_enc.mkTrue());
      }

    } else if (expr instanceof MatchPrefix6Set) {
      pCur.debug("MatchPrefix6Set");
      return fromExpr(_enc.mkFalse());

    } else if (expr instanceof CallExpr) {
      pCur.debug("CallExpr");
      // TODO: the call can modify certain fields, need to keep track of these variables
      CallExpr c = (CallExpr) expr;
      String name = c.getCalledPolicyName();
      RoutingPolicy pol = _conf.getRoutingPolicies().get(name);
      pCur = pCur.setCallContext(TransferParam.CallContext.EXPR_CALL);
      TransferResult<BoolExpr, BoolExpr> r =
          compute(pol.getStatements(), pCur.indent().enterScope(name), initialResult());
      pCur.debug("CallExpr (return): " + r.getReturnValue());
      pCur.debug("CallExpr (fallthrough): " + r.getFallthroughValue());
      return r;

    } else if (expr instanceof WithEnvironmentExpr) {
      pCur.debug("WithEnvironmentExpr");
      // TODO: this is not correct
      WithEnvironmentExpr we = (WithEnvironmentExpr) expr;
      // TODO: postStatements() and preStatements()
      return compute(we.getExpr(), pCur);

    } else if (expr instanceof MatchCommunitySet) {
      pCur.debug("MatchCommunitySet");
      MatchCommunitySet mcs = (MatchCommunitySet) expr;
      if (!mcs.getEnableSmtVariable()) {
        return fromExpr(matchCommunitySet(_conf, mcs.getExpr(), pCur.getData()));
      } else {
        BoolExpr x = matchCommunitySet(_conf, mcs.getExpr(), pCur.getData());
        return fromExpr(x);
        // NOTE: symbolic encoding for the line enable
        // BoolExpr lineEnable = mcs.getConfigLineEnable();
        // x = _enc.mkIf(lineEnable, x, _enc.mkTrue());
        // return fromExpr(x);
      }

    } else if (expr instanceof BooleanExprs.StaticBooleanExpr) {
      BooleanExprs.StaticBooleanExpr b = (BooleanExprs.StaticBooleanExpr) expr;
      switch (b.getType()) {
        case CallExprContext:
          pCur.debug("CallExprContext");
          return fromExpr(
              _enc.mkBool(pCur.getCallContext() == TransferParam.CallContext.EXPR_CALL));
        case CallStatementContext:
          pCur.debug("CallStmtContext");
          return fromExpr(
              _enc.mkBool(pCur.getCallContext() == TransferParam.CallContext.STMT_CALL));
        case True:
          pCur.debug("True");
          return fromExpr(_enc.mkTrue());
        case False:
          pCur.debug("False");
          return fromExpr(_enc.mkFalse());
        default:
          throw new BatfishException(
              "Unhandled " + BooleanExprs.class.getCanonicalName() + ": " + b.getType());
      }

    } else if (expr instanceof MatchAsPath) {
      pCur.debug("MatchAsPath");
      pCur.debug("Warning: use of unimplemented feature MatchAsPath");
      return fromExpr(_enc.mkFalse());

    } else if (expr instanceof MatchCommunities) {
      pCur.debug("MatchCommunities");
      pCur.debug("Warning: use of unimplemented feature MatchCommunities");
      return fromExpr(_enc.mkFalse());
    }

    String s = (_isExport ? "export" : "import");
    String msg =
        String.format(
            "Unimplemented feature %s for %s transfer function on interface %s",
            expr.toString(), s, _graphEdge.toString());

    throw new BatfishException(msg);
  }

  /*
   * Deal with the possibility of null variables due to optimizations
   */
  private ArithExpr getOrDefault(ArithExpr x, ArithExpr d) {
    if (x != null) {
      return x;
    }
    return d;
  }

  /*
   * Apply the effect of modifying a long value (e.g., to set the metric)
   */
  private ArithExpr applyLongExprModification(ArithExpr x, LongExpr e) {
    if (e instanceof LiteralLong) {
      LiteralLong z = (LiteralLong) e;
      if (z.getEnableSmtVariable()) {
        return z.getConfigVarLocalpreference();
      } else {
        return _enc.mkInt(z.getValue());
      }
    }
    if (e instanceof DecrementMetric) {
      DecrementMetric z = (DecrementMetric) e;
      if (z.getEnableSmtVariable()) {
        return z.getConfigVarLocalpreference();
      } else {
        return _enc.mkSub(x, _enc.mkInt(z.getSubtrahend()));
      }
    }
    if (e instanceof IncrementMetric) {
      IncrementMetric z = (IncrementMetric) e;
      if (z.getEnableSmtVariable()) {
        return z.getConfigVarLocalpreference();
      } else {
        return _enc.mkSum(x, _enc.mkInt(z.getAddend()));
      }
    }
    if (e instanceof IncrementLocalPreference) {
      IncrementLocalPreference z = (IncrementLocalPreference) e;
      if (z.getEnableSmtVariable()) {
        return z.getConfigVarLocalpreference();
      } else {
        return _enc.mkSum(x, _enc.mkInt(z.getAddend()));
      }
    }
    if (e instanceof DecrementLocalPreference) {
      DecrementLocalPreference z = (DecrementLocalPreference) e;
      if (z.getEnableSmtVariable()) {
        return z.getConfigVarLocalpreference();
      } else {
        return _enc.mkSub(x, _enc.mkInt(z.getSubtrahend()));
      }
    }
    throw new BatfishException("int expr transfer function: " + e);
  }

  /*
   * Create a constraint that the metric field does not overflow
   * for a given routing protocol.
   */
  private BoolExpr noOverflow(ArithExpr metric, Protocol proto) {
    if (!_enc.getEncoder().getQuestion().getModelOverflow()) {
      return _enc.mkTrue();
    }
    if (proto.isConnected()) {
      return _enc.mkTrue();
    }
    if (proto.isStatic()) {
      return _enc.mkTrue();
    }
    if (proto.isOspf()) {
      return _enc.mkLe(metric, _enc.mkInt(65535));
    }
    if (proto.isBgp()) {
      return _enc.mkLe(metric, _enc.mkInt(255));
    }
    throw new BatfishException("Encoding[noOverflow]: unrecognized protocol: " + proto.name());
  }

  /*
   * Compute how many times to prepend to a path from the AST
   */
  private int prependLength(AsPathListExpr expr) {
    if (expr instanceof MultipliedAs) {
      MultipliedAs x = (MultipliedAs) expr;
      IntExpr e = x.getNumber();
      LiteralInt i = (LiteralInt) e;
      return i.getValue();
    }
    if (expr instanceof LiteralAsList) {
      LiteralAsList x = (LiteralAsList) expr;
      return x.getList().size();
    }
    throw new BatfishException("Error[prependLength]: unreachable");
  }

  private ArithExpr prependLengthVar (AsPathListExpr expr) {
    if (!expr.getEnableSmtVariable()) {
      throw new BatfishException("Encoding[prependLengthVar]: unreachable");
    }
    return expr.getConfigVarPrepend();
  }

  /*
   * Get the BgpPeerConfig object given the current
   * graph edge and protocol information
   */
  private BgpPeerConfig getBgpNeighbor() {
    Graph g = _enc.getGraph();
    if (_graphEdge.isAbstract()) {
      return g.getIbgpNeighbors().get(_graphEdge);
    } else {
      return g.getEbgpNeighbors().get(_graphEdge);
    }
  }

  /*
   * Determine if BGP communities should be
   * sent to/from the neighboring BGP peer.
   */
  private boolean sendCommunity() {
    if (_proto.isBgp()) {
      if (!_isExport) {
        return true;
      }
      BgpPeerConfig n = getBgpNeighbor();
      return n.getIpv4UnicastAddressFamily().getAddressFamilyCapabilities().getSendCommunity();
    } else {
      return false;
    }
  }

  /*
   * Relate the symbolic control plane route variables
   */
  private BoolExpr relateVariables(
      TransferParam<SymbolicRouteBV> p, TransferResult<BoolExpr, BoolExpr> result) {

    ArithExpr defaultLen = _enc.mkInt(_enc.defaultLength());
    ArithExpr defaultAd = _enc.defaultAdminDistance(_conf, _proto, p.getData());
    ArithExpr defaultMed = _enc.mkInt(_enc.defaultMed(_proto));
    ArithExpr defaultLp = _enc.mkInt(_enc.defaultLocalPref());
    ArithExpr defaultId = _enc.mkInt(_enc.defaultId());
    ArithExpr defaultMet = _enc.mkInt(_enc.defaultMetric());

    // TODO: remove all isChanged calls with actual symbolic values that test for a change

    boolean isIbgp = _graphEdge.isAbstract() && _proto.isBgp();

    // Update prefix length when aggregation
    BoolExpr len =
        _enc.safeEq(
            _current.getPrefixLength(), getOrDefault(p.getData().getPrefixLength(), defaultLen));
    BoolExpr per = _enc.safeEq(_current.getPermitted(), p.getData().getPermitted());

    // Only update the router id for import edges
    BoolExpr id = _enc.mkTrue();
    if (!_isExport) {
      id = _enc.safeEq(_current.getRouterId(), getOrDefault(p.getData().getRouterId(), defaultId));
    }

    // Update OSPF area id
    BoolExpr area;
    if (p.getData().getOspfArea() == null || _iface.getOspfAreaName() == null) {
      area = _enc.mkTrue();
    } else {
      area = _enc.safeEqEnum(_current.getOspfArea(), _iface.getOspfAreaName());
    }

    // Set the IGP metric accordingly
    BoolExpr igpMet = _enc.mkTrue();
    boolean isNonClient =
        _graphEdge.isAbstract()
            && (_enc.getGraph().peerType(_graphEdge) != Graph.BgpSendType.TO_EBGP);
    boolean isClient =
        _graphEdge.isAbstract()
            && (_enc.getGraph().peerType(_graphEdge) == Graph.BgpSendType.TO_RR);

    if (_graphEdge.isAbstract() && _current.getIgpMetric() != null) {
      String router = _graphEdge.getRouter();
      String peer = _graphEdge.getPeer();

      // Case where it is a non client, we lookup the next-hop
      if (isNonClient) {
        EncoderSlice s = _enc.getEncoder().getSlice(peer);
        SymbolicRouteBV r = s.getSymbolicDecisions().getBestNeighbor().get(router);
        igpMet = _enc.mkEq(_current.getIgpMetric(), r.getMetric());
      }

      // Case where it is a client, next-hop depends on the clientId tag we added
      if (isClient) {
        BoolExpr acc = _enc.mkTrue();
        for (Map.Entry<String, Integer> entry : _enc.getGraph().getOriginatorId().entrySet()) {
          String r = entry.getKey();
          Integer clientId = entry.getValue();
          if (!r.equals(router)) {
            EncoderSlice s = _enc.getEncoder().getSlice(r);
            SymbolicRouteBV record = s.getSymbolicDecisions().getBestNeighbor().get(r);
            BoolExpr eq = _enc.mkEq(_current.getIgpMetric(), record.getMetric());
            acc =
                _enc.mkAnd(
                    acc, _enc.mkImplies(p.getData().getClientId().checkIfValue(clientId), eq));
          }
        }
        igpMet = acc;
      }
    }

    // Set whether or not is iBGP or not on import
    BoolExpr isInternal =
        _enc.safeEq(_current.getBgpInternal(), _enc.mkBool(isIbgp)); // TODO: and !isExport?

    // Update OSPF type
    BoolExpr type;
    if (result.isChanged("OSPF-TYPE")) {
      type = _enc.safeEqEnum(_current.getOspfType(), p.getData().getOspfType());
    } else {
      boolean hasAreaIface = _iface.getOspfAreaName() != null;
      boolean hasArea = p.getData().getOspfArea() != null;
      boolean hasType = p.getData().getOspfType() != null;
      boolean areaPossiblyChanged = hasType && hasArea && hasAreaIface;
      // Check if area changed
      if (areaPossiblyChanged) {
        BoolExpr internal = p.getData().getOspfType().isInternal();
        BoolExpr same = p.getData().getOspfArea().checkIfValue(_iface.getOspfAreaName());
        BoolExpr update = _enc.mkAnd(internal, _enc.mkNot(same));
        BoolExpr copyOld = _enc.safeEqEnum(_current.getOspfType(), p.getData().getOspfType());
        type = _enc.mkIf(update, _current.getOspfType().checkIfValue(OspfType.OIA), copyOld);
      } else {
        type = _enc.safeEqEnum(_current.getOspfType(), p.getData().getOspfType());
      }
    }

    BoolExpr comms = _enc.safeEq(_current.getCommunitiesBitVec(), p.getData().getCommunitiesBitVec());

    ArithExpr otherAd =
        (p.getData().getAdminDist() == null ? defaultAd : p.getData().getAdminDist());
    ArithExpr otherMed = (p.getData().getMed() == null ? defaultMed : p.getData().getMed());
    ArithExpr otherLp = getOrDefault(p.getData().getLocalPref(), defaultLp);
    ArithExpr otherMet = getOrDefault(p.getData().getMetric(), defaultMet);
    // otherMet = applyMetricUpdate(otherMet);

    BoolExpr ad = _enc.safeEq(_current.getAdminDist(), otherAd);
    BoolExpr history = _enc.equalHistories(_current, p.getData());
    BoolExpr med = _enc.safeEq(_current.getMed(), otherMed);
    BoolExpr met = _enc.safeEq(_current.getMetric(), otherMet);
    BoolExpr lp = _enc.safeEq(_current.getLocalPref(), otherLp);

    // If this was an external route, then we need to add the correct next-hop tag
    boolean isEbgpEdge = _enc.getGraph().getEbgpNeighbors().get(_graphEdge) != null;
    BoolExpr cid = _enc.mkTrue();
    if (_isExport && _proto.isBgp() && p.getData().getClientId() != null) {
      if (isEbgpEdge) {
        cid = _current.getClientId().checkIfValue(0);
      } else {
        cid = _enc.safeEqEnum(_current.getClientId(), p.getData().getClientId());
      }
    }
    if (!_isExport && _proto.isBgp() && p.getData().getClientId() != null) {
      BoolExpr fromExternal = p.getData().getClientId().checkIfValue(0);
      BoolExpr edgeIsInternal = _enc.mkBool(!isClient && !isNonClient);
      BoolExpr copyOver = _enc.safeEqEnum(_current.getClientId(), p.getData().getClientId());
      Integer x = _enc.getGraph().getOriginatorId().get(_graphEdge.getRouter());
      SymbolicOriginatorId soid = _current.getClientId();
      BoolExpr setNewValue = (x == null ? soid.checkIfValue(0) : soid.checkIfValue(x));
      cid = _enc.mkIf(_enc.mkAnd(fromExternal, edgeIsInternal), setNewValue, copyOver);
    }

    BoolExpr updates =
        _enc.mkAnd(
            per, len, ad, med, lp, met, id, cid, type, area, comms, history, isInternal, igpMet);
    BoolExpr noOverflow = noOverflow(otherMet, _proto);

    return _enc.mkIf(noOverflow, updates, _enc.mkNot(_current.getPermitted()));
  }

  /*
   * Create a new variable reflecting the final return value of the function
   */
  private TransferResult<BoolExpr, BoolExpr> returnValue(
      TransferParam<SymbolicRouteBV> p, TransferResult<BoolExpr, BoolExpr> r, boolean val) {
    BoolExpr b = _enc.mkIf(r.getReturnAssignedValue(), r.getReturnValue(), _enc.mkBool(val));
    BoolExpr newRet = createBoolVariableWith(p, "RETURN", b);
    return r.setReturnValue(newRet)
        .setReturnAssignedValue(_enc.mkTrue())
        .addChangedVariable("RETURN", newRet);
  }

  private TransferResult<BoolExpr, BoolExpr> fallthrough(
      TransferParam<SymbolicRouteBV> p, TransferResult<BoolExpr, BoolExpr> r) {
    BoolExpr b = _enc.mkIf(r.getReturnAssignedValue(), r.getFallthroughValue(), _enc.mkTrue());
    BoolExpr newFallthrough = createBoolVariableWith(p, "FALLTHROUGH", b);
    return r.setFallthroughValue(newFallthrough)
        .setReturnAssignedValue(_enc.mkTrue())
        .addChangedVariable("FALLTHROUGH", newFallthrough);
  }

  // private void collectMatchLineEnables(BooleanExpr expr, List<BoolExpr> enables) {
  //   if (expr instanceof MatchPrefixSet) {
  //     MatchPrefixSet mps = (MatchPrefixSet) expr;
  //     if (mps.getEnableSmtVariable() && mps.getConfigLineEnable() != null) {
  //       enables.add(mps.getConfigLineEnable());
  //     }
  //   } else if (expr instanceof MatchCommunitySet) {
  //     MatchCommunitySet mcs = (MatchCommunitySet) expr;
  //     if (mcs.getEnableSmtVariable() && mcs.getConfigLineEnable() != null) {
  //       enables.add(mcs.getConfigLineEnable());
  //     }
  //   } else if (expr instanceof Conjunction) {
  //     for (BooleanExpr conjunct : ((Conjunction) expr).getConjuncts()) {
  //       collectMatchLineEnables(conjunct, enables);
  //     }
  //   } else if (expr instanceof Disjunction) {
  //     for (BooleanExpr disjunct : ((Disjunction) expr).getDisjuncts()) {
  //       collectMatchLineEnables(disjunct, enables);
  //     }
  //   } else if (expr instanceof Not) {
  //     collectMatchLineEnables(((Not) expr).getExpr(), enables);
  //   } else if (expr instanceof WithEnvironmentExpr) {
  //     collectMatchLineEnables(((WithEnvironmentExpr) expr).getExpr(), enables);
  //   }
  // }

  // private BoolExpr applyEntryEnable(BooleanExpr guardExpr, BoolExpr guard) {
  //   List<BoolExpr> matchEnables = new ArrayList<>();
  //   collectMatchLineEnables(guardExpr, matchEnables);
  //   if (matchEnables.isEmpty()) {
  //     return guard;
  //   }
  //   BoolExpr anyEnabled = _enc.mkFalse();
  //   for (BoolExpr enable : matchEnables) {
  //     anyEnabled = _enc.mkOr(anyEnabled, enable);
  //   }
  //   return _enc.mkAnd(guard, anyEnabled);
  // }

  private void updateSingleValue(TransferParam<SymbolicRouteBV> p, String variableName, Expr expr) {
    switch (variableName) {
      case "METRIC":
        p.getData().setMetric((ArithExpr) expr);
        break;
      case "MED":
        p.getData().setMed((ArithExpr) expr);
        break;
      case "PREFIX-LEN":
        p.getData().setPrefixLength((ArithExpr) expr);
        break;
      case "ADMIN-DIST":
        p.getData().setAdminDist((ArithExpr) expr);
        break;
      case "LOCAL-PREF":
        p.getData().setLocalPref((ArithExpr) expr);
        break;
      case "OSPF-TYPE":
        p.getData().getOspfType().setBitVec((BitVecExpr) expr);
        break;
      case "COMMUNITIES":
        // NOTE: modified update community value (BoolExpr -> BitVecExpr communities)
        p.getData().setCommunitiesBitVec((BitVecExpr) expr);
        break;
      case "RETURN":
        break;
      case "FALLTHROUGH":
        break;
      default:
        // for (Map.Entry<CommunityVar, BoolExpr> entry : p.getData().getCommunities().entrySet()) {
        //   CommunityVar cvar = entry.getKey();
        //   if (variableName.equals(cvar.getRegex())) {
        //     p.getData().getCommunities().put(cvar, (BoolExpr) expr);
        //     return;
        //   }
        // }

        throw new BatfishException("Unimplemented: update for " + variableName);
    }
  }

  /*
   * The [phi] function from SSA that merges variables that may differ across
   * different branches of an If statement.
   */
  private MsPair<Expr, Expr> joinPoint(
      TransferParam<SymbolicRouteBV> p,
      TransferResult<BoolExpr, BoolExpr> r,
      BoolExpr guard,
      MsPair<String, MsPair<Expr, Expr>> values) {
    String variableName = values.getFirst();
    Expr trueBranch = values.getSecond().getFirst();
    Expr falseBranch = values.getSecond().getSecond();

    if (variableName.equals("RETURN") || variableName.equals("FALLTHROUGH")) {
      Expr t =
          (trueBranch == null
              ? _enc.mkFalse()
              : trueBranch); // can use False because the value has not been assigned
      Expr f = (falseBranch == null ? _enc.mkFalse() : falseBranch);
      Expr tass = (trueBranch == null ? r.getReturnAssignedValue() : _enc.mkTrue());
      Expr fass = (falseBranch == null ? r.getReturnAssignedValue() : _enc.mkTrue());
      BoolExpr newAss = _enc.mkIf(guard, (BoolExpr) tass, (BoolExpr) fass);
      BoolExpr retAss = createBoolVariableWith(p, "ASSIGNED", newAss);
      BoolExpr variable =
          (variableName.equals("RETURN") ? r.getReturnValue() : r.getFallthroughValue());
      BoolExpr newValue =
          _enc.mkIf(
              r.getReturnAssignedValue(), variable, _enc.mkIf(guard, (BoolExpr) t, (BoolExpr) f));
      BoolExpr ret = createBoolVariableWith(p, variableName, newValue);
      return new MsPair<>(ret, retAss);
    }

    if (variableName.equals("PREFIX-LEN")) {
      Expr t = (trueBranch == null ? p.getData().getPrefixLength() : trueBranch);
      Expr f = (falseBranch == null ? p.getData().getPrefixLength() : falseBranch);
      ArithExpr newValue = _enc.mkIf(guard, (ArithExpr) t, (ArithExpr) f);
      newValue = _enc.mkIf(r.getReturnAssignedValue(), p.getData().getPrefixLength(), newValue);
      ArithExpr ret = createArithVariableWith(p, "PREFIX-LEN", newValue);
      p.getData().setPrefixLength(ret);
      return new MsPair<>(ret, null);
    }
    if (variableName.equals("ADMIN-DIST")) {
      Expr t = (trueBranch == null ? p.getData().getAdminDist() : trueBranch);
      Expr f = (falseBranch == null ? p.getData().getAdminDist() : falseBranch);
      ArithExpr newValue = _enc.mkIf(guard, (ArithExpr) t, (ArithExpr) f);
      newValue = _enc.mkIf(r.getReturnAssignedValue(), p.getData().getAdminDist(), newValue);
      ArithExpr ret = createArithVariableWith(p, "ADMIN-DIST", newValue);
      p.getData().setAdminDist(ret);
      return new MsPair<>(ret, null);
    }
    if (variableName.equals("LOCAL-PREF")) {
      Expr t = (trueBranch == null ? p.getData().getLocalPref() : trueBranch);
      Expr f = (falseBranch == null ? p.getData().getLocalPref() : falseBranch);
      ArithExpr newValue = _enc.mkIf(guard, (ArithExpr) t, (ArithExpr) f);
      newValue = _enc.mkIf(r.getReturnAssignedValue(), p.getData().getLocalPref(), newValue);
      ArithExpr ret = createArithVariableWith(p, "LOCAL-PREF", newValue);
      p.getData().setLocalPref(ret);
      return new MsPair<>(ret, null);
    }
    if (variableName.equals("METRIC")) {
      Expr t = (trueBranch == null ? p.getData().getMetric() : trueBranch);
      Expr f = (falseBranch == null ? p.getData().getMetric() : falseBranch);
      ArithExpr newValue = _enc.mkIf(guard, (ArithExpr) t, (ArithExpr) f);
      newValue = _enc.mkIf(r.getReturnAssignedValue(), p.getData().getMetric(), newValue);
      ArithExpr ret = createArithVariableWith(p, "METRIC", newValue);
      p.getData().setMetric(ret);
      return new MsPair<>(ret, null);
    }
    if (variableName.equals("MED")) {
      Expr t = (trueBranch == null ? p.getData().getMed() : trueBranch);
      Expr f = (falseBranch == null ? p.getData().getMed() : falseBranch);
      ArithExpr newValue = _enc.mkIf(guard, (ArithExpr) t, (ArithExpr) f);
      newValue = _enc.mkIf(r.getReturnAssignedValue(), p.getData().getMed(), newValue);
      ArithExpr ret = createArithVariableWith(p, "METRIC", newValue);
      p.getData().setMed(ret);
      return new MsPair<>(ret, null);
    }
    if (variableName.equals("OSPF-TYPE")) {
      Expr t = (trueBranch == null ? p.getData().getOspfType().getBitVec() : trueBranch);
      Expr f = (falseBranch == null ? p.getData().getOspfType().getBitVec() : falseBranch);
      BitVecExpr newValue = _enc.mkIf(guard, (BitVecExpr) t, (BitVecExpr) f);
      newValue =
          _enc.mkIf(r.getReturnAssignedValue(), p.getData().getOspfType().getBitVec(), newValue);
      BitVecExpr ret = createBitVecVariableWith(p, "OSPF-TYPE", 2, newValue);
      p.getData().getOspfType().setBitVec(ret);
      return new MsPair<>(ret, null);
    }

    // TODO: Improve this to avoid looping over all communities.
    // for (Map.Entry<CommunityVar, BoolExpr> entry : p.getData().getCommunities().entrySet()) {
    //   CommunityVar cvar = entry.getKey();
    //   if (variableName.equals(cvar.getRegex())) {
    //     Expr t = (trueBranch == null ? p.getData().getCommunities().get(cvar) : trueBranch);
    //     Expr f = (falseBranch == null ? p.getData().getCommunities().get(cvar) : falseBranch);
    //     BoolExpr newValue = _enc.mkIf(guard, (BoolExpr) t, (BoolExpr) f);
    //     newValue =
    //         _enc.mkIf(r.getReturnAssignedValue(), p.getData().getCommunities().get(cvar), newValue);
    //     BoolExpr ret = createBoolVariableWith(p, cvar.getRegex(), newValue);
    //     p.getData().getCommunities().put(cvar, ret);
    //     return new MsPair<>(ret, null);
    //   }
    // }

    // NOTE: modified join point for communities (BoolExpr -> BitVecExpr communities)
    if (variableName.equals("COMMUNITIES")) {
      Expr t = (trueBranch == null ? p.getData().getCommunitiesBitVec() : trueBranch);
      Expr f = (falseBranch == null ? p.getData().getCommunitiesBitVec() : falseBranch);
      BitVecExpr newValue = _enc.mkIf(guard, (BitVecExpr) t, (BitVecExpr) f);
      newValue =
          _enc.mkIf(r.getReturnAssignedValue(), p.getData().getCommunitiesBitVec(), newValue);
      BitVecExpr ret =
          createBitVecVariableWith(p, "COMMUNITIES", _commsIndex.size(), newValue);
      p.getData().setCommunitiesBitVec(ret);
      return new MsPair<>(ret, null);
    }

    throw new BatfishException("[joinPoint]: unhandled case for " + variableName);
  }

  /*
   * Convert a list of statements into a Z3 boolean expression for the transfer function.
   */
  private TransferResult<BoolExpr, BoolExpr> compute(
      List<Statement> statements,
      TransferParam<SymbolicRouteBV> p,
      TransferResult<BoolExpr, BoolExpr> result) {
    TransferParam<SymbolicRouteBV> curP = p;
    TransferResult<BoolExpr, BoolExpr> curResult = result;
    boolean doesReturn = false;

    for (Statement stmt : statements) {

      if (stmt instanceof StaticStatement) {
        StaticStatement ss = (StaticStatement) stmt;

        switch (ss.getType()) {
          case ExitAccept:
            doesReturn = true;
            curP.debug("ExitAccept");
            curResult = returnValue(curP, curResult, true);
            break;

          case Unsuppress:
          case ReturnTrue:
            // TODO: implement proper unsuppression of routes covered by aggregates
            doesReturn = true;
            curP.debug("ReturnTrue");
            curResult = returnValue(curP, curResult, true);
            break;

          case ExitReject:
            doesReturn = true;
            curP.debug("ExitReject");
            curResult = returnValue(curP, curResult, false);
            break;

          case Suppress:
          case ReturnFalse:
            // TODO: implement proper suppression of routes covered by aggregates
            doesReturn = true;
            curP.debug("ReturnFalse");
            curResult = returnValue(curP, curResult, false);
            break;

          case SetDefaultActionAccept:
            curP.debug("SetDefaulActionAccept");
            curP = curP.setDefaultAccept(true);
            break;

          case SetDefaultActionReject:
            curP.debug("SetDefaultActionReject");
            curP = curP.setDefaultAccept(false);
            break;

          case SetLocalDefaultActionAccept:
            curP.debug("SetLocalDefaultActionAccept");
            curP = curP.setDefaultAcceptLocal(true);
            break;

          case SetLocalDefaultActionReject:
            curP.debug("SetLocalDefaultActionReject");
            curP = curP.setDefaultAcceptLocal(false);
            break;

          case ReturnLocalDefaultAction:
            curP.debug("ReturnLocalDefaultAction");
            // TODO: need to set local default action in an environment
            if (curP.getDefaultAcceptLocal()) {
              curResult = returnValue(curP, curResult, true);
            } else {
              curResult = returnValue(curP, curResult, false);
            }
            break;

          case FallThrough:
            curP.debug("Fallthrough");
            curResult = fallthrough(curP, curResult);
            break;

          case Return:
            // TODO: assumming this happens at the end of the function, so it is ignored for now.
            curP.debug("Return");
            break;

          case RemovePrivateAs:
            curP.debug("RemovePrivateAs");
            curP.debug("Warning: use of unimplemented feature RemovePrivateAs");
            break;

          default:
            throw new BatfishException("TODO: computeTransferFunction: " + ss.getType());
        }

      } else if (stmt instanceof If) {
        curP.debug("If");
        If i = (If) stmt;
        TransferResult<BoolExpr, BoolExpr> r = compute(i.getGuard(), curP);
        curResult = curResult.addChangedVariables(r);
        BoolExpr guard = (BoolExpr) r.getReturnValue();
        // entryEnable: all match lineEnables false -> skip entry (else branch)
        // guard = applyEntryEnable(i.getGuard(), guard);
        guard = (BoolExpr) guard.simplify();
        String str = guard.toString();

        // If there are updates in the guard, add them to the parameter p before entering branches
        for (MsPair<String, Expr> changed : r.getChangedVariables()) {
          curP.debug("CHANGED: " + changed.getFirst());
          updateSingleValue(curP, changed.getFirst(), changed.getSecond());
        }

        curP.debug("guard: " + str);
        // If we know the branch ahead of time, then specialize
        switch (str) {
          case "true":
            curP.debug("True Branch");
            // BUGFIX: propagate If guard to AddCommunity in this term
            curResult =
                compute(
                    i.getTrueStatements(), curP.indent().setTermGuard(_enc.mkTrue()), curResult);
            break;
          case "false":
            curP.debug("False Branch");
            compute(
                i.getFalseStatements(), curP.indent().setTermGuard(_enc.mkFalse()), curResult);
            break;
          default:
            curP.debug("True Branch");
            // clear changed variables before proceeding
            TransferParam<SymbolicRouteBV> p1 =
                curP.indent().setData(curP.getData().copy()).setTermGuard(guard);
            TransferParam<SymbolicRouteBV> p2 =
                curP.indent().setData(curP.getData().copy()).setTermGuard(_enc.mkNot(guard));

            TransferResult<BoolExpr, BoolExpr> trueBranch =
                compute(i.getTrueStatements(), p1, initialResult());
            curP.debug("False Branch");
            TransferResult<BoolExpr, BoolExpr> falseBranch =
                compute(i.getFalseStatements(), p2, initialResult());
            curP.debug("JOIN");
            PList<MsPair<String, MsPair<Expr, Expr>>> pairs =
                trueBranch.mergeChangedVariables(falseBranch);

            // Extract and deal with the return value first so that other
            // variables have this reflected in their value
            int idx = pairs.find(pair -> pair.getFirst().equals("RETURN"));
            if (idx >= 0) {
              MsPair<String, MsPair<Expr, Expr>> ret = pairs.get(idx);
              pairs = pairs.minus(idx);
              pairs = pairs.plus(pairs.size(), ret);
            }

            for (MsPair<String, MsPair<Expr, Expr>> pair : pairs) {
              String s = pair.getFirst();
              curP.debug("CHANGED: " + s);
              MsPair<Expr, Expr> x = joinPoint(curP, curResult, guard, pair);
              curResult = curResult.addChangedVariable(s, x.getFirst());
              if (s.equals("RETURN")) {
                curResult =
                    curResult
                        .setReturnValue((BoolExpr) x.getFirst())
                        .setReturnAssignedValue((BoolExpr) x.getSecond());
              }
              if (s.equals("FALLTHROUGH")) {
                curResult =
                    curResult
                        .setFallthroughValue((BoolExpr) x.getFirst())
                        .setReturnAssignedValue((BoolExpr) x.getSecond());
              }
            }

            break;
        }

      } else if (stmt instanceof SetDefaultPolicy) {
        curP.debug("SetDefaultPolicy");
        curP = curP.setDefaultPolicy((SetDefaultPolicy) stmt);

      } else if (stmt instanceof SetMetric) {
        curP.debug("SetMetric");
        // TODO: what is the semantics for BGP? Is this MED?
        // NOTE: SetMetric meaning set MED in BGP route-map.
        if (!_current.getProto().isBgp()) {
          SetMetric sm = (SetMetric) stmt;
          LongExpr ie = sm.getMetric();
          ArithExpr newValue = applyLongExprModification(curP.getData().getMetric(), ie);
          newValue = _enc.mkIf(curResult.getReturnAssignedValue(), curP.getData().getMetric(), newValue);
          ArithExpr x = createArithVariableWith(curP, "METRIC", newValue);
          curP.getData().setMetric(x);
          curResult = curResult.addChangedVariable("METRIC", x);
        } else {
          SetMetric sm = (SetMetric) stmt;
          LongExpr ie = sm.getMetric();
          ArithExpr newValue = applyLongExprModification(curP.getData().getMed(), ie);
          newValue = _enc.mkIf(curResult.getReturnAssignedValue(), curP.getData().getMed(), newValue);
          ArithExpr x = createArithVariableWith(curP, "MED", newValue);
          curP.getData().setMed(x);
          curResult = curResult.addChangedVariable("MED", x);

          // TODO: symbolic encoding for the configuration and the line enable
        }

      } else if (stmt instanceof SetOspfMetricType) {
        curP.debug("SetOspfMetricType");
        SetOspfMetricType somt = (SetOspfMetricType) stmt;
        OspfMetricType mt = somt.getMetricType();
        SymbolicOspfType t;
        if (mt == OspfMetricType.E1) {
          t = new SymbolicOspfType(_enc, OspfType.E1);
        } else {
          t = new SymbolicOspfType(_enc, OspfType.E2);
        }
        BitVecExpr newValue = t.getBitVec();
        newValue =
            _enc.mkIf(
                curResult.getReturnAssignedValue(),
                curP.getData().getOspfType().getBitVec(),
                newValue);
        BitVecExpr x = createBitVecVariableWith(curP, "OSPF-TYPE", 2, newValue);
        curP.getData().getOspfType().setBitVec(x);
        curResult = curResult.addChangedVariable("OSPF-TYPE", x);

      } else if (stmt instanceof SetLocalPreference) {
        curP.debug("SetLocalPreference");
        SetLocalPreference slp = (SetLocalPreference) stmt;
        LongExpr ie = slp.getLocalPreference();
        if (!slp.getEnableSmtVariable()) {
          ArithExpr newValue = applyLongExprModification(curP.getData().getLocalPref(), ie);
          newValue = _enc.mkIf(curResult.getReturnAssignedValue(), curP.getData().getLocalPref(), newValue);
          ArithExpr x = createArithVariableWith(curP, "LOCAL-PREF", newValue);
          curP.getData().setLocalPref(x);
          curResult = curResult.addChangedVariable("LOCAL-PREF", x);
        } else {
          // TODO: symbolic encoding for the configuration and the line enable
          ArithExpr newValue = applyLongExprModification(curP.getData().getLocalPref(), ie);
          newValue = _enc.mkIf(curResult.getReturnAssignedValue(), curP.getData().getLocalPref(), newValue);
          ArithExpr x = createArithVariableWith(curP, "LOCAL-PREF", newValue);
          curP.getData().setLocalPref(x);
          curResult = curResult.addChangedVariable("LOCAL-PREF", x);
        }

      } else if (stmt instanceof AddCommunity) {
        // curP.debug("AddCommunity");
        // AddCommunity ac = (AddCommunity) stmt;
        // Set<CommunityVar> comms = collectCommunityVars(_conf, ac.getExpr());
        //
        // BoolExpr lineEnable = ac.getConfigLineEnable();
        //
        // if (!ac.getEnableSmtVariable()) {
        //   for (CommunityVar cvar : comms) {
        //     BoolExpr newValue =
        //         _enc.mkIf(
        //             curResult.getReturnAssignedValue(),
        //             curP.getData().getCommunities().get(cvar),
        //             _enc.mkTrue());
        //     BoolExpr x = createBoolVariableWith(curP, cvar.getRegex(), newValue);
        //     curP.getData().getCommunities().put(cvar, x);
        //     curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //   }
        // } else {
        //   for (CommunityVar cvar : comms) {
        //     BoolExpr community = cvar.getLiteralValue().getConfigVarCommunity();
        //     BoolExpr community_origin = curP.getData().getCommunities().get(cvar);
        //     BoolExpr communityEqual = _enc.mkEq(community, community_origin);
        //     BoolExpr newValue =
        //         _enc.mkIf(
        //             // curResult.getReturnAssignedValue(),
        //             // communityEqual,
        //             // _enc.mkTrue());
        //             curResult.getReturnAssignedValue(),
        //             curP.getData().getCommunities().get(cvar),
        //             community);
        //     BoolExpr newX = createBoolVariableWith(curP, cvar.getRegex(), newValue);
        //     BoolExpr oldX = curP.getData().getCommunities().get(cvar);
        //     // BoolExpr x = newX;
        //     // curP.getData().getCommunities().put(cvar, x);
        //     // curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //     // NOTE: symbolic encoding for the line enable
        //     BoolExpr x = _enc.mkIf(lineEnable, newX, oldX);
        //     curP.getData().getCommunities().put(cvar, x);
        //     curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //   }
        // }

        curP.debug("AddCommunity");
        AddCommunity ac = (AddCommunity) stmt;
        Set<CommunityVar> comms = collectCommunityVars(_conf, ac.getExpr());

        BitVecExpr x = configCommunities(
            curP, curResult, ac.getEnableSmtVariable(), null, // ac.getConfigLineEnable(),
            comms, ac.getConfigVarPrefix(), ac.getClass().getName());
        curP.getData().setCommunitiesBitVec(x);
        curResult = curResult.addChangedVariable("COMMUNITIES", x);

      } else if (stmt instanceof SetCommunity) {
        // curP.debug("SetCommunity");
        // SetCommunity sc = (SetCommunity) stmt;
        // Set<CommunityVar> comms = collectCommunityVars(_conf, sc.getExpr());
        //
        // BoolExpr lineEnable = sc.getConfigLineEnable();
        //
        // if (!sc.getEnableSmtVariable()) {
        //   for (CommunityVar cvar : comms) {
        //     BoolExpr newValue =
        //         _enc.mkIf(
        //             curResult.getReturnAssignedValue(),
        //             curP.getData().getCommunities().get(cvar),
        //             _enc.mkTrue());
        //
        //     BoolExpr x = createBoolVariableWith(curP, cvar.getRegex(), newValue);
        //     curP.getData().getCommunities().put(cvar, x);
        //     curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //   }
        // } else {
        //   for (CommunityVar cvar : comms) {
        //     BoolExpr community = cvar.getLiteralValue().getConfigVarCommunity();
        //     BoolExpr community_origin = curP.getData().getCommunities().get(cvar);
        //     BoolExpr communityEqual = _enc.mkEq(community, community_origin);
        //     BoolExpr newValue =
        //         _enc.mkIf(
        //             // curResult.getReturnAssignedValue(),
        //             // communityEqual,
        //             // _enc.mkTrue());
        //             curResult.getReturnAssignedValue(),
        //             curP.getData().getCommunities().get(cvar),
        //             community);
        //     BoolExpr newX = createBoolVariableWith(curP, cvar.getRegex(), newValue);
        //     BoolExpr oldX = curP.getData().getCommunities().get(cvar);
        //     // BoolExpr x = newX;
        //     // curP.getData().getCommunities().put(cvar, x);
        //     // curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //     // NOTE: symbolic encoding for the enable line
        //     BoolExpr x = _enc.mkIf(lineEnable, newX, oldX);
        //     curP.getData().getCommunities().put(cvar, x);
        //     curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //   }
        // }
        //
        // // BUGFIX: set community to false for other community variables
        // for (CommunityVar cvar_other : curP.getData().getCommunities().keySet()) {
        //   // Skip those communities that are set by this statement
        //   if (comms.contains(cvar_other)) {
        //     continue;
        //   }
        //   // Skip regex community variables
        //   if (cvar_other.getType() == Type.REGEX) {
        //     continue;
        //   }
        //
        //   // Set other community variables to false
        //   BoolExpr newValue_other =
        //       _enc.mkIf(
        //           curResult.getReturnAssignedValue(),
        //           curP.getData().getCommunities().get(cvar_other),
        //           _enc.mkFalse());
        //   BoolExpr newX_other = createBoolVariableWith(curP, cvar_other.getRegex(), newValue_other);
        //   BoolExpr oldX_other = curP.getData().getCommunities().get(cvar_other);
        //   // BoolExpr x_other = newX_other;
        //   // curP.getData().getCommunities().put(cvar_other, x_other);
        //   // curResult = curResult.addChangedVariable(cvar_other.getRegex(), x_other);
        //   // NOTE: symbolic encoding for the enable line
        //   BoolExpr x_other = _enc.mkIf(lineEnable, newX_other, oldX_other);
        //   curP.getData().getCommunities().put(cvar_other, x_other);
        //   curResult = curResult.addChangedVariable(cvar_other.getRegex(), x_other);
        // }

        curP.debug("SetCommunity");
        SetCommunity sc = (SetCommunity) stmt;
        Set<CommunityVar> comms = collectCommunityVars(_conf, sc.getExpr());

        BitVecExpr x = configCommunities(
            curP, curResult, sc.getEnableSmtVariable(), null, // sc.getConfigLineEnable(),
            comms, sc.getConfigVarPrefix(), sc.getClass().getName());
        curP.getData().setCommunitiesBitVec(x);
        curResult = curResult.addChangedVariable("COMMUNITIES", x);

      } else if (stmt instanceof DeleteCommunity) {
        // curP.debug("DeleteCommunity");
        // DeleteCommunity dc = (DeleteCommunity) stmt;
        // Set<CommunityVar> comms = collectCommunityVars(_conf, dc.getExpr());
        // Set<CommunityVar> toDelete = new HashSet<>();
        //
        // // Find communities to delete
        // for (CommunityVar cvar : comms) {
        //   if (cvar.getType() == Type.REGEX) {
        //     toDelete.addAll(_enc.getCommunityDependencies().get(cvar));
        //   } else {
        //     toDelete.add(cvar);
        //   }
        // }
        //
        // BoolExpr lineEnable = dc.getConfigLineEnable();
        //
        // if (!dc.getEnableSmtVariable()) {
        //   for (CommunityVar cvar : toDelete) {
        //     BoolExpr newValue =
        //         _enc.mkIf(
        //             curResult.getReturnAssignedValue(),
        //             curP.getData().getCommunities().get(cvar),
        //             _enc.mkFalse());
        //     BoolExpr x = createBoolVariableWith(curP, cvar.getRegex(), newValue);
        //     curP.getData().getCommunities().put(cvar, x);
        //     curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //   }
        // } else {
        //   for (CommunityVar cvar : toDelete) {
        //     BoolExpr community = cvar.getLiteralValue().getConfigVarCommunity();
        //     BoolExpr community_origin = curP.getData().getCommunities().get(cvar);
        //     BoolExpr communityEqual = _enc.mkEq(community, community_origin);
        //     BoolExpr newValue =
        //         _enc.mkIf(
        //             // curResult.getReturnAssignedValue(),
        //             // communityEqual,
        //             // _enc.mkFalse());
        //             curResult.getReturnAssignedValue(),
        //             curP.getData().getCommunities().get(cvar),
        //             _enc.mkNot(community));
        //     BoolExpr newX = createBoolVariableWith(curP, cvar.getRegex(), newValue);
        //     BoolExpr oldX = curP.getData().getCommunities().get(cvar);
        //     // BoolExpr x = newX;
        //     // curP.getData().getCommunities().put(cvar, x);
        //     // curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //     // NOTE: symbolic encoding for the enable line
        //     BoolExpr x = _enc.mkIf(lineEnable, newX, oldX);
        //     curP.getData().getCommunities().put(cvar, x);
        //     curResult = curResult.addChangedVariable(cvar.getRegex(), x);
        //   }
        // }

        curP.debug("DeleteCommunity");
        DeleteCommunity dc = (DeleteCommunity) stmt;
        Set<CommunityVar> comms = collectCommunityVars(_conf, dc.getExpr());
        Set<CommunityVar> toDelete = new HashSet<>();

        for (CommunityVar cvar : comms) {
          if (cvar.getType() == Type.REGEX) {
            List<CommunityVar> deps = _enc.getCommunityDependencies().get(cvar);
            if (deps != null) {
              toDelete.addAll(deps);
            }
          } else {
            toDelete.add(cvar);
          }
        }

        BitVecExpr x = configCommunities(
            curP, curResult, dc.getEnableSmtVariable(), null, // dc.getConfigLineEnable(),
            toDelete, dc.getConfigVarPrefix(), dc.getClass().getName());
        curP.getData().setCommunitiesBitVec(x);
        curResult = curResult.addChangedVariable("COMMUNITIES", x);

      } else if (stmt instanceof PrependAsPath) {
        // TODO: modify metric to aspathLength.
        curP.debug("PrependAsPath");
        PrependAsPath pap = (PrependAsPath) stmt;

        ArithExpr newValue = null;
        if (!pap.getEnableSmtVariable()) {
          int prependCost = prependLength(pap.getExpr());
          newValue = _enc.mkSum(curP.getData().getMetric(), _enc.mkInt(prependCost));
          newValue = _enc.mkIf(curResult.getReturnAssignedValue(), curP.getData().getMetric(), newValue);
          ArithExpr x = createArithVariableWith(curP, "METRIC", newValue);
          curP.getData().setMetric(x);
          curResult = curResult.addChangedVariable("METRIC", x);
        } else {
          ArithExpr prependCost = prependLengthVar(pap.getExpr());
          newValue = _enc.mkSum(curP.getData().getMetric(), prependCost);
          newValue = _enc.mkIf(curResult.getReturnAssignedValue(), curP.getData().getMetric(), newValue);
          ArithExpr x = createArithVariableWith(curP, "METRIC", newValue);
          curP.getData().setMetric(x);
          curResult = curResult.addChangedVariable("METRIC", x);
          // NOTE: symbolic encoding for the line enable
          // ArithExpr newX = createArithVariableWith(curP, "METRIC", newValue);
          // ArithExpr oldX = curP.getData().getMetric();
          // BoolExpr lineEnable = pap.getConfigLineEnable();
          // ArithExpr x = _enc.mkIf(lineEnable, newX, oldX);
          // curP.getData().setMetric(x);
          // curResult = curResult.addChangedVariable("METRIC", x);
        }


      } else if (stmt instanceof SetOrigin) {
        curP.debug("SetOrigin");
        curP.debug("Warning: use of unimplemented feature SetOrigin");

      } else if (stmt instanceof SetNextHop) {
        curP.debug("SetNextHop");
        curP.debug("Warning: use of unimplemented feature SetNextHop");

      } else if (stmt instanceof SetCommunities) {
        curP.debug("SetCommunities");
        curP.debug("Warning: use of unimplemented feature SetCommunities");

      } else {

        String s = (_isExport ? "export" : "import");
        String msg =
            String.format(
                "Unimplemented feature %s for %s transfer function on interface %s",
                stmt.toString(), s, _graphEdge.toString());

        throw new BatfishException(msg);
      }
    }

    // If this is the outermost call, then we relate the variables
    if (curP.getInitialCall()) {
      curP.debug("InitialCall finalizing");

      // Apply the default action
      if (!doesReturn) {
        curP.debug("Applying default action: " + curP.getDefaultAccept());
        if (curP.getDefaultAccept()) {
          curResult = returnValue(curP, curResult, true);
        } else {
          curResult = returnValue(curP, curResult, false);
        }
      }
      BoolExpr related = relateVariables(curP, curResult);
      BoolExpr retValue =
          _enc.mkIf(curResult.getReturnValue(), related, _enc.mkNot(_current.getPermitted()));
      curResult = curResult.setReturnValue(retValue);
    }
    return curResult;
  }

  /*
   * Check if we can inline a new SSA variable. We can simply conservatively check
   * if the size of the term will get no larger after inlining. Right now we only
   * check for True and False values because z3 seems to have some issue with
   * identifying the AST expression kind (e.g., e.isTrue() throws an exception).
   */
  private boolean canInline(Expr e) {
    // TODO: such a huge hack
    String s = e.toString();
    // p.debug("[STRING]: " + s);
    // p.debug("Can Inline: " + b);
    return s.length() <= INLINE_HEURISTIC;
  }

  /*
   * A collection of functions to create new SSA variables on-the-fly,
   * while also simultaneously setting their value based on an old value.
   */
  private ArithExpr createArithVariableWith(
      TransferParam<SymbolicRouteBV> p, String name, ArithExpr e) {
    ArithExpr eSimple = (ArithExpr) e.simplify();
    if (canInline(eSimple)) {
      p.debug(name + "=" + eSimple);
      return eSimple;
    }
    String s = "SSA_" + name + generateId();
    ArithExpr x = _enc.getCtx().mkIntConst(s);
    // _enc.getAllVariables().add(x);
    BoolExpr eq = _enc.mkEq(x, eSimple);
    _enc.add(eq);
    p.debug(eq.toString());
    return x;
  }

  private BoolExpr createBoolVariableWith(TransferParam<SymbolicRouteBV> p, String name, BoolExpr e) {
    BoolExpr simpleE = (BoolExpr) e.simplify();
    if (canInline(simpleE)) {
      p.debug(name + "=" + simpleE);
      return simpleE;
    }
    String s = "SSA_" + name + generateId();
    BoolExpr x = _enc.getCtx().mkBoolConst(s);
    // _enc.getAllVariables().add(x);
    BoolExpr eq = _enc.mkEq(x, simpleE);
    _enc.add(eq);
    p.debug(eq.toString());
    return x;
  }

  private BitVecExpr createBitVecVariableWith(
      TransferParam<SymbolicRouteBV> p, String name, int size, BitVecExpr e) {
    // BitVecExpr simpleE = (BitVecExpr) e.simplify();
    BitVecExpr simpleE = (BitVecExpr) e;
    if (canInline(simpleE)) {
      p.debug(name + "=" + simpleE);
      return simpleE;
    }
    String s = "SSA_" + name + generateId();
    BitVecExpr x = _enc.getCtx().mkBVConst(s, size);
    // _enc.getAllVariables().add(x);
    BoolExpr eq = _enc.mkEq(x, simpleE);
    _enc.add(eq);
    p.debug(eq.toString());
    return x;
  }

  /*
   * Create a new variable representing the new prefix length after
   * applying the effect of aggregation.
   */
  private void computeIntermediatePrefixLen(TransferParam<SymbolicRouteBV> param) {
    ArithExpr prefixLen = param.getData().getPrefixLength();
    if (_isExport && _proto.isBgp()) {
      _aggregates = aggregateRoutes();
      if (!_aggregates.isEmpty()) {
        for (Map.Entry<Prefix, Boolean> entry : _aggregates.entrySet()) {
          Prefix p = entry.getKey();
          Boolean isSuppressed = entry.getValue();
          // TODO: Configuration GeneratedRoute -> SMT symbolic variables
          ArithExpr len = _enc.mkInt(p.getPrefixLength());
          BoolExpr relevantPfx = _enc.isRelevantFor(p, _enc.getSymbolicPacket().getDstIp());
          BoolExpr relevantLen = _enc.mkGt(param.getData().getPrefixLength(), len);
          BoolExpr relevant = _enc.mkAnd(relevantPfx, relevantLen, _enc.mkBool(isSuppressed));
          prefixLen = _enc.mkIf(relevant, len, prefixLen);
        }
        ArithExpr i = createArithVariableWith(param, "PREFIX-LEN", prefixLen);
        param.getData().setPrefixLength(i);
      }
    }
  }

  private void applyMetricUpdate(TransferParam<SymbolicRouteBV> p) {
    boolean updateOspf = (!_isExport && _proto.isOspf());  // import && OSPF, update metric ?
    boolean updateBgp = (_isExport && _proto.isBgp());     // export && BGP, update metric ?
    boolean updateMetric = updateOspf || updateBgp;
    if (updateMetric) {
      // If it is a BGP route learned from IGP, then we use metric 0
      ArithExpr newValue;
      ArithExpr cost = _enc.mkInt(_addedCost);
      ArithExpr sum = _enc.mkSum(p.getData().getMetric(), cost);
      if (_proto.isBgp()) {
        BoolExpr isBGP;
        String router = _conf.getHostname();
        boolean hasProtocolVar = _other.getProtocolHistory() != null;
        boolean onlyBGP = _enc.getOptimizations().getSliceHasSingleProtocol().contains(router);
        if (hasProtocolVar) {
          isBGP = _other.getProtocolHistory().checkIfValue(Protocol.BGP);
        } else if (onlyBGP) {
          isBGP = _enc.mkTrue();
        } else {
          isBGP = _enc.mkFalse();
        }
        newValue = _enc.mkIf(isBGP, sum, cost);
      } else {  // _proto.isOspf()
        newValue = sum;
      }
      p.getData().setMetric(newValue);
    }
  }

  private void setDefaultLocalPref(TransferParam<SymbolicRouteBV> p, boolean isEbgp) {
    // must be the case that it is an environment variable
    if (p.getData().getLocalPref() == null) {
      p.getData().setLocalPref(_enc.mkInt(_enc.defaultLocalPref()));
    }
    if (isEbgp) {
      p.getData().setLocalPref(_enc.mkInt(_enc.defaultLocalPref()));
    }
  }

  private void setDefaultMed(TransferParam<SymbolicRouteBV> p, boolean isEbgp) {
    if (p.getData().getMed() == null) {
      p.getData().setMed(_enc.mkInt(_enc.defaultMed()));
    }
    if (isEbgp) {
      p.getData().setMed(_enc.mkInt(_enc.defaultMed()));
    }
  }

  public BoolExpr compute() {
    return compute(false);
  }

  public BoolExpr compute(boolean isEbgp) {
    SymbolicRouteBV o = new SymbolicRouteBV(_other);
    TransferParam<SymbolicRouteBV> p = new TransferParam<>(o, Encoder.ENABLE_DEBUGGING);

    // compute aggregate route with suppress aggregate
    computeIntermediatePrefixLen(p);

    // update metric
    //   + export & OSPF, originalMetric + addedCost
    //   + export & BGP, learned from BGP -> originalMetric + addedCost
    //                   learned from IGP -> 0 + addedCost
    applyMetricUpdate(p);

    // set default local prefence to 100
    setDefaultLocalPref(p, isEbgp);
    // set default med to 0
    setDefaultMed(p, isEbgp);

    TransferResult<BoolExpr, BoolExpr> result = compute(_statements, p, initialResult());
    return result.getReturnValue();
  }
}
