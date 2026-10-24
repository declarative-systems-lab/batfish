package org.batfish.simulation;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Predicate;
import java.util.function.Supplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import javax.annotation.Nullable;

/** Resolves logical configuration references to source lines when the mapping is unambiguous. */
public final class ConfigurationSourceIndex {
  private static final Pattern HOSTNAME = Pattern.compile("(?m)^hostname\\s+(\\S+)");
  private final Map<String, List<ConfigurationReference>> _lines = new HashMap<>();
  private final Map<String, ConfigurationReference> _references = new HashMap<>();

  public static ConfigurationSourceIndex read(Path snapshot) throws IOException {
    ConfigurationSourceIndex index = new ConfigurationSourceIndex();
    try (Stream<Path> paths = Files.walk(snapshot.resolve("configs"))) {
      for (Path file : paths.filter(Files::isRegularFile).sorted().collect(Collectors.toList())) {
        List<String> lines = Files.readAllLines(file);
        Matcher matcher = HOSTNAME.matcher(String.join("\n", lines));
        if (!matcher.find()) {
          continue;
        }
        String node = matcher.group(1).toLowerCase(Locale.ROOT);
        List<ConfigurationReference> entries =
            index._lines.computeIfAbsent(node, n -> new ArrayList<>());
        for (int i = 0; i < lines.size(); i++) {
          entries.add(
              new ConfigurationReference(
                  node,
                  "SOURCE",
                  "",
                  snapshot.relativize(file).toString(),
                  i + 1,
                  lines.get(i).trim()));
        }
      }
    }
    return index;
  }

  public ConfigurationReference reference(String node, String kind, String name) {
    return cached(
        "logical:" + node + ":" + kind + ":" + name,
        () -> new ConfigurationReference(node, kind, name, null, null, null));
  }

  public ConfigurationReference routeMap(String node, String name, String sequence) {
    Pattern pattern =
        Pattern.compile(
            "route-map " + Pattern.quote(name) + " (permit|deny) " + Pattern.quote(sequence));
    return resolve(
        node,
        "ROUTE_MAP",
        name + ":" + sequence,
        text -> pattern.matcher(normalize(text)).matches());
  }

  public ConfigurationReference acl(
      String node, String name, @Nullable Integer line, @Nullable String text) {
    String id = name + (line == null ? ":implicit-deny" : ":line-" + line);
    if (text == null) {
      return reference(node, "ACL", id);
    }
    return resolve(node, "ACL", id, source -> normalize(source).equals(normalize(text)));
  }

  public ConfigurationReference listLine(String node, String kind, String name, int line) {
    return cached(
        "list:" + node + ":" + kind + ":" + name + ":" + line,
        () -> findListLine(node, kind, name, line));
  }

  private ConfigurationReference findListLine(String node, String kind, String name, int line) {
    Pattern rule =
        Pattern.compile(
            kind.equals("PREFIX_LIST")
                ? "ip prefix-list " + Pattern.quote(name) + " (seq \\d+ )?(permit|deny) .*"
                : "ip community-list (standard |expanded )?"
                    + Pattern.quote(name)
                    + " (permit|deny) .*");
    List<ConfigurationReference> matches =
        _lines.getOrDefault(node, new ArrayList<>()).stream()
            .filter(r -> rule.matcher(normalize(r.getText())).matches())
            .collect(Collectors.toList());
    // Prefix-list sequence numbers determine evaluation order, not file order.
    if (kind.equals("PREFIX_LIST")
        && matches.stream().anyMatch(r -> normalize(r.getText()).contains(" seq "))) {
      if (!matches.stream().allMatch(r -> normalize(r.getText()).contains(" seq "))
          || matches.stream().map(ConfigurationSourceIndex::sequence).distinct().count()
              != matches.size()) {
        return reference(node, kind, name + (line < 0 ? ":implicit-deny" : ":line-" + line));
      }
      matches.sort(java.util.Comparator.comparingLong(ConfigurationSourceIndex::sequence));
    }
    if (line >= 0 && line < matches.size()) {
      ConfigurationReference source = matches.get(line);
      return new ConfigurationReference(
          node, kind, name + ":line-" + line, source.getFile(), source.getLine(), source.getText());
    }
    return reference(node, kind, name + (line < 0 ? ":implicit-deny" : ":line-" + line));
  }

  public ConfigurationReference resolve(
      String node, String kind, String name, Predicate<String> predicate) {
    return cached(
        "source:" + node + ":" + kind + ":" + name, () -> findSource(node, kind, name, predicate));
  }

  private ConfigurationReference findSource(
      String node, String kind, String name, Predicate<String> predicate) {
    List<ConfigurationReference> matches =
        _lines.getOrDefault(node, new ArrayList<>()).stream()
            .filter(r -> predicate.test(r.getText()))
            .collect(Collectors.toList());
    if (matches.size() != 1) {
      return reference(node, kind, name);
    }
    ConfigurationReference source = matches.get(0);
    return new ConfigurationReference(
        node, kind, name, source.getFile(), source.getLine(), source.getText());
  }

  private ConfigurationReference cached(String key, Supplier<ConfigurationReference> supplier) {
    ConfigurationReference reference = _references.get(key);
    if (reference == null) {
      reference = supplier.get();
      _references.put(key, reference);
    }
    return reference;
  }

  private static long sequence(ConfigurationReference reference) {
    return Long.parseLong(normalize(reference.getText()).split(" seq ")[1].split(" ")[0]);
  }

  private static String normalize(String text) {
    return text.trim().replaceAll("\\s+", " ");
  }
}
