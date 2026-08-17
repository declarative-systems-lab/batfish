package org.batfish.allinone.smt;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.LinkedHashSet;
import java.util.Set;
import org.batfish.common.Answerer;
import org.batfish.datamodel.IpWildcard;
import org.batfish.datamodel.answers.AnswerElement;
import org.batfish.main.Batfish;
import org.batfish.minesweeper.answers.SmtReachabilityAnswerElement;
import org.batfish.minesweeper.question.SmtReachabilityQuestionPlugin.ReachabilityQuestion;

/** Converts property specifications into Minesweeper questions and verifies their answers. */
final class MinesweeperPropertyRunner {
  private static final String PROPERTIES_FILE = "properties.json";

  private final Batfish _batfish;

  MinesweeperPropertyRunner(Batfish batfish) {
    _batfish = batfish;
  }

  boolean verify(JsonNode property) {
    String propertyType = requiredText(property, "type");
    if (!"reachability".equals(propertyType)) {
      throw new IllegalArgumentException("Unsupported SMT property type: " + propertyType);
    }

    ReachabilityQuestion question = new ReachabilityQuestion();
    question.setIngressNodeRegex(requiredText(property, "ingressNodeRegex"));
    question.setFinalNodeRegex(requiredText(property, "finalNodeRegex"));

    JsonNode dstIpsNode = property.get("dstIps");
    if (dstIpsNode == null || !dstIpsNode.isArray() || dstIpsNode.isEmpty()) {
      throw new IllegalArgumentException(
          "dstIps must be a non-empty array in " + PROPERTIES_FILE);
    }
    Set<IpWildcard> dstIps = new LinkedHashSet<>();
    for (JsonNode dstIpNode : dstIpsNode) {
      if (!dstIpNode.isTextual()) {
        throw new IllegalArgumentException("Every dstIps value must be a string");
      }
      dstIps.add(IpWildcard.parse(dstIpNode.textValue()));
    }
    question.setDstIps(dstIps);

    JsonNode negateNode = property.get("negate");
    if (negateNode != null && !negateNode.isBoolean()) {
      throw new IllegalArgumentException("negate must be a boolean in " + PROPERTIES_FILE);
    }
    question.setNegate(negateNode != null && negateNode.booleanValue());

    AnswerElement answer = Answerer.create(question, _batfish).answer(_batfish.getSnapshot());
    if (!(answer instanceof SmtReachabilityAnswerElement)) {
      throw new IllegalStateException(
          "Expected SmtReachabilityAnswerElement, got " + answer.getClass().getSimpleName());
    }
    return ((SmtReachabilityAnswerElement) answer).getResult().isVerified();
  }

  private static String requiredText(JsonNode property, String fieldName) {
    JsonNode field = property.get(fieldName);
    if (field == null || !field.isTextual() || field.textValue().isBlank()) {
      throw new IllegalArgumentException(
          fieldName + " must be a non-empty string in " + PROPERTIES_FILE);
    }
    return field.textValue();
  }
}
