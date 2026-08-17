package org.batfish.representation.juniper;

import java.util.List;
import javax.annotation.Nonnull;
import javax.annotation.ParametersAreNonnullByDefault;
import org.batfish.common.Warnings;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.routing_policy.expr.NamedCommunitySet;
import org.batfish.datamodel.routing_policy.statement.SetCommunity;
import org.batfish.datamodel.routing_policy.statement.Statement;

@ParametersAreNonnullByDefault
public final class PsThenCommunitySet extends PsThen {

  public PsThenCommunitySet(String name, JuniperConfiguration configuration) {
    _name = name;
    _configuration = configuration;
  }

  @Override
  public void applyTo(
      List<Statement> statements,
      JuniperConfiguration juniperVendorConfiguration,
      Configuration c,
      Warnings warnings) {
    if (!c.getCommunitySets().containsKey(_name)) {
      // undefined reference; or not converted because it contains only regexes
      return;
    }
    _configuration.getOrCreateNamedCommunitiesUsedForSet().add(_name);
    statements.add(new SetCommunity(new NamedCommunitySet(_name)));
  }

  public @Nonnull String getName() {
    return _name;
  }

  private JuniperConfiguration _configuration;
  private final String _name;
}
