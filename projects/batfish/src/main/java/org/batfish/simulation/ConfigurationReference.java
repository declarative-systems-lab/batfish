package org.batfish.simulation;

import java.io.Serializable;
import javax.annotation.Nullable;

/** A configuration statement or an implicit policy decision. */
public final class ConfigurationReference implements Serializable {
  private final String _node;
  private final String _kind;
  private final String _name;
  private final @Nullable String _file;
  private final @Nullable Integer _line;
  private final @Nullable String _text;

  public ConfigurationReference(
      String node,
      String kind,
      String name,
      @Nullable String file,
      @Nullable Integer line,
      @Nullable String text) {
    _node = node;
    _kind = kind;
    _name = name;
    _file = file;
    _line = line;
    _text = text;
  }

  public String getNode() {
    return _node;
  }

  public String getKind() {
    return _kind;
  }

  public String getName() {
    return _name;
  }

  public @Nullable String getFile() {
    return _file;
  }

  public @Nullable Integer getLine() {
    return _line;
  }

  public @Nullable String getText() {
    return _text;
  }
}
