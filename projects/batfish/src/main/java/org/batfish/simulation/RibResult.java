package org.batfish.simulation;

import com.google.common.collect.ImmutableList;
import java.util.List;
import javax.annotation.Nullable;
import org.batfish.datamodel.AbstractRoute;

/** Installed routes and candidates evaluated against the same converged snapshot. */
public final class RibResult {
  public static final class Entry {
    private final String _node;
    private final String _vrf;
    private final AbstractRoute _route;
    private final boolean _protocolBest;
    private final @Nullable String _peer;
    private final @Nullable String _blockedBy;
    private final List<ConfigurationReference> _references;

    public Entry(
        String node,
        String vrf,
        AbstractRoute route,
        boolean protocolBest,
        @Nullable String peer,
        @Nullable String blockedBy,
        List<ConfigurationReference> references) {
      _node = node;
      _vrf = vrf;
      _route = route;
      _protocolBest = protocolBest;
      _peer = peer;
      _blockedBy = blockedBy;
      _references = ImmutableList.copyOf(references);
    }

    public String getNode() {
      return _node;
    }

    public String getVrf() {
      return _vrf;
    }

    public AbstractRoute getRoute() {
      return _route;
    }

    public boolean getProtocolBest() {
      return _protocolBest;
    }

    /** Sender for a blocked advertisement; accepted session identities are in the references. */
    public @Nullable String getPeer() {
      return _peer;
    }

    /** EXPORT or IMPORT for a policy rejection, otherwise null. */
    public @Nullable String getBlockedBy() {
      return _blockedBy;
    }

    public List<ConfigurationReference> getReferences() {
      return _references;
    }
  }

  private final List<Entry> _mainRoutes;
  private final List<Entry> _alternativeRoutes;
  private final List<Entry> _blockedRoutes;

  public RibResult(List<Entry> main, List<Entry> alternatives, List<Entry> blocked) {
    _mainRoutes = ImmutableList.copyOf(main);
    _alternativeRoutes = ImmutableList.copyOf(alternatives);
    _blockedRoutes = ImmutableList.copyOf(blocked);
  }

  public List<Entry> getMainRoutes() {
    return _mainRoutes;
  }

  public List<Entry> getAlternativeRoutes() {
    return _alternativeRoutes;
  }

  public List<Entry> getBlockedRoutes() {
    return _blockedRoutes;
  }
}
