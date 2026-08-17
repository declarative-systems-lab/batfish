package org.batfish.common.util;

import java.util.regex.Pattern;
import java.util.regex.Matcher;

public class SymbolicUtil {

  public static String format(String str) {
    String formatedStr = "";
  
    // replace some characters with '_'
    for (char c : str.toCharArray()) {
      switch (c) {
        case '~':
        case '-':
        case ':':
        case '.':
        case '/':
          formatedStr += '_';
          break;
        default:
          formatedStr += c;
          break;
      }
    }
  
    // remove the start with '_'
    if (formatedStr.startsWith("_")) {
      formatedStr = formatedStr.substring(1);
    }
    // remove the end with '_'
    if (formatedStr.endsWith("_")) {
      formatedStr = formatedStr.substring(0, formatedStr.length() - 1);
    }
  
    return formatedStr;
  }
  
  public static String incrementConfigLineSuffix(String routingPolicyPrefixName) {
    // match end with "_LineN" (N is integer number)
    String pattern = "(.+)__Line(\\d+)__$";
    Pattern r = Pattern.compile(pattern);
    Matcher m = r.matcher(routingPolicyPrefixName);
  
    if (m.matches()) {
      String prefix = m.group(1);
      int number = Integer.parseInt(m.group(2));
      return prefix + "__Line" + (number + 1) + "__";
    } else {
      return routingPolicyPrefixName + "_Line1__";
    }
  }

  public static String configLineSuffix(
      String routingPolicyPrefixName, Integer seqNumber, Integer lineNumber) {
    return routingPolicyPrefixName + "_Seq" + seqNumber + "__Line" + lineNumber + "__";
  }
  
  public static String longToIpString(long ip) {
    return String.format(
        "%d.%d.%d.%d",
        (ip >> 24) & 0xFF,
        (ip >> 16) & 0xFF,
        (ip >> 8) & 0xFF,
        ip & 0xFF
    );
  }

}
