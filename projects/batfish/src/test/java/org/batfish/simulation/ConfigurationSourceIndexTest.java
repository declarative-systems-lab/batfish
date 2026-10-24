package org.batfish.simulation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public final class ConfigurationSourceIndexTest {
  @Rule public TemporaryFolder _folder = new TemporaryFolder();

  @Test
  public void testPrefixSequenceOrderAndWhitespace() throws IOException {
    Path root = _folder.newFolder().toPath();
    Files.createDirectory(root.resolve("configs"));
    Files.write(
        root.resolve("configs/node.cfg"),
        ("hostname node\nip prefix-list P seq  20 deny 0.0.0.0/0 le 32\n"
                + "ip prefix-list P seq  5 permit 10.0.0.0/8\n")
            .getBytes(StandardCharsets.UTF_8));
    ConfigurationSourceIndex index = ConfigurationSourceIndex.read(root);
    assertEquals(Integer.valueOf(3), index.listLine("node", "PREFIX_LIST", "P", 0).getLine());
    assertEquals(Integer.valueOf(2), index.listLine("node", "PREFIX_LIST", "P", 1).getLine());
    assertEquals("P:implicit-deny", index.listLine("node", "PREFIX_LIST", "P", -1).getName());
  }

  @Test
  public void testMissingSourceRetainsMatchedLineIdentity() {
    ConfigurationReference reference =
        new ConfigurationSourceIndex().listLine("node", "COMMUNITY_LIST", "C", 2);
    assertEquals("C:line-2", reference.getName());
    assertNull(reference.getFile());
    assertNull(reference.getLine());
  }
}
