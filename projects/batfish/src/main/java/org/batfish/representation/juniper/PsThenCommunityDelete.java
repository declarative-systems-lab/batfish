package org.batfish.representation.juniper;

import java.util.List;
import javax.annotation.Nonnull;
import org.batfish.common.Warnings;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.routing_policy.expr.NamedCommunitySet;
import org.batfish.datamodel.routing_policy.statement.DeleteCommunity;
import org.batfish.datamodel.routing_policy.statement.Statement;

public final class PsThenCommunityDelete extends PsThen {

  public PsThenCommunityDelete(String name) {
    _name = name;
  }

  @Override
  public void applyTo(
      List<Statement> statements,
      JuniperConfiguration juniperVendorConfiguration,
      Configuration c,
      Warnings warnings) {
    if (!c.getCommunityLists().containsKey(_name)) {
      // undefined reference
      return;
    }
    statements.add(new DeleteCommunity(new NamedCommunitySet(_name)));
  }

  public @Nonnull String getName() {
    return _name;
  }

  private final String _name;
}
