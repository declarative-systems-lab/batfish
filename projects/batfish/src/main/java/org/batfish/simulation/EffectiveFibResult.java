package org.batfish.simulation;

import com.google.common.collect.ImmutableList;
import java.util.List;
import javax.annotation.Nullable;
import org.batfish.datamodel.FibEntry;
import org.batfish.datamodel.Ip;

/** Exact IPv4 address regions with identical local forwarding and ACL behavior. */
public final class EffectiveFibResult {
  public enum Action {
    FORWARD,
    ACCEPT,
    NULL_ROUTE,
    NO_ROUTE,
    DENIED_IN,
    DENIED_OUT
  }

  public static final class Entry {
    private final String _node;
    private final String _vrf;
    private final @Nullable String _ingressInterface;
    private final Ip _sourceStart;
    private final Ip _sourceEnd;
    private final Ip _destinationStart;
    private final Ip _destinationEnd;
    private final Action _action;
    private final @Nullable FibEntry _fibEntry;
    private final List<ConfigurationReference> _references;

    public Entry(
        String node,
        String vrf,
        @Nullable String ingressInterface,
        long sourceStart,
        long sourceEnd,
        long destinationStart,
        long destinationEnd,
        Action action,
        @Nullable FibEntry fibEntry,
        List<ConfigurationReference> references) {
      _node = node;
      _vrf = vrf;
      _ingressInterface = ingressInterface;
      _sourceStart = Ip.create(sourceStart);
      _sourceEnd = Ip.create(sourceEnd);
      _destinationStart = Ip.create(destinationStart);
      _destinationEnd = Ip.create(destinationEnd);
      _action = action;
      _fibEntry = fibEntry;
      _references = ImmutableList.copyOf(references);
    }

    public String getNode() {
      return _node;
    }

    public String getVrf() {
      return _vrf;
    }
    /** Null denotes traffic originating on the device. */
    public @Nullable String getIngressInterface() {
      return _ingressInterface;
    }

    public Ip getSourceStart() {
      return _sourceStart;
    }

    public Ip getSourceEnd() {
      return _sourceEnd;
    }

    public Ip getDestinationStart() {
      return _destinationStart;
    }

    public Ip getDestinationEnd() {
      return _destinationEnd;
    }

    public Action getAction() {
      return _action;
    }

    public @Nullable FibEntry getFibEntry() {
      return _fibEntry;
    }

    public List<ConfigurationReference> getReferences() {
      return _references;
    }
  }

  private final List<Entry> _permittedEntries;
  private final List<Entry> _deniedEntries;

  public EffectiveFibResult(List<Entry> permitted, List<Entry> denied) {
    _permittedEntries = ImmutableList.copyOf(permitted);
    _deniedEntries = ImmutableList.copyOf(denied);
  }

  /** Entries not denied by an ACL, including NO_ROUTE and NULL_ROUTE outcomes. */
  public List<Entry> getPermittedEntries() {
    return _permittedEntries;
  }

  public List<Entry> getDeniedEntries() {
    return _deniedEntries;
  }
}
