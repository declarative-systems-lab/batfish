package org.batfish.datamodel;

import static org.batfish.datamodel.Prefix.create;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;
import java.io.Serializable;
import java.util.Objects;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;
import org.batfish.common.BatfishException;

import com.google.common.base.Preconditions;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;

import org.batfish.common.util.SymbolicUtil;

public final class PrefixRange implements Serializable, Comparable<PrefixRange> {

  /** A prefix range representing all prefixes. */
  public static final PrefixRange ALL = fromString("0.0.0.0/0:0-32");

  public PrefixRange(Prefix prefix, SubRange lengthRange) {
    // Canonicalize the prefix by dropping extra bits in the address that are longer than any
    // relevant length.
    int prefixLength = prefix.getPrefixLength();
    int realPrefixLength = Math.min(prefixLength, lengthRange.getEnd());
    if (realPrefixLength == prefixLength) {
      _prefix = prefix;
    } else {
      // FIXME: if prefix or lengthRange have enableSmtVariable flag set to true,
      //        then we should keep same _prefix and _lengthRange with SMT symbolic variable
      //        (maybe we should modify _prefix length and mask SMT symbolic variables)
      //        annotated by yongzheng on 20250407
      Preconditions.checkState(
          false,
          "ERROR: PrefixRange:PrefixRange() " +
          "Prefix and SubRange enabling SMT symbolic variable are not supported");
      Ip realPrefixAddress = prefix.getStartIp().getNetworkAddress(realPrefixLength);
      _prefix = Prefix.create(realPrefixAddress, prefixLength);
    }
    _lengthRange = lengthRange;

    // check Prefix(prefix) and SubRange(lengthRange) enabling SMT symbolic variable flags
    // all flags are true or all flags are false
    Preconditions.checkState(
        (prefix.getEnableSmtVariable() == lengthRange.getEnableSmtVariable()), 
        "ERROR: PrefixRange:PrefixRange() " +
        "Prefix and SubRange enabling SMT symbolic variable are inconsistent");

    // NOTE: check here and fix when needed, annotated by yongzheng on 20250413
    // if (_prefix.getEnableSmtVariable() && _lengthRange.getEnableSmtVariable()) {
    //   // configure enable smt variable flag to true according to Prefix and SubRange
    //   _enableSmtVariable = true;
    // } else {
    //   // initialize enable smt variable flag to false
    //   _enableSmtVariable = false;
    // }

    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  /** Returns a {@link PrefixRange} that contains exactly the specified {@link Prefix}. */
  public static PrefixRange fromPrefix(Prefix prefix) {
    int prefixLength = prefix.getPrefixLength();
    return new PrefixRange(prefix, SubRange.singleton(prefixLength));
  }

  @JsonCreator
  public static PrefixRange fromString(String prefixRangeStr) {
    String[] parts = prefixRangeStr.split(":");
    if (parts.length == 1) {
      return fromPrefix(Prefix.parse(parts[0]));
    } else if (parts.length == 2) {
      return new PrefixRange(Prefix.parse(parts[0]), new SubRange(parts[1]));
    } else {
      throw new BatfishException("Invalid PrefixRange string: '" + prefixRangeStr + "'");
    }
  }

  /** Returns a {@link PrefixRange} that represents all more specific prefixes. */
  public static PrefixRange moreSpecificThan(Prefix prefix) {
    return new PrefixRange(
        prefix, new SubRange(prefix.getPrefixLength() + 1, Prefix.MAX_PREFIX_LENGTH));
  }

  public SubRange getLengthRange() {
    return _lengthRange;
  }

  public Prefix getPrefix() {
    return _prefix;
  }

  public boolean includesPrefixRange(PrefixRange argPrefixRange) {
    Prefix prefix = getPrefix();
    SubRange lengthRange = getLengthRange();
    int prefixLength = prefix.getPrefixLength();
    long maskedPrefixAsLong = prefix.getStartIp().getNetworkAddress(prefixLength).asLong();
    Prefix argPrefix = argPrefixRange.getPrefix();
    SubRange argLengthRange = argPrefixRange.getLengthRange();
    long argMaskedPrefixAsLong = argPrefix.getStartIp().getNetworkAddress(prefixLength).asLong();
    return maskedPrefixAsLong == argMaskedPrefixAsLong
        && lengthRange.getStart() <= argLengthRange.getStart()
        && lengthRange.getEnd() >= argLengthRange.getEnd();
  }

  @Override
  @JsonValue
  public String toString() {
    int prefixLength = _prefix.getPrefixLength();
    int low = _lengthRange.getStart();
    int high = _lengthRange.getEnd();
    if (prefixLength == low && prefixLength == high) {
      return _prefix.toString();
    } else {
      return _prefix + ":" + low + "-" + high;
    }
  }

  @Override
  public int compareTo(@Nonnull PrefixRange o) {
    int prefixCmp = _prefix.compareTo(o._prefix);
    if (prefixCmp != 0) {
      return prefixCmp;
    }
    return _lengthRange.compareTo(o._lengthRange);
  }

  @Override
  public int hashCode() {
    return Objects.hash(_prefix, _lengthRange);
  }

  @Override
  public boolean equals(@Nullable Object obj) {
    if (obj == this) {
      return true;
    } else if (!(obj instanceof PrefixRange)) {
      return false;
    }
    PrefixRange o = (PrefixRange) obj;
    return _prefix.equals(o._prefix) && _lengthRange.equals(o._lengthRange);
  }

  private /*final*/ Prefix _prefix;
  private /*final*/ SubRange _lengthRange;
  
  /** Add configuration constant - SMT symbolic variable */
  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  private static String format(String str) {
    String formatedStr = "";
    for (char c : str.toCharArray()) {
      switch (c) {
        case '.':
          formatedStr += '_';
          break;
        default:
          formatedStr += c;
          break;
      }
    }
    return formatedStr;
  }

  private static String longToIpString(long ip) {
    return String.format(
        "%d.%d.%d.%d",
        (ip >> 24) & 0xFF,
        (ip >> 16) & 0xFF,
        (ip >> 8) & 0xFF,
        ip & 0xFF
    );
  }

  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the prefix range is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("PrefixRange.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    // check and avoid shared object for Prefix
    if (_prefix.getEnableSmtVariable()) {
      System.out.println("WARNING: PrefixRange.initSmtVariable: " +
          "found shared Prefix, cloning it.");

      Prefix prefixBackup = _prefix;
      _prefix = Prefix.create(_prefix.getStartIp(), _prefix.getPrefixLength());

      // add additional assert for using shared object
      if (prefixBackup.getEnableSmtVariable() == _prefix.getEnableSmtVariable()) {
        throw new BatfishException("PrefixRange.initSmtVariable: cloning failed for shared object");
      }
    }

    // check and avoid shared object for SubRange
    if (_lengthRange.getEnableSmtVariable()) {
      System.out.println("WARNING: PrefixRange.initSmtVariable: " +
          "found shared SubRange, cloning it.");

      SubRange lengthRangeBackup = _lengthRange;
      _lengthRange = new SubRange(_lengthRange.getStart(), _lengthRange.getEnd());

      // add additional assert for using shared object
      if (lengthRangeBackup.getEnableSmtVariable() == _lengthRange.getEnableSmtVariable()) {
        throw new BatfishException("PrefixRange.initSmtVariable: cloning failed for shared object");
      }
    }

    long prefixIp = _prefix.getStartIp().asLong();
    String prefixIpStr = SymbolicUtil.longToIpString(prefixIp);
    String configVarPrefixUpdated = configVarPrefix + SymbolicUtil.format(prefixIpStr) + "__";

    // init smt variable for prefix and relevant length range configuration
    _prefix.initSmtVariable(context, solver, configVarPrefixUpdated);
    _lengthRange.initSmtVariable(context, solver, configVarPrefixUpdated);

    // add relevant configuration constant constraint (ge / le / eq with prefix length)
    BoolExpr rangeStartGePrefixLength =
        context.mkGe(_lengthRange.getConfigVarStart(), _prefix.getConfigVarLength());
    BoolExpr rangeEndGePrefixLength =
        context.mkGe(_lengthRange.getConfigVarEnd(), _prefix.getConfigVarLength());
    solver.add(rangeStartGePrefixLength);
    solver.add(rangeEndGePrefixLength);

    // configure the smt variable enable flag to true
    _enableSmtVariable = true;
    _configVarPrefix = configVarPrefix;
  }

  public boolean getEnableSmtVariable() {
    return _enableSmtVariable;
  }

  public String getConfigVarPrefix() {
    return _configVarPrefix;
  }
}
