package org.batfish.simulation;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Predicate;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import javax.annotation.Nullable;
import org.batfish.datamodel.AbstractRouteBuilder;
import org.batfish.datamodel.AbstractRouteDecorator;
import org.batfish.datamodel.BgpSessionProperties;
import org.batfish.datamodel.CommunityList;
import org.batfish.datamodel.CommunityListLine;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.Prefix;
import org.batfish.datamodel.RouteFilterLine;
import org.batfish.datamodel.RouteFilterList;
import org.batfish.datamodel.bgp.community.Community;
import org.batfish.datamodel.routing_policy.Environment;
import org.batfish.datamodel.routing_policy.Environment.Direction;
import org.batfish.datamodel.routing_policy.Result;
import org.batfish.datamodel.routing_policy.RoutingPolicy;
import org.batfish.datamodel.routing_policy.expr.BooleanExpr;
import org.batfish.datamodel.routing_policy.expr.BooleanExprVisitor;
import org.batfish.datamodel.routing_policy.statement.If;
import org.batfish.datamodel.routing_policy.statement.Statement;

/** Replays concrete policy evaluation with isolated tracing wrappers. Not thread safe. */
public final class PolicyReplay {
  private static final Pattern CLAUSE = Pattern.compile("~RMCLAUSE~(.+)~(\\d+)~");
  private final Configuration _configuration;
  private final ConfigurationSourceIndex _sources;
  private final Map<String, RoutingPolicy> _policies = new HashMap<>();
  private final Map<String, RouteFilterList> _prefixLists = new HashMap<>();
  private final Map<String, CommunityList> _communityLists = new HashMap<>();
  private List<ConfigurationReference> _references = new ArrayList<>();

  public PolicyReplay(Configuration configuration, ConfigurationSourceIndex sources) {
    _configuration = configuration;
    _sources = sources;
    configuration
        .getRoutingPolicies()
        .forEach(
            (name, policy) -> {
              RoutingPolicy copy =
                  new RoutingPolicy(name, configuration) {
                    @Override
                    public Result call(Environment environment) {
                      int start = _references.size();
                      Result result = super.call(environment);
                      boolean clauseMatched =
                          _references.subList(start, _references.size()).stream()
                              .anyMatch(
                                  r ->
                                      r.getKind().equals("ROUTE_MAP")
                                          && r.getName().startsWith(name + ":"));
                      if (!RoutingPolicy.isGenerated(name) && !clauseMatched) {
                        _references.add(
                            _sources.reference(
                                configuration.getHostname(),
                                "ROUTE_MAP",
                                name
                                    + (result.getBooleanValue()
                                        ? ":default-permit"
                                        : ":default-deny")));
                      }
                      return result;
                    }
                  };
              copy.setStatements(copyStatements(policy.getStatements()));
              _policies.put(name, copy);
            });
    configuration
        .getRouteFilterLists()
        .forEach(
            (name, list) ->
                _prefixLists.put(
                    name,
                    new RouteFilterList(name, list.getLines()) {
                      @Override
                      public boolean permits(Prefix prefix) {
                        int matched = -1;
                        for (int i = 0; i < getLines().size(); i++) {
                          RouteFilterLine line = getLines().get(i);
                          if (line.getIpWildcard().containsIp(prefix.getStartIp())
                              && line.getLengthRange().includes(prefix.getPrefixLength())) {
                            matched = i;
                            break;
                          }
                        }
                        _references.add(
                            _sources.listLine(
                                configuration.getHostname(), "PREFIX_LIST", name, matched));
                        return super.permits(prefix);
                      }
                    }));
    configuration
        .getCommunityLists()
        .forEach(
            (name, list) ->
                _communityLists.put(
                    name,
                    new CommunityList(name, list.getLines(), list.getInvertMatch()) {
                      @Override
                      public boolean matchCommunity(
                          @Nullable Environment environment, Community community) {
                        recordCommunity(
                            name,
                            list,
                            line ->
                                line.getMatchCondition().matchCommunity(environment, community));
                        return super.matchCommunity(environment, community);
                      }

                      @Override
                      public boolean matchCommunities(
                          Environment environment, java.util.Set<Community> communities) {
                        if (!reducible()) {
                          recordCommunity(
                              name,
                              list,
                              line ->
                                  line.getMatchCondition()
                                      .matchCommunities(environment, communities));
                        }
                        return super.matchCommunities(environment, communities);
                      }
                    }));
  }

  private void recordCommunity(
      String name, CommunityList list, Predicate<CommunityListLine> matches) {
    int matched = -1;
    for (int i = 0; i < list.getLines().size(); i++) {
      if (matches.test(list.getLines().get(i))) {
        matched = i;
        break;
      }
    }
    _references.add(
        _sources.listLine(_configuration.getHostname(), "COMMUNITY_LIST", name, matched));
  }

  private List<Statement> copyStatements(List<Statement> statements) {
    return statements.stream()
        .map(
            statement -> {
              if (!(statement instanceof If)) {
                return statement;
              }
              If original = (If) statement;
              BooleanExpr guard = original.getGuard();
              Matcher matcher =
                  CLAUSE.matcher(original.getComment() == null ? "" : original.getComment());
              if (matcher.matches()) {
                guard =
                    new RecordingGuard(
                        guard,
                        _sources.routeMap(
                            _configuration.getHostname(), matcher.group(1), matcher.group(2)));
              }
              return new If(
                  original.getComment(),
                  guard,
                  copyStatements(original.getTrueStatements()),
                  copyStatements(original.getFalseStatements()));
            })
        .collect(Collectors.toList());
  }

  private final class RecordingGuard extends BooleanExpr {
    private final BooleanExpr _delegate;
    private final ConfigurationReference _reference;

    private RecordingGuard(BooleanExpr delegate, ConfigurationReference reference) {
      _delegate = delegate;
      _reference = reference;
    }

    @Override
    public Result evaluate(Environment environment) {
      Result result = _delegate.evaluate(environment);
      if (!result.getExit() && result.getBooleanValue()) {
        _references.add(_reference);
      }
      return result;
    }

    @Override
    public <T, U> T accept(BooleanExprVisitor<T, U> visitor, U arg) {
      return _delegate.accept(visitor, arg);
    }

    @Override
    public boolean equals(Object other) {
      return this == other;
    }

    @Override
    public int hashCode() {
      return System.identityHashCode(this);
    }
  }

  public boolean process(
      @Nullable String policyName,
      AbstractRouteDecorator input,
      AbstractRouteBuilder<?, ?> output,
      @Nullable BgpSessionProperties session,
      Direction direction,
      List<ConfigurationReference> references) {
    if (policyName == null) {
      references.add(
          _sources.reference(
              _configuration.getHostname(), "POLICY", direction + ":no-policy-permit"));
      return true;
    }
    RoutingPolicy policy = _policies.get(policyName);
    if (policy == null) {
      throw new IllegalArgumentException("Undefined routing policy: " + policyName);
    }
    _references = references;
    try {
      Environment environment =
          Environment.builder(_configuration)
              .setRoutingPolicies(_policies)
              .setRouteFilterLists(_prefixLists)
              .setCommunityLists(_communityLists)
              .setOriginalRoute(input)
              .setOutputRoute(output)
              .setBgpSessionProperties(session)
              .setDirection(direction)
              .build();
      Result result = policy.call(environment);
      boolean permit =
          result.getBooleanValue() && !Boolean.TRUE.equals(environment.getSuppressed());
      references.add(
          _sources.reference(
              _configuration.getHostname(), "POLICY", policyName + (permit ? ":permit" : ":deny")));
      return permit;
    } finally {
      _references = new ArrayList<>();
    }
  }
}
