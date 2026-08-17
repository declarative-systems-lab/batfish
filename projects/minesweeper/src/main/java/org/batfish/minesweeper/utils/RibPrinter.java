package org.batfish.minesweeper.utils;

import org.batfish.datamodel.answers.AnswerElement;
import org.batfish.datamodel.table.TableAnswerElement;
import org.batfish.datamodel.table.Row;
import org.batfish.datamodel.Configuration;
import com.fasterxml.jackson.databind.JsonNode;

import java.io.PrintWriter;
import java.util.Comparator;
import java.util.List;
import java.util.ArrayList;

/**
 * Utility class for printing a Batfish-style route table from an AnswerElement.
 */
public class RibPrinter {
  /**
   * Pretty-print the route table in a tabular format from a TableAnswerElement.
   *
   * @param answerElement a Batfish AnswerElement expected to be a TableAnswerElement
   *                      containing routing table entries
   */
  public static void printRouteTable(AnswerElement answerElement, PrintWriter writer) {
    // Ensure the answer element is a TableAnswerElement
    if (!(answerElement instanceof TableAnswerElement)) {
      System.out.println("Provided AnswerElement is not a TableAnswerElement.");
      return;
    }

    TableAnswerElement table = (TableAnswerElement) answerElement;
    List<Row> rows = table.getRowsList();
    rows = new ArrayList<>(rows);
    // sort the list according to the Node field
    rows.sort(Comparator.comparing(row -> row.get("Node").get("name").asText()));

    if (rows == null || rows.isEmpty()) {
      System.out.println("No route data available.");
      return;
    }

    // Define table header format and header (column widths)
    String format = "%-12s %-8s %-19s %-10s %-16s %-25s %-10s %-8s %-8s %-8s\n";
    String header = String.format(format, "Node", "VRF", "Network", "Protocol", "NextHopIP",
        "NextHopInterface", "NextHop", "Metric", "AD", "Tag");
    // Print column headers
    writer.print(header);
    // System.out.print(header);
    // Print a horizontal divider line
    writer.println(repeatChar('=', header.length()));
    // System.out.println(repeatChar('=', header.length()));

    // Iterate over each route entry and print its fields (default VRF only)
    for (Row row : rows) {
      String vrf = getFieldAsText(row, "VRF");
      if (!Configuration.DEFAULT_VRF_NAME.equals(vrf)) {
        continue;
      }
      String node = getFieldAsText(row, "Node", "name");
      String network = getFieldAsText(row, "Network");
      String protocol = getFieldAsText(row, "Protocol");
      String nextHopIp = getFieldAsText(row, "Next_Hop_IP");
      String nextHopInterface = getFieldAsText(row, "Next_Hop_Interface");
      String nextHop = getFieldAsText(row, "Next_Hop");
      long metric = getFieldAsLong(row, "Metric");
      int adminDistance = getFieldAsInt(row, "Admin_Distance");
      String tag = row.hasNonNull("Tag") ? row.get("Tag").toString() : "-";

      writer.printf(format, node, vrf, network, protocol, nextHopIp,
          nextHopInterface, nextHop, metric, adminDistance, tag);
      // System.out.printf(format, node, vrf, network, protocol, nextHopIp,
      //     nextHopInterface, nextHop, metric, adminDistance, tag);
    }

    // Flush and close the writer
    writer.flush();
    writer.close();
  }

  /** Helper: get a nested field as text (e.g., row.get("Node").get("name").asText()) */
  private static String getFieldAsText(Row row, String outer, String inner) {
    JsonNode outerNode = row.get(outer);
    return outerNode != null && outerNode.has(inner) ? outerNode.get(inner).asText() : "";
  }

  /** Helper: get a simple field as text (row.get("VRF").asText()) */
  private static String getFieldAsText(Row row, String key) {
    JsonNode node = row.get(key);
    return node != null ? node.asText() : "";
  }

  /** Helper: get a simple field as long (row.get("Metric").asLong()) */
  private static long getFieldAsLong(Row row, String key) {
    JsonNode node = row.get(key);
    return node != null ? node.asLong(0) : 0;
  }

  /** Helper: get a simple field as int (row.get("Admin_Distance").asInt()) */
  private static int getFieldAsInt(Row row, String key) {
    JsonNode node = row.get(key);
    return node != null ? node.asInt(0) : 0;
  }

  /**
   * Repeat a character `count` times and return the resulting string.
   *
   * @param c the character to repeat
   * @param count the number of repetitions
   * @return a String with the character repeated `count` times
   */
  private static String repeatChar(char c, int count) {
    StringBuilder builder = new StringBuilder(count);
    for (int i = 0; i < count; i++) {
        builder.append(c);
    }
    return builder.toString();
  }
}

