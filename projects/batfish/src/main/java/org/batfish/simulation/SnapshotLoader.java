package org.batfish.simulation;

import com.google.common.cache.CacheBuilder;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import org.batfish.common.BatfishLogger;
import org.batfish.common.NetworkSnapshot;
import org.batfish.config.Settings;
import org.batfish.dataplane.ibdp.SimulationDataPlanePlugin;
import org.batfish.identifiers.NetworkId;
import org.batfish.identifiers.SnapshotId;
import org.batfish.main.Batfish;
import org.batfish.storage.FileBasedStorage;

/** Owns temporary Batfish storage; the supplied snapshot is never modified. */
final class SnapshotLoader implements AutoCloseable {
  private final Path _storageRoot;
  private final NetworkSnapshot _snapshot;
  private final Batfish _batfish;

  SnapshotLoader(Path input) throws IOException {
    if (!Files.isDirectory(input.resolve("configs"))) {
      throw new IllegalArgumentException("Snapshot must contain a configs directory: " + input);
    }
    _storageRoot = Files.createTempDirectory("batfish-simulation-");
    _snapshot = new NetworkSnapshot(new NetworkId("simulation"), new SnapshotId("snapshot"));
    try {
      Settings settings = new Settings(new String[0]);
      settings.setLogger(new BatfishLogger("warn", false));
      settings.setStorageBase(_storageRoot);
      settings.setContainer(_snapshot.getNetwork().getId());
      settings.setTestrig(_snapshot.getSnapshot().getId());
      settings.setSnapshotName("snapshot");
      settings.setDataplaneEngineName(SimulationDataPlanePlugin.NAME);
      settings.setHaltOnConvertError(true);
      settings.setHaltOnParseError(true);
      FileBasedStorage storage = new FileBasedStorage(_storageRoot, settings.getLogger());
      try (Stream<Path> paths = Files.walk(input)) {
        List<Path> files = paths.filter(Files::isRegularFile).sorted().collect(Collectors.toList());
        for (Path file : files) {
          try (InputStream stream = Files.newInputStream(file)) {
            storage.storeSnapshotInputObject(stream, input.relativize(file).toString(), _snapshot);
          }
        }
      }
      _batfish =
          new Batfish(
              settings,
              CacheBuilder.newBuilder().build(),
              CacheBuilder.newBuilder().build(),
              Collections.synchronizedMap(new HashMap<>()),
              CacheBuilder.newBuilder().build(),
              storage,
              null);
    } catch (IOException | RuntimeException e) {
      try {
        close();
      } catch (IOException cleanup) {
        e.addSuppressed(cleanup);
      }
      throw e;
    }
  }

  Batfish getBatfish() {
    return _batfish;
  }

  NetworkSnapshot getSnapshot() {
    return _snapshot;
  }

  @Override
  public void close() throws IOException {
    try (Stream<Path> paths = Files.walk(_storageRoot)) {
      for (Path path : paths.sorted(Comparator.reverseOrder()).collect(Collectors.toList())) {
        Files.deleteIfExists(path);
      }
    }
  }
}
