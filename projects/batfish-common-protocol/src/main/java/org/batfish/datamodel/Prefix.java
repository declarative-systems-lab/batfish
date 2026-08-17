package org.batfish.datamodel;

import static com.google.common.base.Preconditions.checkArgument;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;
import java.io.Serializable;
import java.util.Optional;
import javax.annotation.Nonnull;
import javax.annotation.Nullable;
import javax.annotation.ParametersAreNonnullByDefault;

import com.microsoft.z3.Context;
import com.microsoft.z3.Solver;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.ArithExpr;
import com.microsoft.z3.BitVecExpr;

import org.batfish.common.BatfishException;

/** An IPv4 Prefix */
@ParametersAreNonnullByDefault
public final class Prefix implements Comparable<Prefix>, Serializable {

  /** Maximum prefix length (number of bits) for a IPv4 address, which is 32 */
  public static final int MAX_PREFIX_LENGTH = 32;

  /** A "0.0.0.0/0" prefix */
  public static final Prefix ZERO = create(Ip.ZERO, 0);

  /** Multicast IPs are in "244.0.0.0/4". */
  public static final Prefix MULTICAST = create(Ip.parse("224.0.0.0"), 4);

  /**
   * /32s are loopback interfaces -- no hosts are connected.
   *
   * <p>/31s are point-to-point connections between nodes -- again, no hosts.
   *
   * <p>/30s could have hosts, but usually do not. Historically, each subnet was required to reserve
   * two addresses: one identifying the network itself, and a broadcast address. This made /31s
   * invalid, since there were no usable IPs left over. A /30 had 2 usable IPs, so was used for
   * point-to-point connections. Eventually /31s were allowed, but we assume here that any /30s are
   * hold-over point-to-point connections in the legacy model.
   */
  public static final int HOST_SUBNET_MAX_PREFIX_LENGTH = 29;

  private static long wildcardMaskForPrefixLength(int prefixLength) {
    assert 0 <= prefixLength && prefixLength <= Prefix.MAX_PREFIX_LENGTH;
    return (1L << (Prefix.MAX_PREFIX_LENGTH - prefixLength)) - 1;
  }

  /** Parse a {@link Prefix} from a string. */
  @Nonnull
  @JsonCreator
  public static Prefix parse(@Nullable String text) {
    checkArgument(text != null, "Invalid IPv4 prefix %s", text);
    String[] parts = text.split("/");
    checkArgument(parts.length == 2, "Invalid prefix string: \"%s\"", text);
    Ip ip = Ip.parse(parts[0]);
    int prefixLength;
    try {
      prefixLength = Integer.parseInt(parts[1]);
    } catch (NumberFormatException e) {
      throw new IllegalArgumentException("Invalid prefix length: \"" + parts[1] + "\"", e);
    }
    return create(ip, prefixLength);
  }

  /**
   * Return an {@link Optional} {@link Prefix} from a string, or {@link Optional#empty} if the
   * string does not represent a {@link Prefix}.
   */
  @Nonnull
  public static Optional<Prefix> tryParse(@Nonnull String text) {
    try {
      return Optional.of(parse(text));
    } catch (IllegalArgumentException e) {
      return Optional.empty();
    }
  }

  /**
   * Parse a {@link Prefix} from a string.
   *
   * @throws IllegalArgumentException if the string does not represent a prefix in canonical form.
   */
  public static @Nonnull Prefix strict(String prefixStr) {
    Prefix prefix = parse(prefixStr);
    checkArgument(prefix.toString().equals(prefixStr), "Non-canonical prefix: %s", prefixStr);
    return prefix;
  }

  private final Ip _ip;

  private final int _prefixLength;

  private Prefix(Ip ip, int prefixLength) {
    checkArgument(
        prefixLength >= 0 && prefixLength <= MAX_PREFIX_LENGTH,
        "Invalid prefix length %s",
        prefixLength);
    if (ip.valid()) {
      // TODO: stop using Ip as a holder for invalid values.
      _ip = ip.getNetworkAddress(prefixLength);
    } else {
      _ip = ip;
    }
    _prefixLength = prefixLength;
    
    // initialize enable smt variable flag to false
    _enableSmtVariable = false;
  }

  private Prefix(
      Ip ip, int prefixLength, BitVecExpr configVarIp, BitVecExpr configVarMask,
      ArithExpr configVarLength) {
    checkArgument(
            prefixLength >= 0 && prefixLength <= MAX_PREFIX_LENGTH,
            "Invalid prefix length %s",
            prefixLength);
    if (ip.valid()) {
      // TODO: stop using Ip as a holder for invalid values.
      _ip = ip.getNetworkAddress(prefixLength);
    } else {
      _ip = ip;
    }
    _prefixLength = prefixLength;

    // copy configuration symbolic variables and relevant flag
    _configVarIp = configVarIp;
    _configVarMask = configVarMask;
    _configVarLength = configVarLength;
    _enableSmtVariable = true;
  }

  public static Prefix create(Ip ip, int prefixLength) {
    return new Prefix(ip, prefixLength);
  }

  public static Prefix create(
      Ip ip, int prefixLength, BitVecExpr configVarIp, BitVecExpr configVarMask,
      ArithExpr configVarLength) {
    return new Prefix(ip, prefixLength, configVarIp, configVarMask, configVarLength);
  }

  public static Prefix create(Ip address, Ip mask) {
    return create(address, mask.numSubnetBits());
  }

  public static Prefix create(
      Ip address, Ip mask, BitVecExpr configVarIp, BitVecExpr configVarMask,
      ArithExpr configVarLength) {
    return create(address, mask.numSubnetBits(), configVarIp, configVarMask, configVarLength);
  }

  /** Return the longest prefix that contains both input prefixes. */
  public static Prefix longestCommonPrefix(Prefix p1, Prefix p2) {
    if (p1.containsPrefix(p2)) {
      return p1;
    }
    if (p2.containsPrefix(p1)) {
      return p2;
    }
    long l1 = p1.getStartIp().asLong();
    long l2 = p2.getStartIp().asLong();
    long oneAtFirstDifferentBit = Long.highestOneBit(l1 ^ l2);
    int lengthInCommon = MAX_PREFIX_LENGTH - 1 - Long.numberOfTrailingZeros(oneAtFirstDifferentBit);
    return Prefix.create(Ip.create(l1), lengthInCommon);
  }

  @Override
  public int compareTo(Prefix rhs) {
    if (this == rhs) {
      return 0;
    }
    int ret = _ip.compareTo(rhs._ip);
    if (ret != 0) {
      return ret;
    }
    return Integer.compare(_prefixLength, rhs._prefixLength);
  }

  public boolean containsIp(Ip ip) {
    long masked = ip.asLong() & ~wildcardMaskForPrefixLength(_prefixLength);
    return masked == _ip.asLong();
  }

  public boolean containsPrefix(Prefix prefix) {
    return _prefixLength <= prefix._prefixLength && containsIp(prefix._ip);
  }

  @Override
  public boolean equals(@Nullable Object o) {
    if (o == this) {
      return true;
    } else if (!(o instanceof Prefix)) {
      return false;
    }
    Prefix rhs = (Prefix) o;
    return _ip.equals(rhs._ip) && _prefixLength == rhs._prefixLength;
  }

  @Nonnull
  public Ip getEndIp() {
    long networkEnd = _ip.asLong() | wildcardMaskForPrefixLength(_prefixLength);
    return Ip.create(networkEnd);
  }

  public int getPrefixLength() {
    return _prefixLength;
  }

  @Nonnull
  public Ip getPrefixWildcard() {
    long wildcardLong = wildcardMaskForPrefixLength(_prefixLength);
    return Ip.create(wildcardLong);
  }

  @Nonnull
  public Ip getStartIp() {
    return _ip;
  }

  @Override
  public int hashCode() {
    // We want a custom quick implementation, so don't call Objects.hash()
    return 31 + 31 * Long.hashCode(_ip.asLong()) + _prefixLength;
  }

  @Nonnull
  public IpSpace toIpSpace() {
    if (_prefixLength == 0) {
      return UniverseIpSpace.INSTANCE;
    } else if (_prefixLength == MAX_PREFIX_LENGTH) {
      return _ip.toIpSpace();
    }
    return PrefixIpSpace.create(this);
  }

  /**
   * Returns an {@link IpSpace} that contains this prefix except for the network and broadcast
   * addresses, if applicable. Following RFC 3021, the entire {@code /31} is treated as host IP
   * space. A prefix of length {@code /32} is preserved, though may be a degenerate case.
   */
  public IpSpace toHostIpSpace() {
    if (_prefixLength >= Prefix.MAX_PREFIX_LENGTH - 1) {
      return toIpSpace();
    }
    return AclIpSpace.builder()
        .thenRejecting(getStartIp().toIpSpace())
        .thenRejecting(getEndIp().toIpSpace())
        .thenPermitting(toIpSpace())
        .build();
  }

  /**
   * Returns the first ip in the prefix that is not a subnet address. When the prefix is /32 or /31,
   * returns the getStartIp(), otherwise, returns the ip after getStartIp().
   */
  public Ip getFirstHostIp() {
    if (_prefixLength >= Prefix.MAX_PREFIX_LENGTH - 1) {
      return getStartIp();
    } else {
      Ip subnetIp = getStartIp();
      return Ip.create(subnetIp.asLong() + 1);
    }
  }

  /**
   * Returns the last ip in the prefix that is not a broadcast address. When the prefix is /32 or
   * /31, returns the getEndIp(), otherwise, returns the ip before getEndIp().
   */
  public Ip getLastHostIp() {
    if (_prefixLength >= Prefix.MAX_PREFIX_LENGTH - 1) {
      return getEndIp();
    } else {
      Ip broadcastIp = getEndIp();
      return Ip.create(broadcastIp.asLong() - 1);
    }
  }

  @Override
  @JsonValue
  public String toString() {
    return _ip + "/" + _prefixLength;
  }

  /** Add configuration constant - SMT symbolic variable */
  private static int BITVEC_EXPR_SIZE = 32;

  private boolean _enableSmtVariable;
  private String _configVarPrefix;

  private transient BitVecExpr _configVarIp;
  private transient BitVecExpr _configVarMask;
  private transient ArithExpr _configVarLength;

  public void initSmtVariable(Context context, Solver solver, String configVarPrefix) {
    // assert that the prefix is not shared
    if (_enableSmtVariable) {
      throw new BatfishException("Prefix.initSmtVariable: shared object.\n" +
          "Previous configVarPrefix: " + _configVarPrefix + "\n" +
          "Current  configVarPrefix: " + configVarPrefix);
    }

    long prefixIp = _ip.asLong();

    _configVarIp = context.mkBVConst(configVarPrefix + "ip", BITVEC_EXPR_SIZE);
    _configVarMask = context.mkBVConst(configVarPrefix + "mask", BITVEC_EXPR_SIZE);
    _configVarLength = context.mkIntConst(configVarPrefix + "length");

    // add relevant configuration constant constraints
    // original wildcardMask is 0b0000111111111111 (0x0FFF)
    // modified subnetMask is   0b1111000000000000 (0xF000)
    BoolExpr configVarIpConstraint = context.mkEq(
        _configVarIp, context.mkBV(prefixIp, BITVEC_EXPR_SIZE));
    BoolExpr configVarMaskConstraint = context.mkEq(
        _configVarMask, context.mkBV(~(getPrefixWildcard().asLong()), BITVEC_EXPR_SIZE));
    BoolExpr configVarLengthConstraint = context.mkEq(
        _configVarLength, context.mkInt(_prefixLength));
    solver.add(configVarIpConstraint);
    solver.add(configVarMaskConstraint);
    solver.add(configVarLengthConstraint);

    // config the smt variable enable flag to true
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
