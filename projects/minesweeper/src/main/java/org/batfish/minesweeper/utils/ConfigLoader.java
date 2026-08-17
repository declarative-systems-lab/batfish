package org.batfish.minesweeper.utils;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.SortedMap;
import java.util.TreeMap;

public class ConfigLoader {
  /**
   * Load all files from a filesystem directory into a map of filename -> byte[] content.
   *
   * @param dirPathStr absolute or relative path on the filesystem, e.g. "/home/user/configs"
   * @param extensionFilter (optional) file extension filter, e.g. ".cfg", or null for all files
   * @return sorted map from filename to file content; empty map if directory doesn't exist
   * @throws IOException if directory or files can't be read
   */
  public static SortedMap<String, byte[]> loadAllFiles(String dirPathStr, String extensionFilter) throws IOException {
    SortedMap<String, byte[]> result = new TreeMap<>();
    Path dirPath = Paths.get(dirPathStr);

    if (!Files.exists(dirPath) || !Files.isDirectory(dirPath)) {
      System.out.println("Directory does not exist or is not a directory: " + dirPathStr);
      return result; // empty map
    }

    try (DirectoryStream<Path> stream = Files.newDirectoryStream(dirPath)) {
      for (Path path : stream) {
        if (Files.isRegularFile(path)) {
          String filename = path.getFileName().toString();
          if (extensionFilter == null || filename.endsWith(extensionFilter)) {
            byte[] content = Files.readAllBytes(path);
            result.put(filename, content);
          }
        }
      }
    }

    return result;
  }
}
