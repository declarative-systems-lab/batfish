package org.batfish.allinone.smt;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.SortedMap;
import org.batfish.datamodel.answers.AnswerElement;
import org.batfish.main.Batfish;
import org.batfish.main.BatfishTestUtils;
import org.batfish.main.TestrigText;
import org.batfish.minesweeper.utils.ConfigLoader;
import org.batfish.minesweeper.utils.RibPrinter;
import org.batfish.question.routes.RoutesAnswerer;
import org.batfish.question.routes.RoutesQuestion;
import org.junit.rules.TemporaryFolder;

/** Loads a Batfish snapshot, computes its dataplane, and writes simulation route outputs. */
final class BatfishSimulationRunner {
  private final Batfish _batfish;

  static BatfishSimulationRunner create(String configPath, TemporaryFolder tempFolder)
      throws IOException {
    TestrigText testrig = loadConfigurations(configPath);
    return new BatfishSimulationRunner(
        BatfishTestUtils.getBatfishFromTestrigText(testrig, tempFolder));
  }

  private BatfishSimulationRunner(Batfish batfish) {
    _batfish = batfish;
  }

  Batfish getBatfish() {
    return _batfish;
  }

  long computeAndPrintDataPlane(String outputDir) throws IOException {
    try (PrintWriter bgpRouteWriter =
            new PrintWriter(new FileWriter(new File(outputDir, "0_sim_bgp_routes.txt"), true));
        PrintWriter ospfRouteWriter =
            new PrintWriter(new FileWriter(new File(outputDir, "0_sim_ospf_routes.txt"), true));
        PrintWriter dataPlaneWriter =
            new PrintWriter(new FileWriter(new File(outputDir, "0_sim_data_plane.txt"), true))) {
      long simulationStartedAt = System.currentTimeMillis();
      _batfish.computeDataPlane(_batfish.getSnapshot(), bgpRouteWriter, ospfRouteWriter);
      long simulationElapsedMs = System.currentTimeMillis() - simulationStartedAt;
      RoutesQuestion routesQuestion = new RoutesQuestion();
      RoutesAnswerer routesAnswerer = new RoutesAnswerer(routesQuestion, _batfish);
      AnswerElement routesAnswer = routesAnswerer.answer(_batfish.getSnapshot());
      RibPrinter.printRouteTable(routesAnswer, dataPlaneWriter);
      return simulationElapsedMs;
    }
  }

  private static TestrigText loadConfigurations(String configPathStr) throws IOException {
    String configPath =
        configPathStr.endsWith("/") || configPathStr.endsWith("\\")
            ? configPathStr
            : configPathStr + System.getProperty("file.separator");

    SortedMap<String, byte[]> configurationsBytes =
        ConfigLoader.loadAllFiles(configPath + "configs", ".cfg");
    SortedMap<String, byte[]> hostsBytes =
        ConfigLoader.loadAllFiles(configPath + "hosts", ".json");
    SortedMap<String, byte[]> iptablesBytes =
        ConfigLoader.loadAllFiles(configPath + "iptables", ".iptables");

    return TestrigText.builder()
        .setConfigurationBytes(configurationsBytes)
        .setHostsBytes(hostsBytes)
        .setIptablesBytes(iptablesBytes)
        .build();
  }
}
