package org.batfish.simulation;

import java.util.List;
import javax.annotation.Nullable;
import org.batfish.datamodel.AclAclLine;
import org.batfish.datamodel.AclLine;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.FilterResult;
import org.batfish.datamodel.Flow;
import org.batfish.datamodel.IpAccessList;
import org.batfish.datamodel.LineAction;
import org.batfish.datamodel.acl.AclLineEvaluator;
import org.batfish.datamodel.acl.DeniedByAcl;
import org.batfish.datamodel.acl.PermittedByAcl;

/** Records concrete first-match decisions, including nested ACLs and implicit deny. */
final class AclReplay extends AclLineEvaluator {
  private final Configuration _configuration;
  private final ConfigurationSourceIndex _sources;
  private final List<ConfigurationReference> _references;

  AclReplay(
      Configuration configuration,
      ConfigurationSourceIndex sources,
      Flow flow,
      @Nullable String ingress,
      List<ConfigurationReference> references) {
    super(flow, ingress, configuration.getIpAccessLists(), configuration.getIpSpaces());
    _configuration = configuration;
    _sources = sources;
    _references = references;
  }

  boolean permit(@Nullable IpAccessList acl, String stage) {
    if (acl == null) {
      _references.add(
          _sources.reference(_configuration.getHostname(), "ACL", stage + ":no-filter-permit"));
      return true;
    }
    return evaluate(acl).getAction() == LineAction.PERMIT;
  }

  private FilterResult evaluate(IpAccessList acl) {
    for (int i = 0; i < acl.getLines().size(); i++) {
      AclLine line = acl.getLines().get(i);
      LineAction action = visit(line);
      if (action != null) {
        _references.add(
            _sources.acl(_configuration.getHostname(), acl.getName(), i, line.getName()));
        return new FilterResult(i, action);
      }
    }
    _references.add(_sources.acl(_configuration.getHostname(), acl.getName(), null, null));
    return new FilterResult(null, LineAction.DENY);
  }

  @Override
  public LineAction visitAclAclLine(AclAclLine line) {
    FilterResult result = evaluate(_availableAcls.get(line.getAclName()));
    return result.getMatchLine() == null ? null : result.getAction();
  }

  @Override
  public Boolean visitPermittedByAcl(PermittedByAcl expression) {
    return evaluate(_availableAcls.get(expression.getAclName())).getAction() == LineAction.PERMIT;
  }

  @Override
  public Boolean visitDeniedByAcl(DeniedByAcl expression) {
    return evaluate(_availableAcls.get(expression.getAclName())).getAction() == LineAction.DENY;
  }
}
