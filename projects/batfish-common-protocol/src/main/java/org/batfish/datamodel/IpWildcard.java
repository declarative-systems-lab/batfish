package org.batfish.datamodel;

import static com.google.common.base.Preconditions.checkArgument;
import static com.google.common.base.Preconditions.checkState;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;
import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.ArithExpr;
import com.microsoft.z3.BitVecExpr;

import java.io.Serializable;
import java.util.Comparator;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;
import javax.annotation.ParametersAreNonnullByDefault;

import org.batfish.common.BatfishException;

/** An IP wildcard consisting of a IP address and a wildcard (also expressed as an IP address) */
@ParametersAreNonnullByDefault
public final class IpWildcard implements Serializable, Comparable<IpWildcard> {
  @Nonnull private final Ip _ip;
  // Set bits are "don't care" bits
  private final long _wildcardMask;

  private static final long ALL_BITS_MASKED = 0xFFFFFFFFL;
  public static final IpWildcard ANY = ipWithWildcardMask(Ip.ZERO, ALL_BITS_MASKED);

  private static Ip parseAddress(String str) {
    if (str.contains(":")) {
      String[] parts = str.split(":");
      checkArgument(parts.length == 2, "Invalid IpWildcard string: '%s'");
      return Ip.parse(parts[0]);
    } else if (str.contains("/")) {
      String[] parts = str.split("/");
      checkArgument(parts.length == 2, "Invalid IpWildcard string: '%s'");
      return Ip.parse(parts[0]);
    } else {
      return Ip.parse(str);
    }
  }

  private static Ip parseMask(String str) {
    if (str.contains(":")) {
      String[] parts = str.split(":");
      checkArgument(parts.length == 2, "Invalid IpWildcard string: '%s'");
      return Ip.parse(parts[1]);
    } else if (str.contains("/")) {
      String[] parts = str.split("/");
      checkArgument(parts.length == 2, "Invalid IpWildcard string: '%s'");
      int prefixLength = Integer.parseInt(parts[1]);
      return Ip.numSubnetBitsToSubnetMask(prefixLength).inverted();
    } else {
      return Ip.ZERO;
    }
  }

  /**
   * Return an {@link IpWildcard} from the given {@link Ip IP address} and {@code wildcardMask}.
   *
   * <p>Bits that are set in the {@code wildcardMask} are "don't care" bits.
   */
  public static IpWildcard ipWithWildcardMask(Ip address, long wildcardMask) {
    return new IpWildcard(address, wildcardMask);
  }

  /**
   * Return an {@link IpWildcard} from the given {@link Ip IP address} and {@link Ip wildcardMask}.
   *
   * <p>Bits that are set in the {@code wildcardMask} are "don't care" bits.
   *
   * @see #ipWithWildcardMask(Ip, long) for a version that directly accesses the mask.
   */
  public static IpWildcard ipWithWildcardMask(Ip address, Ip wildcardMask) {
    return ipWithWildcardMask(address, wildcardMask.asLong());
  }

  public static IpWildcard create(Prefix prefix) {
    int wildcardBits = Prefix.MAX_PREFIX_LENGTH - prefix.getPrefixLength();
    long wildcardMask = (1L << wildcardBits) - 1L;
    return ipWithWildcardMask(prefix.getStartIp(), wildcardMask);
  }

  public static IpWildcard create(Ip ip) {
    return ipWithWildcardMask(ip, 0L);
  }

  @JsonCreator
  public static IpWildcard parse(String str) {
    return ipWithWildcardMask(parseAddress(str), parseMask(str).asLong());
  }

  public boolean containsIp(Ip ip) {
    checkArgument(ip.valid(), "Invalid IP address %s", ip);
    long thisMasked = _ip.asLong() | _wildcardMask;
    long ipMasked = ip.asLong() | _wildcardMask;
    return thisMasked == ipMasked;
  }

  @Override
  public int compareTo(IpWildcard o) {
    if (this == o) {
      return 0;
    }
    return Comparator.comparing(IpWildcard::getIp)
        .thenComparing(IpWildcard::getWildcardMask)
        .compare(this, o);
  }

  @Override
  public boolean equals(@Nullable Object o) {
    if (o == this) {
      return true;
    } else if (!(o instanceof IpWildcard)) {
      return false;
    }
    IpWildcard other = (IpWildcard) o;
    return _ip.equals(other._ip) && _wildcardMask == other._wildcardMask;
  }

  @Override
  public int hashCode() {
    return 31 * _ip.hashCode() + Long.hashCode(_wildcardMask);
  }

  @Nonnull
  public Ip getIp() {
    return _ip;
  }

  @Nonnull
  public Ip getWildcardMaskAsIp() {
    return Ip.create(_wildcardMask);
  }

  public long getWildcardMask() {
    return _wildcardMask;
  }

  public long getMask() {
    return ALL_BITS_MASKED ^ _wildcardMask;
  }

  /**
   * @param other another IpWildcard
   * @return whether the set of IPs matched by this intersects the set of those matched by other.
   */
  public boolean intersects(IpWildcard other) {
    long differentIpBits = _ip.asLong() ^ other._ip.asLong();
    long canDiffer = _wildcardMask | other._wildcardMask;

    /*
     * All IP bits that different must be wild in either this or other.
     */
    return (differentIpBits & canDiffer) == differentIpBits;
  }

  // if _wildcardMask is       0b0000000011111111
  // then _wlidcardMask + 1 is 0b0000000100000000
  // so _wlidcardMask & (_wlidcardMask + 1) is 0L
  public boolean isPrefix() {
    return (_wildcardMask & (_wildcardMask + 1L)) == 0L;
  }

  /**
   * @param other another IpWildcard
   * @return whether the set of IPs matched by this is a subset of those matched by other.
   */
  public boolean subsetOf(IpWildcard other) {
    return other.supersetOf(this);
  }

  /**
   * @param other another IpWildcard
   * @return whether the set of IPs matched by this is a superset of those matched by other.
   */
  public boolean supersetOf(IpWildcard other) {
    long wildToThis = _wildcardMask;
    long wildToOther = other._wildcardMask;
    long differentIpBits = _ip.asLong() ^ other._ip.asLong();

    /*
     * 1. Any bits wild in other must be wild in this (i.e. other's wild bits must be a subset
     *    of this' wild bits).
     * 2. Any IP bits that differ must be wild in this.
     */
    return (wildToThis & wildToOther) == wildToOther
        && (wildToThis & differentIpBits) == differentIpBits;
  }

  @Nonnull
  public IpWildcardIpSpace toIpSpace() {
    return IpWildcardIpSpace.create(this);
  }

  public Prefix toPrefix() {
    checkState(isPrefix(), "Invalid wildcard format for conversion to prefix: %s", _wildcardMask);
    return Prefix.create(_ip, Integer.numberOfLeadingZeros((int) _wildcardMask));
  }

  public Prefix toPrefixWithSymbolicVariables() {
    checkState(isPrefix(), "Invalid wildcard format for conversion to prefix: %s", _wildcardMask);
    return Prefix.create(
        _ip, Integer.numberOfLeadingZeros((int) _wildcardMask), _configVarIp, _configVarMask,
        _configVarLength);
  }

  @JsonValue
  @Override
  public String toString() {
    if (_wildcardMask == 0L) {
      return _ip.toString();
    } else if (isPrefix()) {
      return toPrefix().toString();
    } else {
      return _ip + ":" + getWildcardMaskAsIp();
    }
  }

  private IpWildcard(Ip address, long wildcardMask) {
    checkArgument(address.valid(), "Invalid IP address %s", address);
    checkArgument(
        (wildcardMask & ALL_BITS_MASKED) == wildcardMask, "Invalid mask %s", wildcardMask);

    long inputIp = address.asLong();
    long canonicalIp = inputIp & (ALL_BITS_MASKED ^ wildcardMask);
    _ip = (canonicalIp == inputIp) ? address : Ip.create(canonicalIp);
    _wildcardMask = wildcardMask;

    // initialize SMT variable flag to false
    _enableSmtVariable = false;
  }

  /** Add configuration constant - SMT symbolic variable */
  private static int BITVEC_EXPR_SIZE = 32;

  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  private transient BitVecExpr _configVarIp;
  private transient BitVecExpr _configVarMask;
  private transient ArithExpr _configVarLength;

  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the ip wildcard is not shared object
    if (_enableSmtVariable) {
      throw new BatfishException("IpWildcard.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    long prefixIp = _ip.asLong();

    _configVarIp = context.mkBVConst(configVarPrefix + "ip", BITVEC_EXPR_SIZE);
    _configVarMask = context.mkBVConst(configVarPrefix + "mask", BITVEC_EXPR_SIZE);
    _configVarLength = context.mkIntConst(configVarPrefix + "length");

    // add relevant configuration constant constraints
    // original wildcardMask is 0b000011111111
    // modified subnetMask is   0b111100000000
    BoolExpr configVarIpConstraint = context.mkEq(
        _configVarIp, context.mkBV(prefixIp, BITVEC_EXPR_SIZE));
    BoolExpr configVarMaskConstraint = context.mkEq(
        _configVarMask, context.mkBV((~_wildcardMask), BITVEC_EXPR_SIZE));
    BoolExpr configVarLengthConstraint = context.mkEq(
        _configVarLength, context.mkInt(Prefix.MAX_PREFIX_LENGTH - Long.bitCount(_wildcardMask)));
    solver.add(configVarIpConstraint);
    solver.add(configVarMaskConstraint);
    solver.add(configVarLengthConstraint);

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

  public BitVecExpr getConfigVarIp() {
    return _configVarIp;
  }

  public BitVecExpr getConfigVarMask() {
    return _configVarMask;
  }

  public ArithExpr getConfigVarLength() {
    return _configVarLength;
  }
}
