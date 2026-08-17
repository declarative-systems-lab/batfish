#!/usr/bin/env python3
"""Shared input and intermediate data structures for the pipeline."""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, FrozenSet, List, Mapping, Optional, Set, Tuple, Union

from utils import util_keyword


# Router-level input models.


class RouteProtocol(str, Enum):
    """Canonical route protocols supported by router-level analysis."""

    CONNECTED = util_keyword.PROTOCOL_CONNECTED
    STATIC = util_keyword.PROTOCOL_STATIC
    EBGP = util_keyword.PROTOCOL_EBGP
    IBGP = util_keyword.PROTOCOL_IBGP
    OSPF = util_keyword.PROTOCOL_OSPF
    UNKNOWN = "unknown"

    @classmethod
    def from_token(cls, token: str) -> "RouteProtocol":
        normalized = token.lower()
        if normalized in (util_keyword.PROTOCOL_BGP, util_keyword.PROTOCOL_EBGP):
            return cls.EBGP
        if normalized.startswith(util_keyword.PROTOCOL_OSPF):
            return cls.OSPF
        try:
            return cls(normalized)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class Route:
    """One route from the simulated data-plane table."""

    node: str
    vrf: str
    network: str
    protocol: str
    nexthop_ip: str
    nexthop_interface: str
    nexthop: str
    metric: int
    ad: int
    tag: str

    @property
    def prefix_length(self) -> int:
        """Return the network's CIDR prefix length."""
        if "/" in self.network:
            return int(self.network.split("/")[1])
        return 32


@dataclass
class BgpRoute:
    """One route from the simulated BGP route table."""

    node: str
    vrf: str
    network: str
    protocol: str
    next_hop: str
    aspath: List[int]
    communities: List[str]
    local_pref: Optional[int] = None
    med: Optional[int] = None
    weight: Optional[int] = None

    @property
    def aspath_length(self) -> int:
        """Return the number of ASes in the path."""
        return len(self.aspath)


@dataclass
class OspfRoute:
    """One route from the simulated OSPF route table."""

    node: str
    vrf: str
    network: str
    route_type: str
    area: Optional[int]
    metric: int
    path_cost: int
    next_hop: str


PeerKey = Tuple[str, str]


@dataclass
class PeerTables:
    """Protocol-independent directed peer-interface mappings."""

    interfaces: Dict[PeerKey, Set[str]] = field(default_factory=dict)

    def interfaces_for(self, device: str, peer: str) -> Set[str]:
        return self.interfaces.get((device, peer), set())

    def peers(self, device: str) -> Set[str]:
        return {
            peer
            for (local_device, peer) in self.interfaces
            if local_device == device
        }


@dataclass
class BgpPeerTables(PeerTables):
    """Directed BGP peer interfaces and session AS metadata."""

    autonomous_systems: Dict[PeerKey, Set[Tuple[int, int]]] = field(
        default_factory=dict
    )

    def ebgp_remote_as_numbers(self, device: str, peer: str) -> Set[int]:
        """Return remote AS numbers for eBGP sessions from device to peer."""
        return {
            remote_as
            for local_as, remote_as in self.autonomous_systems.get(
                (device, peer), set()
            )
            if local_as != remote_as
        }


@dataclass
class OspfPeerTables(PeerTables):
    """OSPF peer interfaces."""


@dataclass
class HistoryEnumTables:
    """History enum values and bit widths used by SMT route attributes."""

    # Per-device protocol-history values and their SMT enum widths.
    enums: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    bit_widths: Dict[str, int] = field(default_factory=dict)


@dataclass
class RouterLevelInputs:
    """All input tables required by router-level subspec analysis."""

    hostnames: List[str] = field(default_factory=list)
    routes: List[Route] = field(default_factory=list)
    bgp_routes: Dict[str, List[BgpRoute]] = field(default_factory=dict)
    ospf_routes: Dict[str, List[OspfRoute]] = field(default_factory=dict)
    overall_attributes: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    target_prefixes: List[str] = field(default_factory=list)
    bgp_peers: BgpPeerTables = field(default_factory=BgpPeerTables)
    ospf_peers: OspfPeerTables = field(default_factory=OspfPeerTables)
    unused_control_forwarding: Set[str] = field(default_factory=set)
    history: HistoryEnumTables = field(default_factory=HistoryEnumTables)
    device_interfaces: Dict[str, Set[str]] = field(default_factory=dict)


# Router-level analysis results.


@dataclass(frozen=True)
class RouteAttributes:
    """Protocol-derived OVERALL_BEST attributes before SMT rendering."""

    protocol: Optional[RouteProtocol]
    permitted: Optional[bool]
    prefix_length: Optional[Union[int, str]]
    admin_dist: Optional[Union[int, str]] = None
    local_pref: Optional[Union[int, str]] = None
    metric: Optional[Union[int, str]] = None
    med: Optional[Union[int, str]] = None
    ospf_area: Optional[Union[int, str]] = None
    ospf_type: Optional[str] = None
    history: Optional[str] = None
    communities: Mapping[str, str] = field(default_factory=dict)
    negated_community_constraint: Optional[str] = None


@dataclass(frozen=True)
class ControlForwardingState:
    """Expected forwarding interfaces for one router and target prefix."""

    considered_interfaces: Tuple[str, ...]
    active_interfaces: FrozenSet[str]


@dataclass(frozen=True)
class SmtConstraint:
    """An SMT expression rendered as one top-level assertion."""

    expression: str

    def render(self) -> str:
        return f"(assert {self.expression})"


@dataclass(frozen=True)
class RouteAssumptionCase:
    """One peer-route alternative and its BGP loop-prevention origins."""

    route_constraints: Tuple[SmtConstraint, ...]
    route_origins: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RouterPrefixAnalysis:
    """Complete typed result for one router and one target prefix."""

    router: str
    target_prefix: str
    protocol: Optional[RouteProtocol]
    selected_routes: Tuple[Route, ...]
    route_attributes: RouteAttributes
    control_forwarding: ControlForwardingState
    normal_route_constraints: Tuple[SmtConstraint, ...]
    negated_route_constraints: Tuple[SmtConstraint, ...]
    normal_control_constraints: Tuple[SmtConstraint, ...]
    negated_control_constraints: Tuple[SmtConstraint, ...]
    prefix_length_bounds: Tuple[SmtConstraint, ...]
    route_assumption_cases: Tuple[RouteAssumptionCase, ...]


@dataclass(frozen=True)
class RouterLevelAnalysisReport:
    """All router analyses for the supported single target prefix."""

    target_prefix: str
    routers: Mapping[str, RouterPrefixAnalysis]
    # Per-device, per-peer boundary CONTROL-FORWARDING variables.
    peer_control_variables: Mapping[
        str, Mapping[str, Tuple[str, ...]]
    ] = field(default_factory=dict)


# Router-local encoding state.


@dataclass
class RouterLocalEncodingState:
    """Mutable indexes used while constructing router-local SMT encodings."""

    declarations_by_variable: Dict[str, str] = field(default_factory=dict)
    source_assertions: List[str] = field(default_factory=list)
    assertions_by_router: Dict[str, Set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    route_dependencies: Dict[str, Set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    config_dependencies: Dict[str, Set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    failure_dependencies: Dict[str, Set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    ssa_dependencies: Dict[str, Set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    common_assertions: Set[str] = field(default_factory=set)
    unhandled_assertions: List[str] = field(default_factory=list)


# Subspecification models.


@dataclass(frozen=True)
class ConfigVariable:
    """One active ``Config_*`` equality discovered in an SMT file."""

    name: str
    value: str
    line_number: int
    file_path: str


@dataclass(frozen=True)
class ConfigVariablePair:
    """An IP/mask variable pair that must be processed together."""

    ip_var: ConfigVariable
    mask_var: ConfigVariable
    base_name: str


@dataclass(frozen=True)
class LineLevelConfigGroup:
    """Config variables belonging to the same configuration line."""

    device: str
    line_id: str
    config_variables: List[ConfigVariable]
    line_prefix: str


@dataclass
class SubspecDirectoryLayout:
    """Stage-specific output and intermediate directories for a simplifier."""

    output_dir: Path
    metadata_dir: Path
    field_intermediate_dir: Path
    line_intermediate_dir: Path
    temporary_directory: Optional[TemporaryDirectory] = None


@dataclass(frozen=True)
class SubspecCliOptions:
    """Normalized command-line options shared by subspec simplifier scripts."""

    work_dir: Path
    delete_outputs: bool = False
    field_level_only: bool = False
    line_level_only: bool = False
    verbose: bool = False
    enable_community: bool = False
    device_filter: Optional[str] = None
    joint_multi_location: bool = False
    from_line_subspec: bool = False


# Internet2 refinement results.


@dataclass(frozen=True)
class Internet2PatchSummary:
    """Summary of EXPORT_ENV patches applied to violation-check encodings."""

    processed_files: int = 0
    inserted_assertions: int = 0
    skipped_files: int = 0
    errors: int = 0


@dataclass(frozen=True)
class Internet2ReconstructionResult:
    """Result of refining one router's assume-guarantee constraints."""

    changed_values: int
    updated_variables: Tuple[str, ...]
    matched_variables: int
    total_variables: int
    missing_variables: Tuple[str, ...]
