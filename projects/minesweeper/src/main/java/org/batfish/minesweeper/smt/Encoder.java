package org.batfish.minesweeper.smt;

import com.microsoft.z3.ArithExpr;
import com.microsoft.z3.BitVecExpr;
import com.microsoft.z3.BitVecNum;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Context;
import com.microsoft.z3.Expr;
import com.microsoft.z3.Model;
import com.microsoft.z3.Solver;
import com.microsoft.z3.Status;
import com.microsoft.z3.Tactic;
import com.google.common.collect.ImmutableMap;
import com.google.common.collect.ImmutableSet;
import com.google.common.graph.EndpointPair;

import java.io.*;
import java.math.BigInteger;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Objects;
import java.util.Set;
import java.util.SortedMap;
import java.util.SortedSet;
import java.util.TreeMap;
import java.util.TreeSet;
import javax.annotation.Nullable;
import org.batfish.common.BatfishException;
import org.batfish.datamodel.*;
import org.batfish.datamodel.ospf.OspfNeighborConfigId;
import org.batfish.minesweeper.CommunityVar;
import org.batfish.minesweeper.Graph;
import org.batfish.minesweeper.GraphEdge;
import org.batfish.minesweeper.OspfType;
import org.batfish.minesweeper.Protocol;
import org.batfish.minesweeper.question.HeaderQuestion;
import org.batfish.minesweeper.utils.MsPair;
import org.batfish.minesweeper.utils.Tuple;

import java.util.ArrayList;
import java.util.stream.Collectors;
import java.util.regex.Pattern;

import org.batfish.datamodel.routing_policy.RoutingPolicy;
import org.batfish.datamodel.routing_policy.expr.BooleanExpr;
import org.batfish.datamodel.routing_policy.expr.BooleanExprs;
import org.batfish.datamodel.routing_policy.expr.CallExpr;
import org.batfish.datamodel.routing_policy.expr.CommunitySetExpr;
import org.batfish.datamodel.routing_policy.expr.Conjunction;
import org.batfish.datamodel.routing_policy.expr.ConjunctionChain;
import org.batfish.datamodel.routing_policy.expr.Disjunction;
import org.batfish.datamodel.routing_policy.expr.ExplicitPrefixSet;
import org.batfish.datamodel.routing_policy.expr.FirstMatchChain;
import org.batfish.datamodel.routing_policy.expr.MatchAsPath;
import org.batfish.datamodel.routing_policy.expr.MatchCommunitySet;
import org.batfish.datamodel.routing_policy.expr.MatchIpv4;
import org.batfish.datamodel.routing_policy.expr.MatchIpv6;
import org.batfish.datamodel.routing_policy.expr.MatchPrefix6Set;
import org.batfish.datamodel.routing_policy.expr.MatchPrefixSet;
import org.batfish.datamodel.routing_policy.expr.MatchProtocol;
import org.batfish.datamodel.routing_policy.expr.NamedCommunitySet;
import org.batfish.datamodel.routing_policy.expr.NamedPrefixSet;
import org.batfish.datamodel.routing_policy.expr.Not;
import org.batfish.datamodel.routing_policy.expr.PrefixSetExpr;
import org.batfish.datamodel.routing_policy.expr.WithEnvironmentExpr;
import org.batfish.datamodel.routing_policy.expr.LiteralCommunity;
import org.batfish.datamodel.routing_policy.expr.LiteralCommunitySet;
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
// import org.batfish.datamodel.routing_policy.communities.CommunitySetExpr;
import org.batfish.datamodel.routing_policy.communities.SetCommunities;
import org.batfish.datamodel.routing_policy.communities.InputCommunities;
import org.batfish.datamodel.routing_policy.communities.CommunitySetReference;
import org.batfish.datamodel.routing_policy.communities.CommunitySetUnion;
import org.batfish.datamodel.routing_policy.communities.CommunitySetDifference;
// import org.batfish.datamodel.routing_policy.communities.LiteralCommunitySet;

import org.batfish.datamodel.bgp.community.Community;

import org.batfish.common.util.SymbolicUtil;




/**
 * Data class to store RouteFilterList rule information for Trie matching.
 */
class RouteFilterRuleInfo {
  private final int _lineIndex;
  private final LineAction _action;
  private final int _prefixLength;
  private final int _minLen;
  private final int _maxLen;
  private final String _configVarLinePrefix;

  public RouteFilterRuleInfo(
      int lineIndex, LineAction action, int prefixLength, int minLen, int maxLen,
      String configVarLinePrefix) {
    _lineIndex = lineIndex;
    _action = action;
    _prefixLength = prefixLength;
    _minLen = minLen;
    _maxLen = maxLen;
    _configVarLinePrefix = configVarLinePrefix;
  }

  public int getLineIndex() { return _lineIndex; }
  public LineAction getAction() { return _action; }
  public int getPrefixLength() { return _prefixLength; }
  public int getMinLen() { return _minLen; }
  public int getMaxLen() { return _maxLen; }
  public String getConfigVarLinePrefix() { return _configVarLinePrefix; }

  @Override
  public String toString() {
    String rangeStr = "";
    if (_minLen > _prefixLength) {
      rangeStr += " ge " + _minLen;
    }
    if (_maxLen < 32 || (_minLen == _prefixLength && _maxLen > _prefixLength)) {
      rangeStr += " le " + _maxLen;
    }
    return "seq " + _lineIndex + " " + _action.name().toLowerCase() + rangeStr;
  }
}

/**
 * A custom 01-Trie (Binary Prefix Trie) for matching IP prefixes against RouteFilterList rules.
 * Each node stores a list of RouteFilterRuleInfo that are defined at that prefix.
 * Matching collects all rules along the path and returns the one with smallest lineIndex
 * that satisfies the ge/le length constraints.
 */
class PrefixRuleTrie {
  private final TrieNode _root;

  public PrefixRuleTrie() {
    _root = new TrieNode();
  }

  /**
   * Internal trie node. Uses ArrayList for rules since we iterate through all rules
   * and order matters for collecting along the path.
   */
  private static class TrieNode {
    TrieNode[] children = new TrieNode[2]; // 0 = left, 1 = right
    ArrayList<RouteFilterRuleInfo> rules = new ArrayList<>();
  }

  /**
   * Insert a rule into the trie at the given prefix.
   * @param prefix The IP prefix (e.g., 10.0.0.0/8)
   * @param rule The rule info to store at this prefix
   */
  public void insert(Prefix prefix, RouteFilterRuleInfo rule) {
    TrieNode node = _root;
    long ip = prefix.getStartIp().asLong();
    int prefixLen = prefix.getPrefixLength();

    // Traverse/create nodes for each bit of the prefix (from MSB to LSB)
    for (int i = 31; i >= 32 - prefixLen; i--) {
      int bit = (int) ((ip >> i) & 1);
      if (node.children[bit] == null) {
        node.children[bit] = new TrieNode();
      }
      node = node.children[bit];
    }

    // Add rule at the terminal node for this prefix
    node.rules.add(rule);
  }

  /**
   * Match a query prefix against all rules in the trie.
   * Traverses from root to the query prefix, checking each node's rules
   * and keeping track of the best match (smallest lineIndex that satisfies ge/le).
   *
   * @param queryPrefix The prefix to match (e.g., 192.168.1.0/24)
   * @return The matching rule with smallest lineIndex, or null if no match
   */
  public RouteFilterRuleInfo match(Prefix queryPrefix) {
    RouteFilterRuleInfo bestMatch = null;
    TrieNode node = _root;
    long ip = queryPrefix.getStartIp().asLong();
    int queryLen = queryPrefix.getPrefixLength();

    // Check rules at root (if any rules are defined at 0.0.0.0/0)
    bestMatch = updateBestMatch(bestMatch, node.rules, queryLen);

    // Traverse the trie following the query prefix bits
    for (int i = 31; i >= 32 - queryLen; i--) {
      int bit = (int) ((ip >> i) & 1);
      if (node.children[bit] == null) {
        break; // No more specific prefix in trie
      }
      node = node.children[bit];
      // Check rules at this node and update best match
      bestMatch = updateBestMatch(bestMatch, node.rules, queryLen);
    }

    return bestMatch;
  }

  /**
   * Helper method to update best match from a list of rules.
   */
  private RouteFilterRuleInfo updateBestMatch(
      RouteFilterRuleInfo currentBest, ArrayList<RouteFilterRuleInfo> rules, int queryLen) {
    for (RouteFilterRuleInfo rule : rules) {
      // Check if query prefix length falls within [minLen, maxLen]
      if (queryLen >= rule.getMinLen() && queryLen <= rule.getMaxLen()) {
        if (currentBest == null || rule.getLineIndex() < currentBest.getLineIndex()) {
          currentBest = rule;
        }
      }
    }
    return currentBest;
  }

  /**
   * Match a query prefix and return the count of matching rules (for debugging).
   * @param queryPrefix The prefix to match
   * @return Number of rules that match (prefix is ancestor and ge/le satisfied)
   */
  public int matchCount(Prefix queryPrefix) {
    int count = 0;
    TrieNode node = _root;
    long ip = queryPrefix.getStartIp().asLong();
    int queryLen = queryPrefix.getPrefixLength();

    // Count matching rules at root
    count += countMatchingRules(node.rules, queryLen);

    // Traverse the trie
    for (int i = 31; i >= 32 - queryLen; i--) {
      int bit = (int) ((ip >> i) & 1);
      if (node.children[bit] == null) {
        break;
      }
      node = node.children[bit];
      count += countMatchingRules(node.rules, queryLen);
    }

    return count;
  }

  /**
   * Helper method to count matching rules.
   */
  private int countMatchingRules(ArrayList<RouteFilterRuleInfo> rules, int queryLen) {
    int count = 0;
    for (RouteFilterRuleInfo rule : rules) {
      if (queryLen >= rule.getMinLen() && queryLen <= rule.getMaxLen()) {
        count++;
      }
    }
    return count;
  }
}

/**
 * A class responsible for building a symbolic encoding of the entire network. The encoder does this
 * by maintaining a collection of encoding slices, where each slice encodes the forwarding behavior
 * for a particular packet.
 *
 * <p>The encoder object is architected this way to allow for modeling of features such as iBGP or
 * non-local next-hop ip addresses in static routes, where the forwarding behavior of one packet
 * depends on that of other packets.
 *
 * <p>Symbolic variables that are common to all slices are maintained in this class. That includes,
 * for example, the collection of variables representing topology failures.
 *
 * @author Ryan Beckett
 */
public class Encoder {
  // enable debugging
  static final Boolean ENABLE_DEBUGGING = false;
  static final String MAIN_SLICE_NAME = "SLICE-MAIN_";
  private static final boolean ENABLE_UNSAT_CORE = false;
  // Encoder object identifier, the default value is 0
  private int _encodingId;
  // the default value is true
  private boolean _modelIgp;

  private HeaderQuestion _question;
  private Map<String, EncoderSlice> _slices;
  private Map<String, Map<String, BoolExpr>> _sliceReachability;

  private Encoder _previousEncoder;
  // a collection of symbolic variables representing the possible link failures
  private SymbolicFailures _symbolicFailures;
  // a map of all smt variables, the relevant format is <Expr.toString(), Expr>
  private Map<String, Expr> _allVariables;

  private Graph _graph;

  private Context _ctx;

  private Solver _solver;

  private UnsatCore _unsatCore;

  // routing-policy sequence number and line number
  private Integer _seqNumber;
  private Integer _lineNumber;

  // support destination ports without peer (i.e. null peer)
  private Set<GraphEdge> _destPorts;

  // the output directory name and relevant print writer
  private String _outputDirectoryName;
  PrintWriter _smtWriter;
  PrintWriter _bgpPeersWriter;
  PrintWriter _ospfPeersWriter;
  PrintWriter _hostnamesWriter;
  PrintWriter _interfacesWriter;
  PrintWriter _dstIpsWriter;
  PrintWriter _modelIgpWriter;
  PrintWriter _historyEnumsWriter;
  PrintWriter _commIndexesWriter;
  PrintWriter _overallAttrsWriter;
  PrintWriter _cfwdIgnoresWriter;
  PrintWriter _propertyWriter;
  PrintWriter _propertyVarsWriter;
  PrintWriter _keyPrefixlistsWriter;
  PrintWriter _emptyCommunitiesWriter;

  private Map<String, Map<String, Set<String>>> _communityToConfigVars;
  private Set<String> _matchedCommunities;
  private Map<String, String> _formattedToMatchString;
  private List<String> _warnings;

  /**
   * Create an encoder object that will consider all packets in the provided headerspace.
   *
   * @param graph The network graph
   */
  Encoder(Graph graph, HeaderQuestion q) {
    this(null, graph, q, null, null, null, 0);
  }

  // NOTE: added by yongzheng2024
  // support destination ports without peer (i.e. null peer)
  Encoder(Graph graph, HeaderQuestion q, Set<GraphEdge> destPorts) {
    this(null, graph, q, null, null, null, 0, destPorts);
  }

  /**
   * Create an encoder object from an existing encoder.
   *
   * @param e An existing encoder object
   * @param g An existing network graph
   */
  Encoder(Encoder e, Graph g) {
    this(e, g, e._question, e.getCtx(), e.getSolver(), e.getAllVariables(), e.getId() + 1);
  }

  /**
   * Create an encoder object from an existing encoder.
   *
   * @param e An existing encoder object
   * @param g An existing network graph
   * @param q A header question
   */
  Encoder(Encoder e, Graph g, HeaderQuestion q) {
    this(e, g, q, e.getCtx(), e.getSolver(), e.getAllVariables(), e.getId() + 1);
  }

  // NOTE: added by yongzheng2024
  // support destination ports without peer (i.e. null peer)
  private Encoder(
      @Nullable Encoder enc,
      Graph graph,
      HeaderQuestion q,
      @Nullable Context ctx,
      @Nullable Solver solver,
      @Nullable Map<String, Expr> vars,
      int id,
      Set<GraphEdge> destPorts) {
    this(enc, graph, q, ctx, solver, vars, id);
    _destPorts = destPorts;
  }

  /**
   * Create an encoder object while possibly reusing the partial encoding of another encoder. If the
   * context and solver are null, then a new encoder is created. Otherwise the old encoder is used.
   */
  private Encoder(
      @Nullable Encoder enc,
      Graph graph,
      HeaderQuestion q,
      @Nullable Context ctx,
      @Nullable Solver solver,
      @Nullable Map<String, Expr> vars,
      int id) {
    _graph = graph;
    _previousEncoder = enc;
    _modelIgp = true;
    _encodingId = id;
    _question = q;
    _slices = new HashMap<>();
    _sliceReachability = new HashMap<>();
    _communityToConfigVars = new HashMap<>();
    _matchedCommunities = new HashSet<>();
    _formattedToMatchString = new HashMap<>();
    _warnings = new ArrayList<>();

    _seqNumber = 0;
    _lineNumber = 0;

    HashMap<String, String> cfg = new HashMap<>();

    // allows for unsat core when debugging
    if (ENABLE_UNSAT_CORE) {
      cfg.put("proof", "true");
      cfg.put("auto-config", "false");
    }

    _ctx = (ctx == null ? new Context(cfg) : ctx);

    if (solver == null) {
      if (ENABLE_UNSAT_CORE) {
        _solver = _ctx.mkSolver();
      } else {
        // The following string, such as "simplify", "propagate-values", "solve-eqs", ...
        // are hardcoded in Z3 and have a fixed meaning and fixed functionality.
        // The following code line that make a specific tactic pipeline.
        Tactic t1 = _ctx.mkTactic("simplify");
        Tactic t2 = _ctx.mkTactic("propagate-values");
        Tactic t3 = _ctx.mkTactic("solve-eqs");
        Tactic t4 = _ctx.mkTactic("bit-blast");
        Tactic t5 = _ctx.mkTactic("smt");
        Tactic t = _ctx.then(t1, t2, t3, t4, t5);
        _solver = _ctx.mkSolver(t);
      }
    } else {
      _solver = solver;
    }

    _symbolicFailures = new SymbolicFailures(_ctx);

    if (vars == null) {
      _allVariables = new HashMap<>();
    } else {
      _allVariables = vars;
    }

    if (ENABLE_DEBUGGING) {
      System.out.println(graph);
    }

    _unsatCore = new UnsatCore(ENABLE_UNSAT_CORE);

    // initialize output directory and relevant file print writer
    initOutput();

    // initialize hostnames and ebgp neighbors
    initNetworkTopology();

    long start = System.currentTimeMillis();
    // initialize configuration constant - SMT symbolic variable
    initConfigurationConstants();
    long end = System.currentTimeMillis();
    System.out.printf("SPECLENS_CONFIGURATION_ENCODING_MS=%d%n", end - start);

    // initialize _symbolicFailures and _allVariables, which involving
    //   + all GraphEdge getPeer() == null according to _edgeMap  (_failedEdgeLinks)
    //   + all neighbor node pair according to _neighbors         (_failedInternalLinks)
    initFailedLinkVariables();
    // initialize _symbolicFailures and _allVariables, which involving
    //   + all node according to _routers                         (_failedNodes)
    initFailedNodeVariables();

    // initialize _slices
    //   + one main slice (or only one null slice)
    //   + other slices according to domain (i.e. ibgp neighbors)
    // initialize _sliceReachability (call PropertyAdder instrumentReachability)
    initSlices(_question.getHeaderSpace(), graph);
  }

  /*
   * Initialize symbolic variables to represent link failures.
   */
  private void initFailedLinkVariables() {
    // initialize all isNullPeer GraphEdge, i.e. GraphEdge.getPeer() == null
    for (List<GraphEdge> edges : _graph.getEdgeMap().values()) {
      for (GraphEdge ge : edges) {
        if (ge.getPeer() == null) {
          Interface i = ge.getStart();
          String name = getId() + "_FAILED-EDGE_" + ge.getRouter() + "_" + i.getName();
          ArithExpr var = getCtx().mkIntConst(name);
          _symbolicFailures.getFailedEdgeLinks().put(ge, var);
          _allVariables.put(var.toString(), var);
        }
      }
    }

    // initialize all neighbor node pair, recorded in Graph Map<String, Set<String>> _neighbors
    for (Entry<String, Set<String>> entry : _graph.getNeighbors().entrySet()) {
      String router = entry.getKey();
      Set<String> peers = entry.getValue();
      for (String peer : peers) {
        // sort names for unique
        String pair = (router.compareTo(peer) < 0 ? router + "_" + peer : peer + "_" + router);
        String name = getId() + "_FAILED-EDGE_" + pair;
        ArithExpr var = _ctx.mkIntConst(name);
        _symbolicFailures.getFailedInternalLinks().put(router, peer, var);
        _allVariables.put(var.toString(), var);
      }
    }
  }

  /*
   * Initialize symbolic variables to represent node failures.
   */
  private void initFailedNodeVariables() {
    // initialize all node, recorded in Graph Set<String> _routers
    for (String router : _graph.getRouters()) {
      String name = getId() + "_FAILED-NODE_" + router;
      ArithExpr var = _ctx.mkIntConst(name);
      _symbolicFailures.getFailedNodes().put(router, var);
      _allVariables.put(var.toString(), var);
    }
  }

  /*
   * Initialize each encoding slice.
   * For iBGP, we also add reachability information for each pair of neighbors,
   * to determine if messages sent to/from a neighbor will arrive.
   */
  private void initSlices(HeaderSpace h, Graph g) {
    if (g.getIbgpNeighbors().isEmpty() || !_modelIgp) {
      _slices.put(MAIN_SLICE_NAME,
          new EncoderSlice(this, h, g, "", _cfwdIgnoresWriter, _historyEnumsWriter));
      // Write a flag indicating that we are NOT modeling IGP
      _modelIgpWriter.println("0");
    } else {
      _slices.put(MAIN_SLICE_NAME,
          new EncoderSlice(this, h, g, MAIN_SLICE_NAME, _cfwdIgnoresWriter, _historyEnumsWriter));
      // Write a flag indicating that we are modeling IGP
      _modelIgpWriter.println("1");
    }

    if (_modelIgp) {
      SortedSet<MsPair<String, Ip>> ibgpRouters = new TreeSet<>();

      for (Entry<GraphEdge, BgpActivePeerConfig> entry : g.getIbgpNeighbors().entrySet()) {
        GraphEdge ge = entry.getKey();
        BgpPeerConfig n = entry.getValue();

        String router = ge.getRouter();
        Ip ip = n.getLocalIp();
        MsPair<String, Ip> pair = new MsPair<>(router, ip);

        // Add one slice per (router, source ip) pair
        if (!ibgpRouters.contains(pair)) {

          ibgpRouters.add(pair);

          // Create a control plane slice only for this ip
          HeaderSpace hs = new HeaderSpace();

          // Make sure messages are sent to this destination IP
          SortedSet<IpWildcard> ips = new TreeSet<>();
          ips.add(IpWildcard.create(n.getLocalIp()));
          hs.setDstIps(ips);

          // Make sure messages use TCP port 179
          SortedSet<SubRange> dstPorts = new TreeSet<>();
          dstPorts.add(SubRange.singleton(179));
          hs.setDstPorts(dstPorts);

          // Make sure messages use the TCP protocol
          SortedSet<IpProtocol> protocols = new TreeSet<>();
          protocols.add(IpProtocol.TCP);
          hs.setIpProtocols(protocols);

          // TODO: create domains once
          Graph gNew = new Graph(g.getBatfish(), g.getSnapshot(), null, g.getDomain(router));
          String sliceName = "SLICE-" + router + "_";
          EncoderSlice slice =
              new EncoderSlice(this, hs, gNew, sliceName, _cfwdIgnoresWriter, _historyEnumsWriter);
          _slices.put(sliceName, slice);

          // TODO: annotated by yongzheng on 20250319
          PropertyAdder pa = new PropertyAdder(slice);
          Map<String, BoolExpr> reachVars = pa.instrumentReachability(router);
          _sliceReachability.put(router, reachVars);
        }
      }
    }
  }

  // Create a symbolic boolean
  BoolExpr mkBool(boolean val) {
    return getCtx().mkBool(val);
  }

  // Symbolic boolean negation
  BoolExpr mkNot(BoolExpr e) {
    return getCtx().mkNot(e);
  }

  // Symbolic boolean disjunction
  BoolExpr mkOr(BoolExpr... vals) {
    return getCtx().mkOr(Arrays.stream(vals).filter(Objects::nonNull).toArray(BoolExpr[]::new));
  }

  // Symbolic boolean implication
  BoolExpr mkImplies(BoolExpr e1, BoolExpr e2) {
    return getCtx().mkImplies(e1, e2);
  }

  // Symbolic boolean conjunction
  BoolExpr mkAnd(BoolExpr... vals) {
    return getCtx().mkAnd(Arrays.stream(vals).filter(Objects::nonNull).toArray(BoolExpr[]::new));
  }

  // Symbolic true value
  BoolExpr mkTrue() {
    return getCtx().mkBool(true);
  }

  // Symbolic false value
  BoolExpr mkFalse() {
    return getCtx().mkBool(false);
  }

  // Symbolic arithmetic less than
  BoolExpr mkLt(Expr e1, Expr e2) {
    if (e1 instanceof BoolExpr && e2 instanceof BoolExpr) {
      return mkAnd((BoolExpr) e2, mkNot((BoolExpr) e1));
    }
    if (e1 instanceof ArithExpr && e2 instanceof ArithExpr) {
      return getCtx().mkLt((ArithExpr) e1, (ArithExpr) e2);
    }
    if (e1 instanceof BitVecExpr && e2 instanceof BitVecExpr) {
      return getCtx().mkBVULT((BitVecExpr) e1, (BitVecExpr) e2);
    }
    throw new BatfishException("Invalid call to mkLt while encoding control plane");
  }

  // Symbolic greater than
  BoolExpr mkGt(Expr e1, Expr e2) {
    if (e1 instanceof BoolExpr && e2 instanceof BoolExpr) {
      return mkAnd((BoolExpr) e1, mkNot((BoolExpr) e2));
    }
    if (e1 instanceof ArithExpr && e2 instanceof ArithExpr) {
      return getCtx().mkGt((ArithExpr) e1, (ArithExpr) e2);
    }
    if (e1 instanceof BitVecExpr && e2 instanceof BitVecExpr) {
      return getCtx().mkBVUGT((BitVecExpr) e1, (BitVecExpr) e2);
    }
    throw new BatfishException("Invalid call the mkLe while encoding control plane");
  }

  // Symbolic arithmetic subtraction
  ArithExpr mkSub(ArithExpr e1, ArithExpr e2) {
    return getCtx().mkSub(e1, e2);
  }

  // Symbolic if-then-else for booleans
  BoolExpr mkIf(BoolExpr cond, BoolExpr case1, BoolExpr case2) {
    return (BoolExpr) getCtx().mkITE(cond, case1, case2);
  }

  // Symbolic if-then-else for arithmetic
  ArithExpr mkIf(BoolExpr cond, ArithExpr case1, ArithExpr case2) {
    return (ArithExpr) getCtx().mkITE(cond, case1, case2);
  }

  // Create a symbolic integer
  ArithExpr mkInt(long l) {
    return getCtx().mkInt(l);
  }

  // Symbolic arithmetic addition
  ArithExpr mkSum(ArithExpr e1, ArithExpr e2) {
    return getCtx().mkAdd(e1, e2);
  }

  // Symbolic greater than or equal to
  BoolExpr mkGe(Expr e1, Expr e2) {
    if (e1 instanceof ArithExpr && e2 instanceof ArithExpr) {
      return getCtx().mkGe((ArithExpr) e1, (ArithExpr) e2);
    }
    if (e1 instanceof BitVecExpr && e2 instanceof BitVecExpr) {
      return getCtx().mkBVUGE((BitVecExpr) e1, (BitVecExpr) e2);
    }
    throw new BatfishException("Invalid call to mkGe while encoding control plane");
  }

  // Symbolic less than or equal to
  BoolExpr mkLe(Expr e1, Expr e2) {
    if (e1 instanceof ArithExpr && e2 instanceof ArithExpr) {
      return getCtx().mkLe((ArithExpr) e1, (ArithExpr) e2);
    }
    if (e1 instanceof BitVecExpr && e2 instanceof BitVecExpr) {
      return getCtx().mkBVULE((BitVecExpr) e1, (BitVecExpr) e2);
    }
    throw new BatfishException("Invalid call to mkLe while encoding control plane");
  }

  // Symblic equality of expressions
  BoolExpr mkEq(Expr e1, Expr e2) {
    return getCtx().mkEq(e1, e2);
  }

  // Add a boolean variable to the model
  void add(BoolExpr e) {
    _unsatCore.track(_solver, _ctx, e);
  }

  /*
   * Adds the constraint that at most k links/nodes have failed.
   * This is done in two steps. First we ensure that each
   * variable that represents a failure is constrained to
   * take on a value between 0 and 1:
   *
   * 0 <= failVar_i <= 1
   *
   * Then we ensure that the sum of all fail variables is never more than k:
   *
   * failVar_1 + failVar_2 + ... + failVar_n <= k
   */
  private void addFailedConstraints(int k, Set<ArithExpr> vars) {
    ArithExpr sum = mkInt(0);
    for (ArithExpr var : vars) {
      sum = mkSum(sum, var);
      add(mkGe(var, mkInt(0)));
      add(mkLe(var, mkInt(1)));
    }
    if (k == 0) {
      for (ArithExpr var : vars) {
        add(mkEq(var, mkInt(0)));
      }
    } else {
      add(mkLe(sum, mkInt(k)));
    }
  }

  /* Generate constraints for link failures */
  private void addFailedLinkConstraints(int k) {
    Set<ArithExpr> vars = new HashSet<>();
    getSymbolicFailures().getFailedInternalLinks().forEach((router, peer, var) -> vars.add(var));
    getSymbolicFailures().getFailedEdgeLinks().forEach((ge, var) -> vars.add(var));
    addFailedConstraints(k, vars);
  }

  /* Generate constraints for node failures */
  private void addFailedNodeConstraints(int k) {
    Set<ArithExpr> vars = new HashSet<>();
    getSymbolicFailures().getFailedNodes().forEach((router, var) -> vars.add(var));
    addFailedConstraints(k, vars);
  }

  /*
   * Check if a community value should be displayed to the human
   */
  private boolean displayCommunity(CommunityVar cvar) {
    if (cvar.getType() == CommunityVar.Type.OTHER) {
      return false;
    }
    if (cvar.getType() == CommunityVar.Type.EXACT) {
      return true;
    }
    return true;
  }

  /*
   * Add the relevant variables in the counterexample to
   * display to the user in a human-readable fashion
   */
  private void buildCounterExample(
      Encoder enc,
      Model m,
      SortedMap<String, String> model,
      SortedMap<String, String> packetModel,
      SortedSet<String> fwdModel,
      SortedMap<String, SortedMap<String, String>> envModel,
      SortedSet<String> failures) {
    SortedMap<Expr, String> valuation = new TreeMap<>();

    // If user asks for the full model
    for (Entry<String, Expr> entry : _allVariables.entrySet()) {
      String name = entry.getKey();
      Expr e = entry.getValue();
      Expr val = m.evaluate(e, true);
      if (!val.equals(e)) {
        String s = val.toString();
        if (_question.getFullModel()) {
          model.put(name, s);
        }
        valuation.put(e, s);
      }
    }

    // Packet model
    SymbolicPacket p = enc.getMainSlice().getSymbolicPacket();
    String dstIp = valuation.get(p.getDstIp());
    String srcIp = valuation.get(p.getSrcIp());
    String dstPt = valuation.get(p.getDstPort());
    String srcPt = valuation.get(p.getSrcPort());
    String icmpCode = valuation.get(p.getIcmpCode());
    String icmpType = valuation.get(p.getIcmpType());
    String ipProtocol = valuation.get(p.getIpProtocol());
    String tcpAck = valuation.get(p.getTcpAck());
    String tcpCwr = valuation.get(p.getTcpCwr());
    String tcpEce = valuation.get(p.getTcpEce());
    String tcpFin = valuation.get(p.getTcpFin());
    String tcpPsh = valuation.get(p.getTcpPsh());
    String tcpRst = valuation.get(p.getTcpRst());
    String tcpSyn = valuation.get(p.getTcpSyn());
    String tcpUrg = valuation.get(p.getTcpUrg());

    Ip dip = Ip.create(Long.parseLong(dstIp));
    Ip sip = Ip.create(Long.parseLong(srcIp));

    packetModel.put("dstIp", dip.toString());

    if (sip.asLong() != 0) {
      packetModel.put("srcIp", sip.toString());
    }
    if (dstPt != null && !dstPt.equals("0")) {
      packetModel.put("dstPort", dstPt);
    }
    if (srcPt != null && !srcPt.equals("0")) {
      packetModel.put("srcPort", srcPt);
    }
    if (icmpCode != null && !icmpCode.equals("0")) {
      packetModel.put("icmpCode", icmpCode);
    }
    if (icmpType != null && !icmpType.equals("0")) {
      packetModel.put("icmpType", icmpType);
    }
    if (ipProtocol != null && !ipProtocol.equals("0")) {
      int number = Integer.parseInt(ipProtocol);
      IpProtocol proto = IpProtocol.fromNumber(number);
      packetModel.put("protocol", proto.toString());
    }
    if ("true".equals(tcpAck)) {
      packetModel.put("tcpAck", "set");
    }
    if ("true".equals(tcpCwr)) {
      packetModel.put("tcpCwr", "set");
    }
    if ("true".equals(tcpEce)) {
      packetModel.put("tcpEce", "set");
    }
    if ("true".equals(tcpFin)) {
      packetModel.put("tcpFin", "set");
    }
    if ("true".equals(tcpPsh)) {
      packetModel.put("tcpPsh", "set");
    }
    if ("true".equals(tcpRst)) {
      packetModel.put("tcpRst", "set");
    }
    if ("true".equals(tcpSyn)) {
      packetModel.put("tcpSyn", "set");
    }
    if ("true".equals(tcpUrg)) {
      packetModel.put("tcpUrg", "set");
    }

    for (EncoderSlice slice : enc.getSlices().values()) {
      for (Entry<LogicalEdge, SymbolicRouteBV> entry2 :
          slice.getLogicalGraph().getEnvironmentVars().entrySet()) {
        LogicalEdge lge = entry2.getKey();
        SymbolicRouteBV r = entry2.getValue();
        if ("true".equals(valuation.get(r.getPermitted()))) {
          SortedMap<String, String> recordMap = new TreeMap<>();
          GraphEdge ge = lge.getEdge();
          String nodeIface = ge.getRouter() + "," + ge.getStart().getName() + " (BGP)";
          envModel.put(nodeIface, recordMap);
          if (r.getPrefixLength() != null) {
            String x = valuation.get(r.getPrefixLength());
            if (x != null) {
              int len = Integer.parseInt(x);
              Prefix p1 = Prefix.create(dip, len);
              recordMap.put("prefix", p1.toString());
            }
          }
          if (r.getAdminDist() != null) {
            String x = valuation.get(r.getAdminDist());
            if (x != null) {
              recordMap.put("admin distance", x);
            }
          }
          if (r.getLocalPref() != null) {
            String x = valuation.get(r.getLocalPref());
            if (x != null) {
              recordMap.put("local preference", x);
            }
          }
          if (r.getMetric() != null) {
            String x = valuation.get(r.getMetric());
            if (x != null) {
              recordMap.put("protocol metric", x);
            }
          }
          if (r.getMed() != null) {
            String x = valuation.get(r.getMed());
            if (x != null) {
              recordMap.put("multi-exit disc.", valuation.get(r.getMed()));
            }
          }
          if (r.getOspfArea() != null && r.getOspfArea().getBitVec() != null) {
            String x = valuation.get(r.getOspfArea().getBitVec());
            if (x != null) {
              Integer i = Integer.parseInt(x);
              Long area = r.getOspfArea().value(i);
              recordMap.put("OSPF Area", area.toString());
            }
          }
          if (r.getOspfType() != null && r.getOspfType().getBitVec() != null) {
            String x = valuation.get(r.getOspfType().getBitVec());
            if (x != null) {
              int i = Integer.parseInt(x);
              OspfType type = r.getOspfType().value(i);
              recordMap.put("OSPF Type", type.toString());
            }
          }

          // for (Entry<CommunityVar, BoolExpr> entry3 : r.getCommunities().entrySet()) {
          //   CommunityVar cvar = entry3.getKey();
          //   BoolExpr e = entry3.getValue();
          //   String c = valuation.get(e);
          //   // TODO: what about OTHER type?
          //   if ("true".equals(c) && displayCommunity(cvar)) {
          //     String s = cvar.getRegex();
          //     String t = slice.getNamedCommunities().get(cvar.getRegex());
          //     s = (t == null ? s : t);
          //     recordMap.put("community " + s, "");
          //   }
          // }

          // NOTE: modified community encoding for counterexample (BoolExpr -> BitVecExpr communities)
          //       but only display exact community values in counterexample, regex community values
          //       are not displayed directly, via community dependencies indirectly
          BitVecExpr comms = r.getCommunitiesBitVec();
          if (null != comms) {
            Expr commsExpr = m.evaluate(comms, true);
            if (!(commsExpr instanceof BitVecNum)) {
              throw new BatfishException("Expected BitVecNum for communities, got: " + commsExpr);
            }
            ImmutableSet<CommunityVar> commsVars =
                SymbolicRouteBV.communitiesVars((BitVecNum) commsExpr, _graph.getAllCommunitiesIndex());
            for (CommunityVar cvar : commsVars) {
              if (displayCommunity(cvar)) {
                String s = cvar.getRegex();
                String t = slice.getNamedCommunities().get(cvar.getRegex());
                s = (t == null ? s : t);
                recordMap.put("community " + s, "");
              }
            }
          }
        }
      }
    }

    // Forwarding Model
    enc.getMainSlice()
        .getSymbolicDecisions()
        .getDataForwarding()
        .forEach(
            (router, edge, e) -> {
              String s = valuation.get(e);
              if ("true".equals(s)) {
                SymbolicRouteBV r =
                    enc.getMainSlice().getSymbolicDecisions().getBestNeighbor().get(router);
                if (r.getProtocolHistory() != null) {
                  Protocol proto;
                  List<Protocol> allProtocols = enc.getMainSlice().getProtocols().get(router);
                  if (allProtocols.size() == 1) {
                    proto = allProtocols.get(0);
                  } else {
                    s = valuation.get(r.getProtocolHistory().getBitVec());
                    int i = Integer.parseInt(s);
                    proto = r.getProtocolHistory().value(i);
                  }
                  fwdModel.add(edge + " (" + proto.name() + ")");
                } else {
                  fwdModel.add(edge.toString());
                }
              }
            });

    _symbolicFailures
        .getFailedInternalLinks()
        .forEach(
            (x, y, e) -> {
              String s = valuation.get(e);
              if ("1".equals(s)) {
                String pair = (x.compareTo(y) < 0 ? x + "," + y : y + "," + x);
                failures.add("link(" + pair + ")");
              }
            });

    _symbolicFailures
        .getFailedEdgeLinks()
        .forEach(
            (ge, e) -> {
              String s = valuation.get(e);
              if ("1".equals(s)) {
                failures.add("link(" + ge.getRouter() + "," + ge.getStart().getName() + ")");
              }
            });

    _symbolicFailures
        .getFailedNodes()
        .forEach(
            (x, e) -> {
              String s = valuation.get(e);
              if ("1".equals(s)) {
                failures.add("node(" + x + ")");
              }
            });
  }

  /*
   * Generate a blocking clause for the encoding that says that one
   * of the environments that was true before must now be false.
   */
  private BoolExpr environmentBlockingClause(Model m) {
    BoolExpr acc1 = mkFalse();
    BoolExpr acc2 = mkTrue();

    // Disable an environment edge if possible
    Map<LogicalEdge, SymbolicRouteBV> map = getMainSlice().getLogicalGraph().getEnvironmentVars();
    for (Map.Entry<LogicalEdge, SymbolicRouteBV> entry : map.entrySet()) {
      SymbolicRouteBV record = entry.getValue();
      BoolExpr per = record.getPermitted();
      Expr x = m.evaluate(per, false);
      if (x.toString().equals("true")) {
        acc1 = mkOr(acc1, mkNot(per));
      } else {
        acc2 = mkAnd(acc2, mkNot(per));
      }
    }

    // Disable a community value if possible
    // for (Map.Entry<LogicalEdge, SymbolicRoute> entry : map.entrySet()) {
    //   SymbolicRoute record = entry.getValue();
    //   for (Map.Entry<CommunityVar, BoolExpr> centry : record.getCommunities().entrySet()) {
    //     BoolExpr comm = centry.getValue();
    //     Expr x = m.evaluate(comm, false);
    //     if (x.toString().equals("true")) {
    //       acc1 = mkOr(acc1, mkNot(comm));
    //     } else {
    //       acc2 = mkAnd(acc2, mkNot(comm));
    //     }
    //   }
    // }

    // NOTE: modified disable community value if possible (BoolExpr -> BitVecExpr communities)
    ImmutableMap<CommunityVar, Integer> commsIndex = _graph.getAllCommunitiesIndex();
    for (Map.Entry<LogicalEdge, SymbolicRouteBV> entry : map.entrySet()) {
      SymbolicRouteBV record = entry.getValue();
      BitVecExpr comms = record.getCommunitiesBitVec();
      if (null == comms) {
        continue;
      }
      Expr commsExpr = m.evaluate(comms, false);
      if (!(commsExpr instanceof BitVecNum)) {
        throw new BatfishException("Expected BitVecNum for communities, got: " + commsExpr);
      }
      BigInteger bits = ((BitVecNum) commsExpr).getBigInteger();
      for (Map.Entry<CommunityVar, Integer> commIndex : commsIndex.entrySet()) {
        CommunityVar cvar = commIndex.getKey();
        int bitIndex = commIndex.getValue();
        BoolExpr commLit = SymbolicRouteBV.communityBitSet(_ctx, comms, commsIndex, cvar);
        if (bits.testBit(bitIndex)) {
          acc1 = mkOr(acc1, mkNot(commLit));
        } else {
          acc2 = mkAnd(acc2, mkNot(commLit));
        }
      }
    }

    return mkAnd(acc1, acc2);
  }

  /**
   * Checks that a property is always true by seeing if the encoding is unsatisfiable. If the model
   * is satisfiable, then there is a counter example to the property.
   *
   * @return A VerificationResult indicating the status of the check.
   */
  public Tuple<VerificationResult, Model> verify() {

    EncoderSlice mainSlice = _slices.get(MAIN_SLICE_NAME);

    // count the number of smt variable and constraint
    int numVariables = _allVariables.size();
    int numConstraints = _solver.getAssertions().length;
    // count the number of network node and edge according to main encoder slice
    int numNodes = mainSlice.getGraph().getConfigurations().size();
    int numEdges = 0;
    for (Map.Entry<String, Set<String>> e : mainSlice.getGraph().getNeighbors().entrySet()) {
      numEdges += e.getValue().size();
    }

    // simplify all assertions and record in simplifiedSolver
    Solver simplifiedSolver = _ctx.mkSolver();
    // TODO: assertion.simplify always replace "=>" with "or not", but "=>" is more suitable
    //       added by yongzheng2024 on 20250703
    for (BoolExpr assertion : _solver.getAssertions()) {
      // BoolExpr simplifiedAssertion = (BoolExpr) assertion.simplify();
      BoolExpr simplifiedAssertion = assertion;
      simplifiedSolver.add(simplifiedAssertion);
    }

    _smtWriter.println(simplifiedSolver.toString());
    _smtWriter.println("(check-sat)");
    _smtWriter.println(";(get-model)");
    _smtWriter.flush();
    _smtWriter.close();

    Status status = Status.UNSATISFIABLE;
    // Status status = _solver.check();

    VerificationStats stats = null;
    if (_question.getBenchmark()) {
      stats = new VerificationStats();
      stats.setAvgNumNodes(numNodes);
      stats.setMaxNumNodes(numNodes);
      stats.setMinNumNodes(numNodes);
      stats.setAvgNumEdges(numEdges);
      stats.setMaxNumEdges(numEdges);
      stats.setMinNumEdges(numEdges);
      stats.setAvgNumVariables(numVariables);
      stats.setMaxNumVariables(numVariables);
      stats.setMinNumVariables(numVariables);
      stats.setAvgNumConstraints(numConstraints);
      stats.setMaxNumConstraints(numConstraints);
      stats.setMinNumConstraints(numConstraints);
    }

    if (status == Status.UNSATISFIABLE) {
      VerificationResult res = new VerificationResult(true, null, null, null, null, null, stats);
      return new Tuple<>(res, null);
    } else if (status == Status.UNKNOWN) {
      throw new BatfishException("ERROR: satisfiability unknown");
    } else {
      VerificationResult result;

      Model m;
      while (true) {
        m = _solver.getModel();
        SortedMap<String, String> model = new TreeMap<>();
        SortedMap<String, String> packetModel = new TreeMap<>();
        SortedSet<String> fwdModel = new TreeSet<>();
        SortedMap<String, SortedMap<String, String>> envModel = new TreeMap<>();
        SortedSet<String> failures = new TreeSet<>();
        buildCounterExample(this, m, model, packetModel, fwdModel, envModel, failures);
        if (_previousEncoder != null) {
          buildCounterExample(
              _previousEncoder, m, model, packetModel, fwdModel, envModel, failures);
        }

        result =
            new VerificationResult(false, model, packetModel, envModel, fwdModel, failures, stats);

        if (!_question.getMinimize()) {
          break;
        }

        BoolExpr blocking = environmentBlockingClause(m);
        add(blocking);

        Status s = _solver.check();
        if (s == Status.UNSATISFIABLE) {
          break;
        }
        if (s == Status.UNKNOWN) {
          throw new BatfishException("ERROR: satisfiability unknown");
        }
      }

      return new Tuple<>(result, m);
    }
  }

  /**
   * Adds all the constraints to capture the interactions of messages among all protocols in the
   * network. This should be called prior to calling the <b>verify method</b>
   */
  void computeEncoding() {
    if (_graph.hasStaticRouteWithDynamicNextHop()) {
      throw new BatfishException(
          "Cannot encode a network that has a static route with a dynamic next hop");
    }


    SortedSet<String> overallBestAttrs = new TreeSet<>();

    addFailedLinkConstraints(_question.getFailures());
    addFailedNodeConstraints(_question.getNodeFailures());

    // addEnvironmentVariables
    getMainSlice().computeEncoding();
    overallBestAttrs.addAll(getMainSlice().getOverallBestAttrs());

    for (Entry<String, EncoderSlice> entry : _slices.entrySet()) {
      String name = entry.getKey();
      EncoderSlice slice = entry.getValue();
      if (!name.equals(MAIN_SLICE_NAME)) {
        slice.computeEncoding();
        overallBestAttrs.addAll(slice.getOverallBestAttrs());
      }
    }

    for (String attr : overallBestAttrs) {
      _overallAttrsWriter.println(attr);
    }

    // flush and close file print writer
    _overallAttrsWriter.flush();
    _overallAttrsWriter.close();
    _cfwdIgnoresWriter.flush();
    _cfwdIgnoresWriter.close();
    _historyEnumsWriter.flush();
    _historyEnumsWriter.close();
  }

  private void initOutput() {
    // _outputDirectoryName = createOutputDirectory();
    _outputDirectoryName = searchOutputDirectory();

    String outputSmtEncodingFileName        = _outputDirectoryName + "/smt_encoding.smt2";
    String outputBgpPeersFileName           = _outputDirectoryName + "/0_sim_bgp_peers.txt";
    String outputOspfPeersFileName          = _outputDirectoryName + "/0_sim_ospf_peers.txt";
    String outputHostnamesFileName          = _outputDirectoryName + "/0_all_hostnames.txt";
    String outputInterfacesFileName         = _outputDirectoryName + "/0_all_interfaces.txt";
    String outputDstIpsFileName             = _outputDirectoryName + "/0_all_dst_ips.txt";
    String outputModelIgpName               = _outputDirectoryName + "/0_all_model_igp.txt";
    String outputHistoryEnumsFileName       = _outputDirectoryName + "/0_smt_history_enums.txt";
    String outputCommunityIndexesFileName   = _outputDirectoryName + "/0_smt_community_indexes.txt";
    String outputOverallAttributesFileName  = _outputDirectoryName + "/0_smt_overall_attributes.txt";
    String outputControlFwdIgnoresFileName  = _outputDirectoryName + "/0_smt_controlfwd_ignores.txt";
    String outputPropertyFileName           = _outputDirectoryName + "/0_smt_property.txt";
    String outputPropertyVariablesFileName  = _outputDirectoryName + "/0_smt_property_variables.txt";
    String outputKeyPrefixListsFileName     = _outputDirectoryName + "/0_opt_key_prefixlists.txt";
    String outputEmptyCommunitiesFileName   = _outputDirectoryName + "/0_opt_empty_communities.txt";

    File outputSmtEncodingFile              = new File(outputSmtEncodingFileName);
    File outputBgpPeersFile                 = new File(outputBgpPeersFileName);
    File outputOspfPeersFile                = new File(outputOspfPeersFileName);
    File outputHostnamesFile                = new File(outputHostnamesFileName);
    File outputInterfacesFile               = new File(outputInterfacesFileName);
    File outputDstIpsFile                   = new File(outputDstIpsFileName);
    File outputModelIgpFile                 = new File(outputModelIgpName);
    File outputHistoryEnumsFile             = new File(outputHistoryEnumsFileName);
    File outputCommunityIndexesFile         = new File(outputCommunityIndexesFileName);
    File outputOverallAttributesFile        = new File(outputOverallAttributesFileName);
    File outputControlFwdIgnoresFile        = new File(outputControlFwdIgnoresFileName);
    File outputPropertyFile                 = new File(outputPropertyFileName);
    File outputPropertyVariablesFile        = new File(outputPropertyVariablesFileName);
    File outputKeyPrefixListsFile           = new File(outputKeyPrefixListsFileName);
    File outputEmptyCommunitiesFile         = new File(outputEmptyCommunitiesFileName);

    try {
      _smtWriter                            = new PrintWriter(new FileWriter(outputSmtEncodingFile, true), true);
      _bgpPeersWriter                       = new PrintWriter(new FileWriter(outputBgpPeersFile, true), true);
      _ospfPeersWriter                      = new PrintWriter(new FileWriter(outputOspfPeersFile, true), true);
      _hostnamesWriter = new PrintWriter(new FileWriter(outputHostnamesFile, true), true);
      _interfacesWriter = new PrintWriter(new FileWriter(outputInterfacesFile, true), true);
      _dstIpsWriter                         = new PrintWriter(new FileWriter(outputDstIpsFile, true), true);
      _modelIgpWriter                       = new PrintWriter(new FileWriter(outputModelIgpFile, true), true);
      _historyEnumsWriter                   = new PrintWriter(new FileWriter(outputHistoryEnumsFile, true), true);
      _commIndexesWriter                    = new PrintWriter(new FileWriter(outputCommunityIndexesFile, true), true);
      _overallAttrsWriter                   = new PrintWriter(new FileWriter(outputOverallAttributesFile, true), true);
      _cfwdIgnoresWriter                    = new PrintWriter(new FileWriter(outputControlFwdIgnoresFile, true), true);
      _propertyWriter                       = new PrintWriter(new FileWriter(outputPropertyFile, true), true);
      _propertyVarsWriter                   = new PrintWriter(new FileWriter(outputPropertyVariablesFile, true), true);
      _keyPrefixlistsWriter                 = new PrintWriter(new FileWriter(outputKeyPrefixListsFile, true), true);
      _emptyCommunitiesWriter               = new PrintWriter(new FileWriter(outputEmptyCommunitiesFile, true), true);

    } catch (IOException e) {
      System.err.println("Error: Unable to create file: " + e.getMessage());
    }
  }

  public static String searchOutputDirectory() {
    // SMT_DIRECTORY_PREFIX = "/PATH-TO/batfish/smts"
    final String DIRECTORY_PREFIX = System.getenv("SMT_DIRECTORY_PREFIX");
    final String DIRECTORY_NAME = DIRECTORY_PREFIX + "/smt_output_";
    final int DIRECTORY_INDEX_LIMIT = 9999;

    String outputDirectoryName = null;

    for (int i = 1; i <= DIRECTORY_INDEX_LIMIT; ++i) {
      // outputDirectoryName = "/PATH-TO/batfish/smts/smt_output_xxxx"
      // output directory range from 0001 to 9999
      String outputDirectoryNameNew = String.format("%s%04d", DIRECTORY_NAME, i);
      File outputDirectoryNew = new File(outputDirectoryNameNew);

      // FIXME: If there are three directory smt_output_0001, smt_output_0002, smt_output_0004,
      //        and we call createOutputDirectory(), it will return smt_output_0003,
      //        but then we call searchOutputDirectory(), it will return smt_output_0004.
      // if we find a non-existing output directory, return the previous one
      if (!outputDirectoryNew.exists()) {
        return outputDirectoryName;
      }

      outputDirectoryName = outputDirectoryNameNew;
    }

    /**
     * Search for the latest existing output directory.
     * Returns null if none exist.
     */
    return null;
  }

  public static String createOutputDirectory() {
    // SMT_DIRECTORY_PREFIX = "/PATH-TO/batfish/smts"
    final String DIRECTORY_PREFIX = System.getenv("SMT_DIRECTORY_PREFIX");
    final String DIRECTORY_NAME = DIRECTORY_PREFIX + "/smt_output_";
    final int DIRECTORY_INDEX_LIMIT = 9999;

    String outputDirectoryName = null;

    for (int i = 1; i <= DIRECTORY_INDEX_LIMIT; ++i) {
      // outputDirectoryName = "/PATH-TO/batfish/smts/smt_output_xxxx"
      // output directory range from 0001 to 9999
      outputDirectoryName = String.format("%s%04d", DIRECTORY_NAME, i);
      File outputDirectory = new File(outputDirectoryName);

      if (outputDirectory.exists()) {
        continue;
      }

      try {
        outputDirectory.mkdir();
      } catch (SecurityException e) {
        System.err.println("Error: Unable to create directory: " + e.getMessage());
      }

      break;
    }

    return outputDirectoryName;
  }

  /*
   * Getters and setters
   */

  Graph getGraph() {
    return _graph;
  }

  SymbolicFailures getSymbolicFailures() {
    return _symbolicFailures;
  }

  EncoderSlice getSlice(String router) {
    String s = "SLICE-" + router + "_";
    return _slices.get(s);
  }

  public Context getCtx() {
    return _ctx;
  }

  EncoderSlice getMainSlice() {
    return _slices.get(MAIN_SLICE_NAME);
  }

  Solver getSolver() {
    return _solver;
  }

  Map<String, Expr> getAllVariables() {
    return _allVariables;
  }

  int getId() {
    return _encodingId;
  }

  boolean getModelIgp() {
    return _modelIgp;
  }

  Map<String, Map<String, BoolExpr>> getSliceReachability() {
    return _sliceReachability;
  }

  UnsatCore getUnsatCore() {
    return _unsatCore;
  }

  int getFailures() {
    return _question.getFailures();
  }

  public boolean getFullModel() {
    return _question.getFullModel();
  }

  private Map<String, EncoderSlice> getSlices() {
    return _slices;
  }

  HeaderQuestion getQuestion() {
    return _question;
  }

  public String getDirectoryName() {
    return _outputDirectoryName;
  }

  public Set<GraphEdge> getDestPorts() {
    return _destPorts;
  }

  public void setQuestion(HeaderQuestion question) {
    _question = question;
  }

  public BitVecExpr mkBV(long val, int size) {
    return _ctx.mkBV(val, size);
  }

  public BitVecExpr mkBVAND(BitVecExpr expr, BitVecExpr mask) {
    return _ctx.mkBVAND(expr, mask);
  }

  public ArithExpr mkIntConst(String name) {
    return _ctx.mkIntConst(name);
  }

  public BitVecExpr mkBVConst(String name, int size) {
    return _ctx.mkBVConst(name, size);
  }

  private void initNetworkTopology() {
    // write all host names
    for (String hostname : _graph.getConfigurations().keySet()) {
      _hostnamesWriter.println(hostname);
    }
    _hostnamesWriter.flush();
    _hostnamesWriter.close();

    // write all interfaces
    for (GraphEdge edge : _graph.getAllEdges()) {
      _interfacesWriter.println(edge.getRouter() + "," + edge.getStart().getName());
    }
    _interfacesWriter.flush();
    _interfacesWriter.close();

    Map<String, SortedSet<String>> ospfPeers = getDefaultVrfOspfPeers();
    Map<String, SortedSet<String>> ebgpPeers = groupBgpPeers(_graph.getEbgpNeighbors());
    Map<String, SortedSet<String>> ibgpPeers = groupBgpPeers(_graph.getIbgpNeighbors());

    // Write default-VRF OSPF, eBGP, and iBGP peers in one device traversal.
    for (String hostname : _graph.getConfigurations().keySet()) {
      writePeers(_ospfPeersWriter, ospfPeers.get(hostname));
      writePeers(_bgpPeersWriter, ebgpPeers.get(hostname));
      writePeers(_bgpPeersWriter, ibgpPeers.get(hostname));
    }
    _ospfPeersWriter.flush();
    _ospfPeersWriter.close();
    _bgpPeersWriter.flush();
    _bgpPeersWriter.close();

    // write all communities and related indexes (exclude other community type now)
    ImmutableMap<CommunityVar, Integer> allCommsIndex = _graph.getAllCommunitiesIndex();
    _commIndexesWriter.println(allCommsIndex.size());
    for (Map.Entry<CommunityVar, Integer> entry : allCommsIndex.entrySet()) {
      CommunityVar comm = entry.getKey();
      int index = entry.getValue();
      if (CommunityVar.Type.EXACT == comm.getType()) {
        Community literal = comm.getLiteralValue();
        assert literal != null;
        _commIndexesWriter.println(literal.toString() + ": " + index);
      }
    }
    _commIndexesWriter.flush();
    _commIndexesWriter.close();

    // write all dst-ips
    SortedSet<IpWildcard> dstIps = _question.getDstIps();
    for (IpWildcard dstIp : dstIps) {
      _dstIpsWriter.println(dstIp);
    }
    _dstIpsWriter.flush();
    _dstIpsWriter.close();
  }

  private static void writePeers(PrintWriter writer, @Nullable Set<String> peers) {
    if (peers != null) {
      peers.forEach(writer::println);
    }
  }

  private Map<String, SortedSet<String>> getDefaultVrfOspfPeers() {
    return _graph
        .getBatfish()
        .getTopologyProvider()
        .getInitialOspfTopology(_graph.getSnapshot())
        .getGraph()
        .edges()
        .stream()
        .filter(
            edge ->
                Configuration.DEFAULT_VRF_NAME.equals(edge.source().getVrfName())
                    && Configuration.DEFAULT_VRF_NAME.equals(edge.target().getVrfName()))
        .collect(
            Collectors.groupingBy(
                edge -> edge.source().getHostname(),
                Collectors.mapping(Encoder::formatOspfPeer, Collectors.toCollection(TreeSet::new))));
  }

  private static String formatOspfPeer(EndpointPair<OspfNeighborConfigId> edge) {
    OspfNeighborConfigId local = edge.source();
    OspfNeighborConfigId remote = edge.target();
    return local.getHostname()
        + ","
        + local.getInterfaceName()
        + " -> "
        + remote.getHostname()
        + ","
        + remote.getInterfaceName();
  }

  private static Map<String, SortedSet<String>> groupBgpPeers(
      Map<GraphEdge, BgpActivePeerConfig> neighbors) {
    return neighbors.entrySet().stream()
        .filter(entry -> entry.getKey().getPeer() != null && entry.getKey().getEnd() != null)
        .collect(
            Collectors.groupingBy(
                entry -> entry.getKey().getRouter(),
                Collectors.mapping(Encoder::formatBgpPeer, Collectors.toCollection(TreeSet::new))));
  }

  private static String formatBgpPeer(Map.Entry<GraphEdge, BgpActivePeerConfig> entry) {
    GraphEdge edge = entry.getKey();
    BgpActivePeerConfig peerConfig = entry.getValue();
    return edge.getRouter()
        + ","
        + edge.getStart().getName()
        + " ("
        + peerConfig.getLocalAs()
        + ") -> "
        + edge.getPeer()
        + ","
        + edge.getEnd().getName()
        + " ("
        + peerConfig.getRemoteAsns()
        + ")";
  }

  private void routingPolicySeqNumber(@Nullable String comment) {
    if (comment != null) {
      String[] parts = comment.split("~", -1);
      if (parts.length > 1) {
        try {
          _seqNumber = Integer.parseInt(parts[parts.length - 2]);
          return;
        } catch (NumberFormatException e) {
          // Non-Cisco policies use descriptive term names instead of numeric sequence comments.
        }
      }
    }
    _seqNumber++;
  }

  private void incrementRoutingPolicyEntryLineNumber() {
    _lineNumber++;
  }

  private void cleanRoutingPolicyEntryLineNumber() {
    _lineNumber = 0;
  }

  static void initConfigurationConstantsComm(
      Encoder enc, CommunityVar cvar, String configVarPrefix) {
    Community community = cvar.getLiteralValue();
    BitVecExpr communityValue = null;
    Integer commIndex = enc.getGraph().getAllCommunitiesIndex().get(cvar);
    Integer commsWdith = enc.getGraph().getAllCommunitiesIndex().size();
    if (null != commIndex) {
      communityValue = enc.getCtx().mkBV(BigInteger.ONE.shiftLeft(commIndex).toString(), commsWdith);
    } else {
      throw new BatfishException("Encoder.initConfigurationConstantsComm: " +
          "community not found in commsIndex: " + community.getCommunityString());
    }
    community.initSmtVariable(
        enc.getCtx(), enc.getSolver(), configVarPrefix, true, communityValue, commsWdith);
  }

  private void initConfigurationConstants() {
    for (Map.Entry<String, Configuration> configEntry : _graph.getConfigurations().entrySet()) {
      String hostName = configEntry.getKey();
      Configuration config = configEntry.getValue();

      for (Map.Entry<String, RouteFilterList> routeFilterListEntry : config.getRouteFilterLists().entrySet()) {
        String routeFilterListName = routeFilterListEntry.getKey();
        RouteFilterList routeFilterList = routeFilterListEntry.getValue();

        // exclude other router filter list with configuration constants -> SMT symbolic variables
        // if (routerFilterListName.contains("default")) {
        //   continue;
        // }

        String configVarPrefix =
                "Config_" + hostName + "_RouteFilterList_" + SymbolicUtil.format(routeFilterListName) + "_";

        routeFilterList.initSmtVariable(_ctx, _solver, configVarPrefix);
      }

      if (!_graph.getAllCommunities().isEmpty()) {
        // if graph has no community, skip initialization of community symbolic configuration constants
        for (Map.Entry<String, CommunityList> communityListEntry : config.getCommunityLists().entrySet()) {
          String communityListName = communityListEntry.getKey();
          CommunityList communityList = communityListEntry.getValue();

          String configVarPrefix =
              "Config_" + hostName + "_CommunityList_" + SymbolicUtil.format(communityListName) + "_";
          // NOTE: Improve SMT variable names compatibility with line numbers
          // configVarPrefix += "_Line0__";

          communityList.initSmtVariable(
              _ctx, _solver, configVarPrefix,
              _graph.getAllExactCommunitiesIndex(), _graph.getAllCommunitiesIndex().size());
        }
      }

      for (Map.Entry<String, RoutingPolicy> routingPolicyEntry : config.getRoutingPolicies().entrySet()) {
        String policyName = routingPolicyEntry.getKey();
        RoutingPolicy routingPolicy = routingPolicyEntry.getValue();

        // exclude other routing policy with configuration constants -> SMT symbolic variables
        if (policyName.contains("default")) {
          continue;
        }

        List<Statement> statements = routingPolicy.getStatements();
        String configVarPrefix =
            "Config_" + hostName + "_RoutingPolicy_" + SymbolicUtil.format(policyName) + "_";
        // NOTE: Improve SMT variable names compatibility with line numbers
        // configVarPrefix += "_Line0__";
        initConfigurationConstants(statements, configVarPrefix);
      }

      // prefixes trie-tree optimization
      // TODO: implement prefixes trie-tree main function
      for (Map.Entry<String, RouteFilterList> routeFilterListEntry : config.getRouteFilterLists().entrySet()) {
        String routeFilterListName = routeFilterListEntry.getKey();
        RouteFilterList routeFilterList = routeFilterListEntry.getValue();

        // Build custom PrefixRuleTrie to store rule info
        PrefixRuleTrie trie = new PrefixRuleTrie();

        int lineIndex = 1;
        for (RouteFilterLine line : routeFilterList.getLines()) {
          Prefix linePrefix = line.getIpWildcard().toPrefix();
          int pLen = linePrefix.getPrefixLength();
          int minLen = line.getLengthRange().getStart();
          int maxLen = line.getLengthRange().getEnd();

          long prefixIp = line.getIpWildcard().getIp().asLong();
          String prefixIpStr = SymbolicUtil.longToIpString(prefixIp);
          String currConfigVarPrefix = "Config_" + hostName + "_RouteFilterList_" +
              SymbolicUtil.format(routeFilterListName) + "__Line" + lineIndex;

          // Add rule info to trie (with configVarPrefix)
          RouteFilterRuleInfo ruleInfo = new RouteFilterRuleInfo(
                  lineIndex, line.getAction(), pLen, minLen, maxLen, currConfigVarPrefix);
          trie.insert(linePrefix, ruleInfo);

          // add line index
          lineIndex++;
        }

        // Match Question's DstIps against this prefix list's trie
        if (_question != null && _question.getHeaderSpace() != null) {
          IpSpace dstIpSpace = _question.getHeaderSpace().getDstIps();
          if (dstIpSpace instanceof IpWildcardSetIpSpace) {
            IpWildcardSetIpSpace wildcardSet = (IpWildcardSetIpSpace) dstIpSpace;
            // Match whitelist IPs
            for (IpWildcard ipw : wildcardSet.getWhitelist()) {
              Prefix queryPrefix = ipw.toPrefix();
              RouteFilterRuleInfo bestMatch = trie.match(queryPrefix);
              if (bestMatch != null) {
                _keyPrefixlistsWriter.println(bestMatch.getConfigVarLinePrefix());
              }
            }
            // Match blacklist IPs
            for (IpWildcard ipw : wildcardSet.getBlacklist()) {
              Prefix queryPrefix = ipw.toPrefix();
              RouteFilterRuleInfo bestMatch = trie.match(queryPrefix);
              if (bestMatch != null) {
                _keyPrefixlistsWriter.println(bestMatch.getConfigVarLinePrefix());
              }
            }
          }
        }
      }
    }

    // static analysis community optimization
    // TODO: implement static analysis community main function
    printUnmatchedCommunities();
  }

  private void initConfigurationConstants(
      List<Statement> statements, String configVarPrefix) {
    for (Statement stmt : statements) {
      if (stmt instanceof StaticStatement) {
        // TODO: check here and implement it when needed
        StaticStatement ss = (StaticStatement) stmt;
        switch (ss.getType()) {
          case ExitAccept:
            break;
          case Unsuppress:
          case ReturnTrue:
            break;
          case ExitReject:
            break;
          case Suppress:
          case ReturnFalse:
            break;
          case SetDefaultActionAccept:
            break;
          case SetDefaultActionReject:
            break;
          case SetLocalDefaultActionAccept:
            break;
          case SetLocalDefaultActionReject:
            break;
          case ReturnLocalDefaultAction:
            break;
          case FallThrough:
            break;
          case Return:
            break;
          case RemovePrivateAs:
            break;
          default:
            String msg = String.format("Unimplemented feature %s", ss.getType());
            throw new BatfishException(msg);
        }

      } else if (stmt instanceof If) {
        // IF
        //   guard
        // THEN
        //   trueStatements
        // ELSE
        //   falseStatement
        If i = (If) stmt;
        routingPolicySeqNumber(i.getComment());
        initConfigurationConstants(i.getGuard(), configVarPrefix);
        initConfigurationConstants(i.getTrueStatements(), configVarPrefix);
        initConfigurationConstants(i.getFalseStatements(), configVarPrefix);

      } else if (stmt instanceof SetDefaultPolicy) {
        // TODO: implement me
        {}  // do nothing

      } else if (stmt instanceof SetMetric) {
        SetMetric sm = (SetMetric) stmt;
        String metricValue = sm.getMetric().getLiteralLongString();
        incrementRoutingPolicyEntryLineNumber();
        String configVarPrefixUpdated =
            SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
        sm.initSmtVariable(_ctx, _solver, configVarPrefixUpdated + "set_metric_" + metricValue);

      } else if (stmt instanceof SetOspfMetricType) {
        // TODO: implement me
        {}  // do nothing

      } else if (stmt instanceof SetLocalPreference) {
        SetLocalPreference slp = (SetLocalPreference) stmt;
        String localPreferenceValue = slp.getLocalPreference().getLiteralLongString();
        incrementRoutingPolicyEntryLineNumber();
        String configVarPrefixUpdated =
            SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
        slp.initSmtVariable(_ctx, _solver,
            configVarPrefixUpdated + "set_localpreference_" + localPreferenceValue);

      } else if (stmt instanceof AddCommunity) {
        AddCommunity ac = (AddCommunity) stmt;
        if (ac.getEnableSmtVariable()) {
          ac = new AddCommunity(ac.getExpr());
        }
        // symbolic configuration
        CommunitySetExpr communitySetExpr = ac.getExpr();
        incrementRoutingPolicyEntryLineNumber();
        String configVarPrefixUpdated =
            SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
        ac.initSmtVariable(
            _ctx, _solver, configVarPrefixUpdated + "add_community_", true,
            _graph.getAllExactCommunitiesIndex(), _graph.getAllCommunitiesIndex().size());

        // support static analysis for more exact community subspecs
        if (communitySetExpr instanceof LiteralCommunitySet) {
          LiteralCommunitySet lcs = (LiteralCommunitySet) communitySetExpr;
          Set<Community> communities = lcs.getCommunities();
          for (Community community : communities) {
            String communityString = SymbolicUtil.format(community.getCommunityString());
            String matchString = community.matchString();
            String configVarName = configVarPrefix + "add_community_" + communityString + "_community";
            _formattedToMatchString.put(communityString, matchString);
            _communityToConfigVars
                    .computeIfAbsent(communityString, k -> new HashMap<>())
                    .computeIfAbsent("ADD", k -> new HashSet<>())
                    .add(configVarName);
          }
        } else if (communitySetExpr instanceof LiteralCommunity) {
          LiteralCommunity lc = (LiteralCommunity) communitySetExpr;
          String communityString = SymbolicUtil.format(lc.getCommunity().getCommunityString());
          String matchString = lc.getCommunity().matchString();
          String configVarName = configVarPrefix + "add_community_" + communityString + "_community";
          _formattedToMatchString.put(communityString, matchString);
          _communityToConfigVars
              .computeIfAbsent(communityString, k -> new HashMap<>())
              .computeIfAbsent("ADD", k -> new HashSet<>())
              .add(configVarName);
        } else if (communitySetExpr instanceof NamedCommunitySet) {
          continue;
        } else {
          throw new BatfishException("Unimplemented feature " + communitySetExpr.getClass());
        }

      } else if (stmt instanceof SetCommunity) {
        SetCommunity sc = (SetCommunity) stmt;
        if (sc.getEnableSmtVariable()) {
          sc = new SetCommunity(sc.getExpr());
        }
        // symbolic configuration
        CommunitySetExpr communitySetExpr = sc.getExpr();
        incrementRoutingPolicyEntryLineNumber();
        String configVarPrefixUpdated =
            SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
        sc.initSmtVariable(
            _ctx, _solver, configVarPrefixUpdated + "set_community_", true,
            _graph.getAllExactCommunitiesIndex(), _graph.getAllCommunitiesIndex().size());
        // support static analysis for more exact community subspecs
        if (communitySetExpr instanceof LiteralCommunitySet) {
          LiteralCommunitySet lcs = (LiteralCommunitySet) communitySetExpr;
          Set<Community> communities = lcs.getCommunities();
          for (Community community : communities) {
            String communityString = SymbolicUtil.format(community.getCommunityString());
            String matchString = community.matchString();
            String configVarName = configVarPrefixUpdated + "set_community_" + communityString + "_community";
            _formattedToMatchString.put(communityString, matchString);
            _communityToConfigVars
                    .computeIfAbsent(communityString, k -> new HashMap<>())
                    .computeIfAbsent("SET", k -> new HashSet<>())
                    .add(configVarName);
          }
        } else if (communitySetExpr instanceof LiteralCommunity) {
          LiteralCommunity lc = (LiteralCommunity) communitySetExpr;
          String communityString = SymbolicUtil.format(lc.getCommunity().getCommunityString());
          incrementRoutingPolicyEntryLineNumber();
          String matchString = lc.getCommunity().matchString();
          String configVarName = configVarPrefixUpdated + "set_community_" + communityString + "_community";
          _formattedToMatchString.put(communityString, matchString);
          _communityToConfigVars
              .computeIfAbsent(communityString, k -> new HashMap<>())
              .computeIfAbsent("SET", k -> new HashSet<>())
              .add(configVarName);
        } else if (communitySetExpr instanceof NamedCommunitySet) {
          continue;
        } else {
          throw new BatfishException("Unimplemented feature " + communitySetExpr.getClass());
        }

      } else if (stmt instanceof DeleteCommunity) {
        DeleteCommunity dc = (DeleteCommunity) stmt;
        if (dc.getEnableSmtVariable()) {
          dc = new DeleteCommunity(dc.getExpr());
        }
        // symbolic configuration
        incrementRoutingPolicyEntryLineNumber();
        String configVarPrefixUpdated =
            SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
        dc.initSmtVariable(
            _ctx, _solver, configVarPrefixUpdated + "delete_community_", false,
            _graph.getAllExactCommunitiesIndex(), _graph.getAllCommunitiesIndex().size());

      } else if (stmt instanceof PrependAsPath) {
        PrependAsPath pap = (PrependAsPath) stmt;
        incrementRoutingPolicyEntryLineNumber();
        String configVarPrefixUpdated =
            SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
        pap.initSmtVariable(_ctx, _solver, configVarPrefixUpdated + "prepend_aspath_");

      } else if (stmt instanceof SetOrigin) {
        // TODO: implement me
        {}  // do nothing

      } else if (stmt instanceof SetNextHop) {
        // TODO: implement me
        {}  // do nothing

      } else if (stmt instanceof SetCommunities) {
        SetCommunities scs = (SetCommunities) stmt;
        org.batfish.datamodel.routing_policy.communities.CommunitySetExpr communitySetExpr =
            scs.getExpr();
        incrementRoutingPolicyEntryLineNumber();
        String configVarPrefixUpdated =
            SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
        if (communitySetExpr instanceof InputCommunities) {
          // TODO: implement me
          {}  // do nothing
        } else if (communitySetExpr instanceof CommunitySetReference) {
          // TODO: implement me
          {}  // do nothing
        } else if (communitySetExpr instanceof CommunitySetUnion) {
          // TODO: implement me
          {}  // do nothing
        } else if (communitySetExpr instanceof CommunitySetDifference) {
          // TODO: implement me
          {}  // do nothing
        } else if (communitySetExpr instanceof
            org.batfish.datamodel.routing_policy.communities.LiteralCommunitySet) {
          // TODO: implement me
          {}  // do nothing
        } else {
          String msg = String.format("Unimplemented feature %s", communitySetExpr.getClass());
          throw new BatfishException(msg);
        }

      } else {
        String msg = String.format("Unimplemented feature %s", stmt.toString());
        throw new BatfishException(msg);
      }
    }

    cleanRoutingPolicyEntryLineNumber();
  }

  private void initConfigurationConstants(
      BooleanExpr expr, String configVarPrefix) {
    if (expr instanceof MatchIpv4) {
      // TODO: implement me
      {}  // do nothing
    }

    if (expr instanceof MatchIpv6) {
      // TODO: implement me
      {}  // do nothing
    }

    if (expr instanceof Conjunction) {
      Conjunction c = (Conjunction) expr;
      for (BooleanExpr booleanExpr : c.getConjuncts()) {
        initConfigurationConstants(booleanExpr, configVarPrefix);
      }
    }

    if (expr instanceof Disjunction) {
      Disjunction d = (Disjunction) expr;
      for (BooleanExpr booleanExpr : d.getDisjuncts()) {
        initConfigurationConstants(booleanExpr, configVarPrefix);
      }
    }

    if (expr instanceof ConjunctionChain) {
      // TODO: check here
      ConjunctionChain d = (ConjunctionChain) expr;
      List<BooleanExpr> conjuncts = new ArrayList<>(d.getSubroutines());
      for (BooleanExpr booleanExpr : conjuncts) {
        initConfigurationConstants(booleanExpr, configVarPrefix);
      }
    }

    if (expr instanceof FirstMatchChain) {
      // TODO: check here
      FirstMatchChain chain = (FirstMatchChain) expr;
      List<BooleanExpr> chainPolicies = new ArrayList<>(chain.getSubroutines());
      for (BooleanExpr booleanExpr : chainPolicies) {
        initConfigurationConstants(booleanExpr, configVarPrefix);
      }
    }

    if (expr instanceof Not) {
      // TODO: check here
      Not n = (Not) expr;
      initConfigurationConstants(n.getExpr(), configVarPrefix);
    }

    if (expr instanceof MatchProtocol) {
      // FIXME: check here and implement it when needed
      MatchProtocol mp = (MatchProtocol) expr;
      Set<RoutingProtocol> rps = mp.getProtocols();
      if (rps.size() > 1) {
        // Hack: Minesweeper doesn't support MatchProtocol with multiple arguments.
        List<BooleanExpr> mps = rps.stream().map(MatchProtocol::new).collect(Collectors.toList());
        for (BooleanExpr booleanExpr : mps) {
          initConfigurationConstants(booleanExpr, configVarPrefix);
        }
      }
    }

    if (expr instanceof MatchPrefixSet) {
      // TODO: check here and implement it when needed
      MatchPrefixSet mps = (MatchPrefixSet) expr;
      // temporary fix: clone a new MatchPrefixSet without SMT variable enable flag
      if (mps.getEnableSmtVariable()) {
        mps = new MatchPrefixSet(mps.getPrefix(), mps.getPrefixSet());
      }
      incrementRoutingPolicyEntryLineNumber();
      configVarPrefix = SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
      mps.initSmtVariable(_ctx, _solver, configVarPrefix + "match_prefixlist_");

      // write smt symbolic variables name to configs_to_variables file
      PrefixSetExpr prefixSetExpr = mps.getPrefixSet();
      if (prefixSetExpr instanceof ExplicitPrefixSet) {
        {}  // do nothing, call ip prefix-list / access-list in configuration
      } else if (prefixSetExpr instanceof NamedPrefixSet) {
        {}  // do nothing, call ip prefix-list / access-list in configuration
      } else {
        throw new BatfishException("Unimplemented feature " + expr.getClass());
      }

    } else if (expr instanceof MatchPrefix6Set) {
      // TODO: implement me
      {}  // do nothing

    } else if (expr instanceof CallExpr) {
      // TODO: check here and implement it when needed
      CallExpr ce = (CallExpr) expr;

    } else if (expr instanceof WithEnvironmentExpr) {
      WithEnvironmentExpr we = (WithEnvironmentExpr) expr;
      initConfigurationConstants(we.getExpr(), configVarPrefix);

    } else if (expr instanceof MatchCommunitySet) {
      // TODO: check here and implement it when needed
      MatchCommunitySet mcs = (MatchCommunitySet) expr;
      // mcs.initSmtVariable(_ctx, _solver, configVarPrefix);

      // support static analysis for more exact community subspecs
      String hostName = extractHostNameFromConfigVarPrefix(configVarPrefix);
      Configuration currentConfig = hostName != null ? _graph.getConfigurations().get(hostName) : null;

      CommunitySetExpr communitySetExpr = mcs.getExpr();
      if (communitySetExpr instanceof NamedCommunitySet) {
        // support static analysis for more exact community subspecs
        collectCommunitiesFromNamedCommunitySet(((NamedCommunitySet) communitySetExpr).getName(), currentConfig);
      } else if (communitySetExpr instanceof RegexCommunitySet) {
        // support static analysis for more exact community subspecs
        collectCommunitiesFromRegexCommunitySet((RegexCommunitySet) communitySetExpr);
      } else if (communitySetExpr instanceof LiteralCommunity) {
        // support static analysis for more exact community subspecs
        collectCommunitiesFromLiteralCommunity((LiteralCommunity) communitySetExpr);
      } else if (communitySetExpr instanceof LiteralCommunitySet) {
        // support static analysis for more exact community subspecs
        collectCommunitiesFromLiteralCommunitySet((LiteralCommunitySet) communitySetExpr);
      } else if (communitySetExpr instanceof CommunityList) {
        // support static analysis for more exact community subspecs
        collectCommunitiesFromCommunityList((CommunityList) communitySetExpr, currentConfig);
      } else {
        // Unimplemented subclasses of CommunitySetExpr:
        // * LiteralCommunityConjunction
        // * UnsupportedCommunitySetExpr in CommunityListTest
        // * CommunityHalvesExpr
        // * EmptyCommunitySetExpr
        // mcs.initSmtVariable(_ctx, _solver, configVarPrefix + "unimplemented_community_");
        throw new BatfishException("Unimplemented feature: " + expr.getClass().getName());
      }

      incrementRoutingPolicyEntryLineNumber();
      configVarPrefix = SymbolicUtil.configLineSuffix(configVarPrefix, _seqNumber, _lineNumber);
      mcs.initSmtVariable(
          _ctx, _solver, configVarPrefix + "match_community_list_",
          _graph.getAllExactCommunitiesIndex(), _graph.getAllCommunitiesIndex().size());

    } else if (expr instanceof BooleanExprs.StaticBooleanExpr) {
      BooleanExprs.StaticBooleanExpr b = (BooleanExprs.StaticBooleanExpr) expr;
      switch (b.getType()) {
        case CallExprContext:
          break;
        case CallStatementContext:
          break;
        case True:
          break;
        case False:
          break;
        default:
          // FIXME: check here and implement it when needed
          // String msg = String.format(
          //     "Unimplemented feature %s : %s", BooleanExprs.class.getCanonicalName(), b.getType());
          // throw new BatfishException(msg);
          break;
      }

    } else if (expr instanceof MatchAsPath) {
      // TODO: implement me
      {}  // do nothing
    }

    // FIXME: check here and implement it when needed
    // String msg = String.format("Unimplemented feature %s", expr.toString());
    // throw new BatfishException(msg);
  }

  private void collectCommunitiesFromNamedCommunitySet(String name, Configuration currentConfig) {
    collectCommunitiesFromNamedCommunitySet(name, currentConfig, new HashSet<>());
  }
  
  private void collectCommunitiesFromNamedCommunitySet(String name, Configuration currentConfig, Set<String> visited) {
    if (visited.contains(name)) return;
    visited.add(name);
  
    if (currentConfig != null) {
      CommunityList cl = currentConfig.getCommunityLists().get(name);
      if (cl != null) {
        collectCommunitiesFromCommunityList(cl, currentConfig, visited);
        return;
      }
    }
  
    if (currentConfig != null) {
      _warnings.add("CommunityList '" + name + "' not found in configuration '" +
              currentConfig.getHostname() + "'");
    } else {
      _warnings.add("CommunityList '" + name + "' not found (currentConfig is null)");
    }
  }

  /** Collect communities from a literal community set into _matchedCommunities (static analysis). */
  private void collectCommunitiesFromLiteralCommunitySet(LiteralCommunitySet lcs) {
    for (Community community : lcs.getCommunities()) {
      _matchedCommunities.add(SymbolicUtil.format(community.getCommunityString()));
    }
  }

  /** Collect the single community from a literal community into _matchedCommunities (static analysis). */
  private void collectCommunitiesFromLiteralCommunity(LiteralCommunity lc) {
    _matchedCommunities.add(SymbolicUtil.format(lc.getCommunity().getCommunityString()));
  }
  
  private void collectCommunitiesFromCommunityList(CommunityList cl, Configuration currentConfig) {
    collectCommunitiesFromCommunityList(cl, currentConfig, new HashSet<>());
  }

  private void collectCommunitiesFromCommunityList(CommunityList cl, Configuration currentConfig, Set<String> visited) {
    for (CommunityListLine line : cl.getLines()) {
      CommunitySetExpr expr = line.getMatchCondition();
      if (expr instanceof LiteralCommunitySet) {
        collectCommunitiesFromLiteralCommunitySet((LiteralCommunitySet) expr);
      } else if (expr instanceof LiteralCommunity) {
        collectCommunitiesFromLiteralCommunity((LiteralCommunity) expr);
      } else if (expr instanceof NamedCommunitySet) {
        collectCommunitiesFromNamedCommunitySet(((NamedCommunitySet) expr).getName(), currentConfig, visited);
      } else if (expr instanceof CommunityList) {
        collectCommunitiesFromCommunityList((CommunityList) expr, currentConfig, visited);
      } else if (expr instanceof RegexCommunitySet) {
        collectCommunitiesFromRegexCommunitySet((RegexCommunitySet) expr);
      }
    }
  }

  private void collectCommunitiesFromRegexCommunitySet(RegexCommunitySet rcs) {
    Pattern pattern = Pattern.compile(rcs.getRegex());
    for (String formattedCommunity : _communityToConfigVars.keySet()) {
      String matchString = _formattedToMatchString.get(formattedCommunity);
      if (matchString != null && pattern.matcher(matchString).find()) {
        _matchedCommunities.add(formattedCommunity);
      }
    }
  }

  /**
   * Extracts hostname from a config variable prefix (e.g. "Config_my_router_RoutingPolicy_...").
   * Uses known section tokens so hostnames containing underscores are parsed correctly.
   */
  private String extractHostNameFromConfigVarPrefix(String configVarPrefix) {
    if (configVarPrefix == null || !configVarPrefix.startsWith("Config_")) {
      return null;
    }
    int start = "Config_".length();
    // Prefix is built as Config_<hostname>_RouteFilterList_... or _CommunityList_... or _RoutingPolicy_...
    int end = -1;
    for (String token : new String[]{"_RouteFilterList_", "_CommunityList_", "_RoutingPolicy_"}) {
      int idx = configVarPrefix.indexOf(token, start);
      if (idx > 0) {
        end = idx;
        break;
      }
    }
    if (end == -1) {
      end = configVarPrefix.indexOf("_", start);
    }
    if (end == -1) {
      return null;
    }
    return configVarPrefix.substring(start, end);
  }

  private void printUnmatchedCommunities() {
    if (_communityToConfigVars == null) {
      _emptyCommunitiesWriter.close();
      return;
    }
    Set<String> unmatched = new TreeSet<>(_communityToConfigVars.keySet());
    if (_matchedCommunities != null) {
      unmatched.removeAll(_matchedCommunities);
    }
    for (String community : unmatched) {
      Map<String, Set<String>> opMap = _communityToConfigVars.get(community);
      if (opMap != null) {
        if (opMap.containsKey("ADD")) {
          for (String var : new TreeSet<>(opMap.get("ADD"))) {
            _emptyCommunitiesWriter.println(var);
          }
        }
        if (opMap.containsKey("SET")) {
          for (String var : new TreeSet<>(opMap.get("SET"))) {
            _emptyCommunitiesWriter.println(var);
          }
        }
      }
    }
    _emptyCommunitiesWriter.close();
  }

  public PrintWriter getPropertyVarsWriter() {
    return _propertyVarsWriter;
  }

  public PrintWriter getPropertyWriter() {
    return _propertyWriter;
  }
}
