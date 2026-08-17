package org.batfish.allinone.smt;

import static org.batfish.minesweeper.smt.Encoder.createOutputDirectory;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.is;

import com.fasterxml.jackson.databind.JsonNode;
import com.google.devtools.build.runfiles.Runfiles;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.batfish.common.util.BatfishObjectMapper;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class SmtPropertyTest {
    private static final String PROPERTIES_FILE = "properties.json";
    private static final String PROPERTY_INDEX_ENV = "SMT_PROPERTY_INDEX";
    private static final String WORK_DIRECTORY_ENV = "SMT_WORK_DIRECTORY";

    @Rule public TemporaryFolder _temp = new TemporaryFolder();

    private BatfishSimulationRunner _simulationRunner;
    private MinesweeperPropertyRunner _minesweeperRunner;
    private JsonNode _property;
    private int _propertyIndex;

    @Before
    public void setup() throws IOException {
        // read the configurations from the filesystem
        Runfiles runfiles = Runfiles.create();
        String workDirectory = System.getenv(WORK_DIRECTORY_ENV);
        if (workDirectory == null || workDirectory.isBlank()) {
            throw new IllegalArgumentException(
                WORK_DIRECTORY_ENV
                    + " must identify a directory under benchmarks/ or user-study/");
        }
        String configPath = runfiles.rlocation("batfish/" + workDirectory);
        if (configPath == null || !new File(configPath).isDirectory()) {
            throw new IllegalArgumentException(
                "Work directory is not available in runfiles: " + workDirectory);
        }
        List<JsonNode> properties = loadProperties(configPath);
        _propertyIndex = loadPropertyIndex(properties.size());
        _property = properties.get(_propertyIndex - 1);

        _simulationRunner = BatfishSimulationRunner.create(configPath, _temp);
        _minesweeperRunner = new MinesweeperPropertyRunner(_simulationRunner.getBatfish());
    }

    /**
     * Test network property: Reachability (or Isolation with negated) via SMT.
     * You can set node failures (or not) or edge failures (or not).
     */
    @Test
    public void testProperty() throws IOException {
        String propertyName = String.format("property-%02d", _propertyIndex);
        String outputDir = createOutputDirectory();
        BatfishObjectMapper.prettyWriter()
            .writeValue(new File(outputDir, "0_all_property.json"), _property);

        _simulationRunner.computeAndPrintDataPlane(outputDir);
        boolean verified = _minesweeperRunner.verify(_property);
        String outputDirectoryName = new File(outputDir).getName();
        if (verified) {
            System.out.printf(
                "[✓] Completed: Property %02d "
                    + "(Simulation State & Verification Encoding)%n",
                _propertyIndex);
        } else {
            System.out.printf(
                "[✗] Failed: Property %02d "
                    + "(Simulation State & Verification Encoding)%n",
                _propertyIndex);
        }
        System.out.printf("Output Directory: %s%n", outputDirectoryName);
        assertThat("Unverified property: " + propertyName, verified, is(true));
    }

    private static int loadPropertyIndex(int propertyCount) {
        String value = System.getenv(PROPERTY_INDEX_ENV);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(
                PROPERTY_INDEX_ENV + " must select one property using a 1-based index");
        }

        int propertyIndex;
        try {
            propertyIndex = Integer.parseInt(value);
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException(
                PROPERTY_INDEX_ENV + " must be a valid integer: " + value, error);
        }
        if (propertyIndex < 1 || propertyIndex > propertyCount) {
            throw new IllegalArgumentException(
                String.format(
                    "%s must be between 1 and %d: %d",
                    PROPERTY_INDEX_ENV, propertyCount, propertyIndex));
        }
        return propertyIndex;
    }

    private static List<JsonNode> loadProperties(String configPath) throws IOException {
        File propertyFile = new File(configPath, PROPERTIES_FILE);
        if (!propertyFile.isFile()) {
            throw new IllegalArgumentException("Missing property specification: " + propertyFile);
        }
        JsonNode root = BatfishObjectMapper.mapper().readTree(propertyFile);
        if (root == null || !root.isObject()) {
            throw new IllegalArgumentException(PROPERTIES_FILE + " must contain a JSON object");
        }
        JsonNode propertyNodes = root.get("properties");
        if (propertyNodes == null || !propertyNodes.isArray() || propertyNodes.isEmpty()) {
            throw new IllegalArgumentException(
                PROPERTIES_FILE + " must contain a non-empty properties array");
        }

        List<JsonNode> properties = new ArrayList<>();
        for (JsonNode property : propertyNodes) {
            if (!property.isObject()) {
                throw new IllegalArgumentException(
                    "Every entry in the properties array must be a JSON object");
            }
            properties.add(property);
        }
        return properties;
    }

}
