package org.batfish.simulation;

import static org.junit.Assert.assertEquals;

import com.google.common.collect.ImmutableList;
import org.batfish.datamodel.Configuration;
import org.batfish.datamodel.ConfigurationFormat;
import org.batfish.datamodel.ExprAclLine;
import org.batfish.datamodel.HeaderSpace;
import org.batfish.datamodel.Ip;
import org.batfish.datamodel.IpAccessList;
import org.batfish.datamodel.IpProtocol;
import org.batfish.datamodel.IpWildcard;
import org.batfish.datamodel.acl.MatchHeaderSpace;
import org.batfish.datamodel.acl.PermittedByAcl;
import org.junit.Test;

public final class Ipv4PartitionTest {
  @Test
  public void testNonContiguousWildcard() {
    Configuration c = new Configuration("node", ConfigurationFormat.CISCO_IOS);
    IpWildcard wildcard = IpWildcard.parse("10.0.0.0:0.0.0.5");
    IpAccessList acl =
        IpAccessList.builder()
            .setName("filter")
            .setOwner(c)
            .setLines(
                ImmutableList.of(
                    ExprAclLine.accepting(
                        new MatchHeaderSpace(
                            HeaderSpace.builder().setSrcIps(wildcard.toIpSpace()).build()))))
            .build();
    Ipv4Partition partition = new Ipv4Partition(c);
    partition.acl(acl);
    Long[] bounds = partition.sources();
    assertEquals(6, bounds.length);
    for (int i = 0; i < 256; i++) {
      long ip = Ip.parse("10.0.0.0").asLong() + i;
      for (int j = 0; j < bounds.length - 1; j++) {
        if (ip >= bounds[j] && ip < bounds[j + 1]) {
          assertEquals(
              wildcard.containsIp(Ip.create(ip)), wildcard.containsIp(Ip.create(bounds[j])));
          assertEquals(
              wildcard.containsIp(Ip.create(ip)),
              wildcard.containsIp(Ip.create(bounds[j + 1] - 1)));
        }
      }
    }
    assertEquals(Long.valueOf(0), bounds[0]);
    assertEquals(Long.valueOf(1L << 32), bounds[bounds.length - 1]);
  }

  @Test(expected = UnsupportedOperationException.class)
  public void testProtocolMatchIsNotSilentlyApproximated() {
    Configuration c = new Configuration("node", ConfigurationFormat.CISCO_IOS);
    IpAccessList acl =
        IpAccessList.builder()
            .setName("filter")
            .setOwner(c)
            .setLines(
                ImmutableList.of(
                    ExprAclLine.accepting(
                        new MatchHeaderSpace(
                            HeaderSpace.builder().setIpProtocols(IpProtocol.TCP).build()))))
            .build();
    new Ipv4Partition(c).acl(acl);
  }

  @Test(expected = IllegalArgumentException.class)
  public void testCyclicAclReference() {
    Configuration c = new Configuration("node", ConfigurationFormat.CISCO_IOS);
    IpAccessList acl =
        IpAccessList.builder()
            .setName("filter")
            .setOwner(c)
            .setLines(ImmutableList.of(ExprAclLine.accepting(new PermittedByAcl("filter"))))
            .build();
    new Ipv4Partition(c).acl(acl);
  }
}
