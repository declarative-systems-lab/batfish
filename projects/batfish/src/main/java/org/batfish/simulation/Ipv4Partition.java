package org.batfish.simulation;

import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.SortedSet;
import java.util.TreeSet;
import javax.annotation.Nullable;
import org.batfish.datamodel.AclAclLine;
import org.batfish.datamodel.AclIpSpace;
import org.batfish.datamodel.AclLine;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.EmptyIpSpace;
import org.batfish.datamodel.ExprAclLine;
import org.batfish.datamodel.HeaderSpace;
import org.batfish.datamodel.IpAccessList;
import org.batfish.datamodel.IpIpSpace;
import org.batfish.datamodel.IpSpace;
import org.batfish.datamodel.IpSpaceReference;
import org.batfish.datamodel.IpWildcard;
import org.batfish.datamodel.IpWildcardIpSpace;
import org.batfish.datamodel.IpWildcardSetIpSpace;
import org.batfish.datamodel.Prefix;
import org.batfish.datamodel.PrefixIpSpace;
import org.batfish.datamodel.UniverseIpSpace;
import org.batfish.datamodel.acl.AclLineMatchExpr;
import org.batfish.datamodel.acl.AndMatchExpr;
import org.batfish.datamodel.acl.DeniedByAcl;
import org.batfish.datamodel.acl.FalseExpr;
import org.batfish.datamodel.acl.MatchHeaderSpace;
import org.batfish.datamodel.acl.MatchSrcInterface;
import org.batfish.datamodel.acl.NotMatchExpr;
import org.batfish.datamodel.acl.OrMatchExpr;
import org.batfish.datamodel.acl.OriginatingFromDevice;
import org.batfish.datamodel.acl.PermittedByAcl;
import org.batfish.datamodel.acl.TrueExpr;

/** Collects boundaries that make every supported ACL predicate constant within each cell. */
final class Ipv4Partition {
  static final long END = 1L << 32;
  private static final int MAX_BOUNDARIES = 100_000;
  private final Configuration _configuration;
  private final SortedSet<Long> _sources = new TreeSet<>();
  private final SortedSet<Long> _destinations = new TreeSet<>();
  private final Set<String> _visitedAcls = new HashSet<>();
  private final Set<String> _activeAcls = new HashSet<>();

  Ipv4Partition(Configuration configuration) {
    _configuration = configuration;
    _sources.add(0L);
    _sources.add(END);
    _destinations.add(0L);
    _destinations.add(END);
  }

  Long[] sources() {
    return _sources.toArray(new Long[0]);
  }

  Long[] destinations() {
    return _destinations.toArray(new Long[0]);
  }

  void destination(Prefix prefix) {
    _destinations.add(prefix.getStartIp().asLong());
    _destinations.add(prefix.getEndIp().asLong() + 1);
  }

  void destination(IpSpace space) {
    add(space, _destinations, new HashSet<>());
  }

  void acl(@Nullable IpAccessList acl) {
    if (acl == null || _visitedAcls.contains(acl.getName())) {
      return;
    }
    if (!_activeAcls.add(acl.getName())) {
      throw new IllegalArgumentException("Cyclic ACL reference: " + acl.getName());
    }
    for (AclLine line : acl.getLines()) {
      if (line instanceof ExprAclLine) {
        expression(((ExprAclLine) line).getMatchCondition());
      } else if (line instanceof AclAclLine) {
        namedAcl(((AclAclLine) line).getAclName());
      } else {
        throw unsupported(line);
      }
    }
    _activeAcls.remove(acl.getName());
    _visitedAcls.add(acl.getName());
  }

  private void namedAcl(String name) {
    IpAccessList acl = _configuration.getIpAccessLists().get(name);
    if (acl == null) {
      throw new IllegalArgumentException("Undefined ACL: " + name);
    }
    acl(acl);
  }

  private void expression(AclLineMatchExpr expression) {
    if (expression instanceof MatchHeaderSpace) {
      HeaderSpace headers = ((MatchHeaderSpace) expression).getHeaderspace();
      HeaderSpace other =
          headers.toBuilder()
              .setSrcIps((IpSpace) null)
              .setDstIps((IpSpace) null)
              .setNotSrcIps((IpSpace) null)
              .setNotDstIps((IpSpace) null)
              .setSrcOrDstIps((IpSpace) null)
              .setNegate(false)
              .build();
      if (!other.equals(HeaderSpace.builder().build())) {
        throw new UnsupportedOperationException(
            "Effective FIB currently supports address-only IPv4 ACLs: " + headers);
      }
      add(headers.getSrcIps(), _sources, new HashSet<>());
      add(headers.getNotSrcIps(), _sources, new HashSet<>());
      add(headers.getSrcOrDstIps(), _sources, new HashSet<>());
      add(headers.getDstIps(), _destinations, new HashSet<>());
      add(headers.getNotDstIps(), _destinations, new HashSet<>());
      add(headers.getSrcOrDstIps(), _destinations, new HashSet<>());
    } else if (expression instanceof AndMatchExpr) {
      ((AndMatchExpr) expression).getConjuncts().forEach(this::expression);
    } else if (expression instanceof OrMatchExpr) {
      ((OrMatchExpr) expression).getDisjuncts().forEach(this::expression);
    } else if (expression instanceof NotMatchExpr) {
      expression(((NotMatchExpr) expression).getOperand());
    } else if (expression instanceof PermittedByAcl) {
      namedAcl(((PermittedByAcl) expression).getAclName());
    } else if (expression instanceof DeniedByAcl) {
      namedAcl(((DeniedByAcl) expression).getAclName());
    } else if (!(expression instanceof TrueExpr
        || expression instanceof FalseExpr
        || expression instanceof MatchSrcInterface
        || expression instanceof OriginatingFromDevice)) {
      throw unsupported(expression);
    }
  }

  private void add(@Nullable IpSpace space, SortedSet<Long> boundaries, Set<String> active) {
    if (space == null || space instanceof UniverseIpSpace || space instanceof EmptyIpSpace) {
      return;
    }
    if (space instanceof IpIpSpace) {
      long ip = ((IpIpSpace) space).getIp().asLong();
      boundaries.add(ip);
      boundaries.add(ip + 1);
    } else if (space instanceof PrefixIpSpace) {
      Prefix prefix = ((PrefixIpSpace) space).getPrefix();
      boundaries.add(prefix.getStartIp().asLong());
      boundaries.add(prefix.getEndIp().asLong() + 1);
    } else if (space instanceof IpWildcardIpSpace) {
      wildcard(((IpWildcardIpSpace) space).getIpWildcard(), boundaries);
    } else if (space instanceof IpWildcardSetIpSpace) {
      IpWildcardSetIpSpace set = (IpWildcardSetIpSpace) space;
      set.getWhitelist().forEach(w -> wildcard(w, boundaries));
      set.getBlacklist().forEach(w -> wildcard(w, boundaries));
    } else if (space instanceof AclIpSpace) {
      ((AclIpSpace) space).getLines().forEach(line -> add(line.getIpSpace(), boundaries, active));
    } else if (space instanceof IpSpaceReference) {
      String name = ((IpSpaceReference) space).getName();
      Map<String, IpSpace> spaces = _configuration.getIpSpaces();
      if (!active.add(name) || !spaces.containsKey(name)) {
        throw new IllegalArgumentException("Undefined or cyclic IP space: " + name);
      }
      add(spaces.get(name), boundaries, active);
      active.remove(name);
    } else {
      throw unsupported(space);
    }
    checkSize(boundaries);
  }

  private static void wildcard(IpWildcard wildcard, SortedSet<Long> boundaries) {
    expand(
        wildcard.getIp().asLong() & ~wildcard.getWildcardMask(),
        wildcard.getWildcardMask(),
        boundaries);
  }

  private static void expand(long base, long mask, SortedSet<Long> boundaries) {
    if ((mask & (mask + 1)) == 0) {
      boundaries.add(base);
      boundaries.add(base + mask + 1);
      checkSize(boundaries);
      return;
    }
    long bit = Long.highestOneBit(mask);
    expand(base, mask ^ bit, boundaries);
    expand(base | bit, mask ^ bit, boundaries);
  }

  private static void checkSize(SortedSet<Long> boundaries) {
    if (boundaries.size() > MAX_BOUNDARIES) {
      throw new IllegalArgumentException(
          "IPv4 partition exceeds " + MAX_BOUNDARIES + " boundaries");
    }
  }

  private static UnsupportedOperationException unsupported(Object object) {
    return new UnsupportedOperationException(
        "Unsupported effective FIB predicate: " + object.getClass().getSimpleName());
  }
}
