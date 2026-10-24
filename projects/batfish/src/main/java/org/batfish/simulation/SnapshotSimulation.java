package org.batfish.simulation;

import java.io.IOException;
import java.nio.file.Path;
import java.util.Map;
import org.batfish.datamodel.Configuration;
import org.batfish.dataplane.ibdp.SimulationDataPlanePlugin;

/**
 * Simulates one immutable input snapshot and exposes its RIB and effective IPv4 forwarding table.
 */
public final class SnapshotSimulation implements AutoCloseable {
  private final SnapshotLoader _loader;
  private final SimulationDataPlanePlugin _plugin;
  private final ConfigurationSourceIndex _sources;
  private final Map<String, Configuration> _configurations;
  private EffectiveFibResult _effectiveFib;
  private boolean _closed;

  public static SnapshotSimulation open(Path snapshotDirectory) throws IOException {
    return new SnapshotSimulation(snapshotDirectory);
  }

  private SnapshotSimulation(Path input) throws IOException {
    _sources = ConfigurationSourceIndex.read(input);
    _loader = new SnapshotLoader(input);
    try {
      _plugin = new SimulationDataPlanePlugin(_sources);
      _plugin.initialize(_loader.getBatfish());
      _loader.getBatfish().computeDataPlane(_loader.getSnapshot());
      _configurations = _loader.getBatfish().loadConfigurations(_loader.getSnapshot());
    } catch (RuntimeException e) {
      try {
        _loader.close();
      } catch (IOException cleanup) {
        e.addSuppressed(cleanup);
      }
      throw e;
    }
  }

  public RibResult getRib() {
    return _plugin.getRib();
  }

  /** Expands address-only IPv4 ACLs; unsupported packet transformations fail explicitly. */
  public synchronized EffectiveFibResult getEffectiveFib() {
    if (_effectiveFib == null) {
      _effectiveFib =
          new EffectiveFibBuilder(_sources).build(_configurations, _plugin.getResult()._dataPlane);
    }
    return _effectiveFib;
  }

  @Override
  public synchronized void close() throws IOException {
    if (!_closed) {
      _loader.close();
      _closed = true;
    }
  }
}
