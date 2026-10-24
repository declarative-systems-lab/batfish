package org.batfish.dataplane.ibdp;

import org.batfish.common.NetworkSnapshot;
import org.batfish.common.plugin.DataPlanePlugin;
import org.batfish.simulation.ConfigurationSourceIndex;
import org.batfish.simulation.RibResult;

/** Adds a read-only, post-convergence collection pass to the ordinary iBDP plugin. */
public final class SimulationDataPlanePlugin extends DataPlanePlugin {
  public static final String NAME = "simulation";
  private final IncrementalDataPlanePlugin _delegate = new IncrementalDataPlanePlugin();
  private final ConfigurationSourceIndex _sources;
  private ComputeDataPlaneResult _result;
  private RibResult _rib;

  public SimulationDataPlanePlugin(ConfigurationSourceIndex sources) {
    _sources = sources;
  }

  @Override
  protected void dataPlanePluginInitialize() {
    _delegate.initialize(_pluginConsumer);
  }

  @Override
  public String getName() {
    return NAME;
  }

  @Override
  public ComputeDataPlaneResult computeDataPlane(NetworkSnapshot snapshot) {
    IbdpResult result = (IbdpResult) _delegate.computeDataPlane(snapshot);
    _rib = new ConvergedRouteCollector(_sources).collect(result);
    _result =
        new ComputeDataPlaneResult(result._answerElement, result._dataPlane, result._topologies);
    return result;
  }

  public RibResult getRib() {
    if (_rib == null) {
      throw new IllegalStateException("Dataplane has not been computed");
    }
    return _rib;
  }

  public ComputeDataPlaneResult getResult() {
    if (_result == null) {
      throw new IllegalStateException("Dataplane has not been computed");
    }
    return _result;
  }
}
