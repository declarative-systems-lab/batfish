#!/usr/bin/env python3
"""Generate satisfaction and violation router-level assume-guarantee fragments."""

import ipaddress
import sys
from collections import defaultdict
from pathlib import Path
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from utils import util_keyword
from utils.util_data import (
    BgpRoute,
    ControlForwardingState,
    OspfRoute,
    PeerTables,
    Route,
    RouteAssumptionCase,
    RouteAttributes,
    RouteProtocol,
    RouterLevelAnalysisReport,
    RouterLevelInputs,
    RouterPrefixAnalysis,
    SmtConstraint,
)
from utils.util_file import (
    delete_router_level_outputs,
    load_bgp_peers,
    load_bgp_routes,
    load_data_plane,
    load_history_enums,
    load_hostnames,
    load_interfaces,
    load_model_igp,
    load_overall_attributes,
    load_ospf_peers,
    load_ospf_routes,
    load_target_prefixes,
    load_unused_control_forwarding_variables,
    validate_router_level_inputs,
    write_router_level_analysis_report,
)
from utils.util_log import (
    exit_with_error,
    log_info,
    verbose_info,
)
from utils.util_route_attributes import (
    NoRouteAttributeHandler,
    RouteAttributeHandler,
    build_protocol_handlers,
)
from utils.util_route_community import CommunityEncoder
from utils.util_smt import SmtConstraintBuilder, SmtVariableNamer


# These interfaces do not represent control-forwarding decisions.
_EXCLUDED_ROUTE_INTERFACES = frozenset({"Loopback0", "dynamic"})

# Dataplane sentinel for routes without a resolved peer next hop.
_NULL_NEXTHOP = "null"


class UndeclaredRouteInterfaceError(ValueError):
    """A selected route references an interface absent from 0_interfaces.txt."""


class ControlForwardingAnalyzer:
    """Derive active and inactive forwarding interfaces for selected routes."""

    def __init__(
        self,
        device_interfaces: Dict[str, Set[str]],
        unused_variables: Set[str],
        namer: SmtVariableNamer,
        get_peer_interfaces: Callable[[str, str, RouteProtocol], Set[str]],
    ):
        self.device_interfaces = device_interfaces
        self.unused_variables = unused_variables
        self.namer = namer
        self.get_peer_interfaces = get_peer_interfaces

    def analyze(
        self,
        router: str,
        routes: Iterable[Route],
    ) -> ControlForwardingState:
        route_interfaces = self._route_interfaces(router, routes)
        self._validate_interfaces(router, route_interfaces)

        active_interfaces = {
            interface
            for interface in route_interfaces
            if not self._is_unused(router, interface)
        }
        considered_interfaces = tuple(
            interface
            for interface in sorted(self.device_interfaces.get(router, set()))
            if not self._is_unused(router, interface)
        )
        return ControlForwardingState(
            considered_interfaces=considered_interfaces,
            active_interfaces=frozenset(active_interfaces),
        )

    def _route_interfaces(
        self,
        router: str,
        routes: Iterable[Route],
    ) -> Set[str]:
        interfaces: Set[str] = set()
        for route in routes:
            if route.nexthop_interface not in _EXCLUDED_ROUTE_INTERFACES:
                interfaces.add(route.nexthop_interface)

            protocol = RouteProtocol.from_token(route.protocol)
            if protocol not in (
                RouteProtocol.EBGP,
                RouteProtocol.IBGP,
                RouteProtocol.OSPF,
            ):
                continue
            if not route.nexthop or route.nexthop.lower() == _NULL_NEXTHOP:
                continue
            peer_interfaces = self.get_peer_interfaces(
                router,
                route.nexthop,
                protocol,
            )
            interfaces.update(
                interface
                for interface in peer_interfaces
                if interface not in _EXCLUDED_ROUTE_INTERFACES
            )
        return interfaces

    def _validate_interfaces(self, router: str, interfaces: Set[str]) -> None:
        allowed = self.device_interfaces.get(router, set())
        for interface in interfaces:
            if interface not in allowed:
                raise UndeclaredRouteInterfaceError(
                    f"Best route interface '{interface}' for device '{router}' "
                    f"is not in {util_keyword.INTERFACES_FILE}."
                )

    def _is_unused(self, router: str, interface: str) -> bool:
        variable = self.namer.control_forwarding(router, interface)
        return variable in self.unused_variables


class RouterLevelSubspecAnalyzer:
    """Build peer assumptions and local route/forwarding guarantees."""

    def __init__(self, work_dir: str, verbose_flag: bool = False):
        self.work_dir = Path(work_dir)
        self.verbose_flag = verbose_flag
        self.model_igp = load_model_igp(self.work_dir)
        # model_igp uses variables scoped under the SLICE-MAIN prefix.
        smt_var_prefix = (
            util_keyword.SMT_VAR_MODEL_IGP_PREFIX
            if self.model_igp
            else util_keyword.SMT_VAR_DEFAULT_PREFIX
        )
        self.namer = SmtVariableNamer(smt_var_prefix)
        self.constraint_builder = SmtConstraintBuilder(self.namer)
        self.inputs = RouterLevelInputs()
        self.target_prefix: Optional[str] = None
        self.community_encoder = CommunityEncoder(self)
        self.protocol_handlers: Dict[RouteProtocol, RouteAttributeHandler] = (
            build_protocol_handlers()
        )
        self.no_route_handler = NoRouteAttributeHandler()
        validate_router_level_inputs(self.work_dir)

    def load_inputs(self) -> None:
        """Load the inputs for one analysis run."""
        verbose_info(self.verbose_flag, 'Step 1: Loading input data files...')

        routes = load_data_plane(self.work_dir)
        self.community_encoder.load()
        self.inputs = RouterLevelInputs(
            hostnames=load_hostnames(self.work_dir),
            routes=routes,
            bgp_routes=load_bgp_routes(self.work_dir),
            ospf_routes=load_ospf_routes(self.work_dir),
            overall_attributes=load_overall_attributes(self.work_dir),
            target_prefixes=load_target_prefixes(self.work_dir),
            bgp_peers=load_bgp_peers(self.work_dir),
            ospf_peers=load_ospf_peers(self.work_dir),
            unused_control_forwarding=(
                load_unused_control_forwarding_variables(self.work_dir)
            ),
            history=load_history_enums(self.work_dir),
            device_interfaces=load_interfaces(self.work_dir),
        )
        self._validate_device_inventory()
        self.target_prefix = self._require_one_target_prefix(
            self.inputs.target_prefixes
        )
        self._log_input_summary()

    def _validate_device_inventory(self) -> None:
        """Validate the authoritative hostname inventory used by stage 1."""
        hostnames = self.inputs.hostnames
        if not hostnames:
            raise ValueError(f"No devices found in {util_keyword.HOSTNAMES_FILE}")

        duplicate_hostnames = sorted(
            hostname
            for hostname in set(hostnames)
            if hostnames.count(hostname) > 1
        )
        if duplicate_hostnames:
            raise ValueError(
                f"Duplicate devices in {util_keyword.HOSTNAMES_FILE}: "
                + ", ".join(duplicate_hostnames)
            )

        unknown_route_devices = sorted(
            {route.node for route in self.inputs.routes} - set(hostnames)
        )
        if unknown_route_devices:
            raise ValueError(
                f"Dataplane devices missing from {util_keyword.HOSTNAMES_FILE}: "
                + ", ".join(unknown_route_devices)
            )

    def build_report(self) -> RouterLevelAnalysisReport:
        """Analyze every router for the configured target prefix."""
        if self.target_prefix is None:
            raise RuntimeError('Input data must be loaded before route analysis')

        target_prefix = self.target_prefix
        verbose_info(
            self.verbose_flag,
            f'Step 2: Analyzing routes for target prefix: {target_prefix}',
        )
        verbose_info(
            self.verbose_flag,
            f'\n=== Analyzing destination: {target_prefix} ===',
        )

        control_analyzer = ControlForwardingAnalyzer(
            device_interfaces=self.inputs.device_interfaces,
            unused_variables=self.inputs.unused_control_forwarding,
            namer=self.namer,
            get_peer_interfaces=self._require_peer_interfaces,
        )
        routers = {}
        for device in sorted(self.inputs.hostnames):
            routers[device] = self._analyze_device_for_prefix(
                device, target_prefix, control_analyzer
            )

        peer_control_variables = {
            device: self._get_peer_control_variables(device)
            for device in routers
        }
        missing_peers = sorted(
            (device, peer)
            for device, peers in peer_control_variables.items()
            for peer in peers
            if peer not in routers
        )
        if missing_peers:
            relationships = ", ".join(
                f"{device}->{peer}" for device, peer in missing_peers
            )
            raise ValueError(
                f"Routing peers missing from {util_keyword.HOSTNAMES_FILE}: "
                f"{relationships}"
            )

        # Each fragment assumes all peer best routes and boundary decisions.
        # Its guarantee is the expected or violated local route/forwarding state.
        return RouterLevelAnalysisReport(
            target_prefix=target_prefix,
            routers=routers,
            # Peer decisions are boundary assumptions for each local router.
            peer_control_variables=peer_control_variables,
        )

    def _log_input_summary(self) -> None:
        inputs = self.inputs

        verbose_info(self.verbose_flag, f'  -> Loaded {len(inputs.routes)} routes')
        verbose_info(
            self.verbose_flag,
            f'  -> Loaded '
            f'{sum(len(routes) for routes in inputs.bgp_routes.values())} '
            f'BGP routes',
        )
        verbose_info(
            self.verbose_flag,
            f'  -> Loaded '
            f'{sum(len(routes) for routes in inputs.ospf_routes.values())} '
            f'OSPF routes',
        )
        verbose_info(
            self.verbose_flag,
            f'  -> Loaded OVERALL_BEST attributes for '
            f'{len(inputs.overall_attributes)} devices',
        )
        verbose_info(
            self.verbose_flag,
            f'  -> Loaded {len(inputs.target_prefixes)} destination IPs: '
            f'{inputs.target_prefixes}',
        )
        verbose_info(
            self.verbose_flag,
            f'  -> Loaded {len(inputs.bgp_peers.interfaces)} BGP peer mappings',
        )
        verbose_info(
            self.verbose_flag,
            f'  -> Loaded {len(inputs.ospf_peers.interfaces)} OSPF peer mappings',
        )
        verbose_info(
            self.verbose_flag,
            f'  -> Loaded history enums for {len(inputs.history.enums)} devices',
        )
        self.community_encoder.log_load_summary()
        verbose_info(self.verbose_flag, '  -> All data loaded successfully')

    @classmethod
    def _require_one_target_prefix(cls, target_prefixes: List[str]) -> str:
        if len(target_prefixes) != 1:
            raise ValueError(
                'Exactly one target prefix is currently supported; '
                f'found {len(target_prefixes)} in {util_keyword.DST_IPS_FILE}'
            )
        target_prefix = target_prefixes[0]
        cls._parse_ipv4_network(
            target_prefix,
            source=util_keyword.DST_IPS_FILE,
        )
        return target_prefix

    @staticmethod
    def _parse_ipv4_network(
        prefix: str,
        *,
        source: str,
    ) -> ipaddress.IPv4Network:
        candidate = prefix if '/' in prefix else f'{prefix}/32'
        try:
            network = ipaddress.ip_network(candidate, strict=False)
        except ValueError as error:
            raise ValueError(
                f"Invalid IPv4 prefix '{prefix}' in {source}"
            ) from error
        if not isinstance(network, ipaddress.IPv4Network):
            raise ValueError(
                f"Unsupported non-IPv4 prefix '{prefix}' in {source}"
            )
        return network

    def get_history_value(self, device: str, protocol: str) -> Optional[str]:
        """Return a protocol history enum as an SMT bit-vector literal."""
        enum_value = self.inputs.history.enums.get(device, {}).get(protocol.upper())
        if enum_value is None:
            return None
        # History defaults to two bits when no device-specific width is recorded.
        bit_width = self.inputs.history.bit_widths.get(device, 2)
        return f"#b{format(enum_value, f'0{bit_width}b')}"

    def get_overall_attributes(self, device: str) -> Set[str]:
        """Return attributes referenced by this device's OVERALL_BEST route."""
        return set(self.inputs.overall_attributes.get(device, frozenset()))

    def get_all_bgp_info(
        self,
        device: str,
        network: str,
        protocol: Optional[RouteProtocol] = None,
    ) -> List[BgpRoute]:
        routes = self.inputs.bgp_routes.get(f'{device}_{network}', [])
        if protocol is None:
            return routes
        return [
            route
            for route in routes
            if RouteProtocol.from_token(route.protocol) is protocol
        ]

    def _get_selected_bgp_routes(
        self,
        device: str,
        route: Route,
        protocol: RouteProtocol,
    ) -> List[BgpRoute]:
        bgp_routes = [
            bgp_route
            for bgp_route in self.get_all_bgp_info(
                device,
                route.network,
                protocol,
            )
            if bgp_route.next_hop == route.nexthop_ip
        ]
        if not bgp_routes:
            raise ValueError(
                f"Missing {protocol.value} route in "
                f"{util_keyword.BGP_ROUTES_FILE} for selected route on "
                f"device '{device}', network '{route.network}', next hop "
                f"'{route.nexthop_ip}'"
            )
        return bgp_routes

    def get_selected_bgp_info(
        self,
        device: str,
        routes: List[Route],
        protocol: RouteProtocol,
    ) -> List[BgpRoute]:
        """Resolve selected data-plane routes to exact supplemental BGP rows."""
        selected = []
        seen = set()
        for route in routes:
            for bgp_route in self._get_selected_bgp_routes(
                device, route, protocol
            ):
                key = (
                    bgp_route.node,
                    bgp_route.vrf,
                    bgp_route.network,
                    bgp_route.protocol,
                    bgp_route.next_hop,
                    tuple(bgp_route.aspath),
                    tuple(bgp_route.communities),
                    bgp_route.local_pref,
                    bgp_route.med,
                    bgp_route.weight,
                )
                if key not in seen:
                    seen.add(key)
                    selected.append(bgp_route)
        return selected

    def get_all_ospf_info(
        self,
        device: str,
        network: str,
    ) -> List[OspfRoute]:
        return self.inputs.ospf_routes.get(f'{device}_{network}', [])

    def _peer_table(self, protocol: RouteProtocol) -> PeerTables:
        if protocol is RouteProtocol.OSPF:
            return self.inputs.ospf_peers
        if protocol in (RouteProtocol.EBGP, RouteProtocol.IBGP):
            return self.inputs.bgp_peers
        raise ValueError(f"Protocol '{protocol.value}' does not use peer mappings")

    def _require_peer_interfaces(
        self,
        device: str,
        peer_hostname: str,
        protocol: RouteProtocol,
    ) -> Set[str]:
        interfaces = self._peer_table(protocol).interfaces_for(
            device, peer_hostname
        )
        if interfaces:
            return interfaces
        source_file = (
            util_keyword.OSPF_PEERS_FILE
            if protocol is RouteProtocol.OSPF
            else util_keyword.BGP_PEERS_FILE
        )
        raise ValueError(
            f"Missing {protocol.value} peer interface in {source_file}: "
            f"{device}->{peer_hostname}"
        )

    def _get_peer_control_variables(
        self,
        device: str,
    ) -> Dict[str, Tuple[str, ...]]:
        """Return peer forwarding variables used as boundary constraints."""
        interfaces_by_peer: Dict[str, Set[str]] = defaultdict(set)
        peer_tables = (
            (util_keyword.BGP_PEERS_FILE, self.inputs.bgp_peers),
            (util_keyword.OSPF_PEERS_FILE, self.inputs.ospf_peers),
        )
        for source_file, peer_table in peer_tables:
            for peer in sorted(peer_table.peers(device)):
                reverse_interfaces = peer_table.interfaces_for(peer, device)
                if not reverse_interfaces:
                    raise ValueError(
                        f"Missing reverse peer interface in {source_file}: "
                        f"{peer}->{device}"
                    )
                interfaces_by_peer[peer].update(reverse_interfaces)

        return {
            peer: tuple(
                self.namer.control_forwarding(peer, interface)
                for interface in sorted(interfaces)
            )
            for peer, interfaces in sorted(interfaces_by_peer.items())
        }

    def _get_ebgp_neighbors(self, device: str) -> Dict[str, Set[int]]:
        """Return eBGP neighbors and their remote session AS numbers."""
        bgp_peers = self.inputs.bgp_peers
        peer_names = sorted(bgp_peers.peers(device))
        if not peer_names:
            raise ValueError(
                f"No BGP peers found for eBGP route on device '{device}'"
            )

        neighbors = {}
        for peer in peer_names:
            session_as = bgp_peers.autonomous_systems.get((device, peer))
            if not session_as:
                raise ValueError(
                    f"Missing session AS metadata in "
                    f"{util_keyword.BGP_PEERS_FILE}: "
                    f"{device}->{peer}"
                )
            remote_as_numbers = bgp_peers.ebgp_remote_as_numbers(device, peer)
            if remote_as_numbers:
                neighbors[peer] = remote_as_numbers
        if not neighbors:
            raise ValueError(
                f"No eBGP peers found for eBGP route on device '{device}'"
            )
        return neighbors

    def generate_community_variables(
        self,
        device: str,
        selected_routes: List[Route],
        negated_mode: bool = False,
    ) -> Union[Dict[str, str], str, None]:
        return self.community_encoder.generate_community_variables(
            device, selected_routes, negated_mode
        )

    def generate_community_variables_for_no_routes(
        self, device: str
    ) -> Dict[str, str]:
        return self.community_encoder.generate_community_variables_for_no_routes(
            device
        )

    def _find_best_routes(self, device: str, target_prefix: str) -> List[Route]:
        """Select routes using longest-prefix match, then administrative distance."""
        device_routes = [
            route
            for route in self.inputs.routes
            if route.node == device
            and route.protocol.lower() != util_keyword.PROTOCOL_LOCAL
            and self._route_matches_target(route, target_prefix)
        ]
        if not device_routes:
            return []

        maximum_prefix_length = max(
            route.prefix_length for route in device_routes
        )
        candidate_routes = [
            route
            for route in device_routes
            if route.prefix_length == maximum_prefix_length
        ]
        if len(candidate_routes) == 1:
            return candidate_routes

        minimum_ad = min(route.ad for route in candidate_routes)
        return [
            route
            for route in candidate_routes
            if route.ad == minimum_ad
        ]

    @classmethod
    def _route_matches_target(cls, route: Route, target_prefix: str) -> bool:
        route_network = cls._parse_ipv4_network(
            route.network,
            source=(
                f"{util_keyword.DATA_PLANE_FILE} route for device "
                f"'{route.node}'"
            ),
        )
        destination_network = cls._parse_ipv4_network(
            target_prefix,
            source=util_keyword.DST_IPS_FILE,
        )
        return destination_network.subnet_of(route_network)

    def _analyze_device_for_prefix(
        self,
        device: str,
        target_prefix: str,
        control_analyzer: ControlForwardingAnalyzer,
    ) -> RouterPrefixAnalysis:
        verbose_info(self.verbose_flag, f'\nAnalyzing device: {device}')
        selected_routes = self._group_routes_by_interface(
            self._find_best_routes(device, target_prefix)
        )
        self._log_selected_routes(device, target_prefix, selected_routes)

        protocol = (
            RouteProtocol.from_token(selected_routes[0].protocol)
            if selected_routes
            else None
        )
        selected_protocols = {
            RouteProtocol.from_token(route.protocol)
            for route in selected_routes
        }
        if len(selected_protocols) > 1:
            raise ValueError(
                f"Best routes on device '{device}' use multiple protocols: "
                + ", ".join(sorted(item.value for item in selected_protocols))
            )
        attributes = self._analyze_protocol_attributes(
            device, protocol, selected_routes
        )
        control_state = control_analyzer.analyze(device, selected_routes)

        normal_route_constraints = (
            self.constraint_builder.normal_route_constraints(
                device, attributes
            )
        )
        negated_route_constraints = (
            self.constraint_builder.negated_route_constraints(
                device, attributes
            )
        )
        prefix_bounds = (
            self.constraint_builder.prefix_length_bounds(
                device, self._maximum_target_prefix_length()
            )
            if attributes.prefix_length is not None
            else ()
        )
        route_assumption_cases = self._build_route_assumption_cases(
            device,
            protocol,
            selected_routes,
            normal_route_constraints,
        )

        return RouterPrefixAnalysis(
            router=device,
            target_prefix=target_prefix,
            protocol=protocol,
            selected_routes=tuple(selected_routes),
            route_attributes=attributes,
            control_forwarding=control_state,
            normal_route_constraints=normal_route_constraints,
            negated_route_constraints=negated_route_constraints,
            normal_control_constraints=(
                self.constraint_builder.normal_control_constraints(
                    device, control_state
                )
            ),
            negated_control_constraints=(
                self.constraint_builder.negated_control_constraints(
                    device, control_state
                )
            ),
            prefix_length_bounds=prefix_bounds,
            route_assumption_cases=route_assumption_cases,
        )

    def _build_route_assumption_cases(
        self,
        device: str,
        protocol: Optional[RouteProtocol],
        selected_routes: List[Route],
        aggregate_constraints: Tuple[SmtConstraint, ...],
    ) -> Tuple[RouteAssumptionCase, ...]:
        """Keep each BGP route coupled to its own loop-prevention origins."""
        if protocol not in (RouteProtocol.EBGP, RouteProtocol.IBGP):
            return (
                RouteAssumptionCase(
                    route_constraints=aggregate_constraints,
                ),
            )

        cases = []
        seen = set()
        for route in selected_routes:
            attributes = self._analyze_protocol_attributes(
                device, protocol, [route]
            )
            constraints = self.constraint_builder.normal_route_constraints(
                device, attributes
            )
            origins = tuple(self._compute_route_from(device, [route]))
            key = (
                tuple(item.expression for item in constraints),
                origins,
            )
            if key in seen:
                continue
            seen.add(key)
            cases.append(
                RouteAssumptionCase(
                    route_constraints=constraints,
                    route_origins=origins,
                )
            )
        return tuple(cases)

    def _analyze_protocol_attributes(
        self,
        device: str,
        protocol: Optional[RouteProtocol],
        selected_routes: List[Route],
    ) -> RouteAttributes:
        if protocol is None:
            return self.no_route_handler.analyze(self, device)
        handler = self.protocol_handlers.get(protocol)
        if handler is None:
            raise ValueError(
                f"Unsupported best-route protocol "
                f"'{selected_routes[0].protocol}' for device '{device}'"
            )
        return handler.analyze(self, device, selected_routes)

    def _maximum_target_prefix_length(self) -> int:
        if self.target_prefix is None:
            raise RuntimeError('Input data must be loaded before route analysis')
        return self._parse_ipv4_network(
            self.target_prefix,
            source=util_keyword.DST_IPS_FILE,
        ).prefixlen

    def _compute_route_from(
        self, device: str, selected_routes: List[Route]
    ) -> List[str]:
        """Find eBGP peers that would send a selected route back to its origin."""
        if not selected_routes:
            return []
        if (
            RouteProtocol.from_token(selected_routes[0].protocol)
            is not RouteProtocol.EBGP
        ):
            return []

        as_path = {
            as_number
            for route in selected_routes
            for bgp_route in self._get_selected_bgp_routes(
                device,
                route,
                RouteProtocol.EBGP,
            )
            for as_number in bgp_route.aspath
        }
        return [
            neighbor
            for neighbor, remote_as_numbers in self._get_ebgp_neighbors(
                device
            ).items()
            if remote_as_numbers & as_path
        ]

    @staticmethod
    def _group_routes_by_interface(routes: List[Route]) -> List[Route]:
        """Keep ECMP routes grouped by their outgoing interface."""
        routes_by_interface: Dict[str, List[Route]] = defaultdict(list)
        for route in routes:
            routes_by_interface[route.nexthop_interface].append(route)
        return [
            route
            for interface_routes in routes_by_interface.values()
            for route in interface_routes
        ]

    def _log_selected_routes(
        self, device: str, target_prefix: str, routes: List[Route]
    ) -> None:
        if not routes:
            verbose_info(
                self.verbose_flag,
                f'  No routes found for destination {target_prefix}',
            )
            return

        verbose_info(
            self.verbose_flag,
            f'  Found {len(routes)} ECMP route(s):',
        )
        for route_index, route in enumerate(routes, 1):
            verbose_info(
                self.verbose_flag,
                f'    Route {route_index}: {route.network} via '
                f'{route.protocol} (AD={route.ad})'
            )
            if RouteProtocol.from_token(route.protocol) is not RouteProtocol.EBGP:
                continue
            bgp_routes = self.get_all_bgp_info(
                device,
                route.network,
                RouteProtocol.EBGP,
            )
            for bgp_index, bgp_info in enumerate(bgp_routes, 1):
                if len(bgp_routes) > 1:
                    verbose_info(
                        self.verbose_flag,
                        f'      BGP Route {bgp_index} AS path: {bgp_info.aspath} '
                        f'(length={bgp_info.aspath_length})'
                    )
                else:
                    verbose_info(
                        self.verbose_flag,
                        f'      BGP AS path: {bgp_info.aspath} '
                        f'(length={bgp_info.aspath_length})'
                    )
                if bgp_info.communities:
                    verbose_info(
                        self.verbose_flag,
                        f'      BGP Communities: {bgp_info.communities}',
                    )


def _parse_cli_args(
    args: Sequence[str],
) -> Tuple[bool, bool, Optional[str]]:
    verbose_flag = False
    delete_flag = False
    work_dir = None
    for arg in args:
        if arg == '-v':
            verbose_flag = True
        elif arg == '-d':
            delete_flag = True
        elif arg.startswith('-'):
            raise ValueError(f"Unknown option: {arg}")
        elif work_dir is not None:
            raise ValueError("Multiple work directories specified")
        else:
            work_dir = arg
    return verbose_flag, delete_flag, work_dir


def _print_usage() -> None:
    print("Usage: python 1_router_level_subspec.py [-v] [-d] <work_directory>")
    print("Options:")
    print("  -v     Verbose mode: Show detailed INFO logs")
    print("         Without -v: Only show WARNING/ERROR logs and completion status")
    print("  -d     Delete intermediate output files before running, then exit")
    print("  -h, --help  Show this help message")
    print("")
    print("Example: python 1_router_level_subspec.py smt_output_0001")
    print("         python 1_router_level_subspec.py -v smt_output_0001")
    print("         python 1_router_level_subspec.py -d smt_output_0001")


def _delete_outputs(work_dir: Path) -> None:
    """Delete files produced by stage 1 and report the result."""
    deleted_paths = delete_router_level_outputs(work_dir)
    if not deleted_paths:
        log_info("No intermediate files found to delete.")
        return
    for deleted_path in deleted_paths:
        log_info("Deleted intermediate output: %s", deleted_path)


def _run_router_level_subspec(work_dir: Path, verbose_flag: bool) -> None:
    """Build and write router-level functional subspecifications."""
    router_level_analyzer = RouterLevelSubspecAnalyzer(
        str(work_dir),
        verbose_flag=verbose_flag,
    )
    router_level_analyzer.load_inputs()
    report = router_level_analyzer.build_report()
    write_router_level_analysis_report(router_level_analyzer.work_dir, report)


def main(args: Optional[Sequence[str]] = None) -> None:
    """Run the stage-1 router-level functional subspecification pipeline."""
    cli_args = list(sys.argv[1:] if args is None else args)
    if any(argument in ("-h", "--help") for argument in cli_args):
        _print_usage()
        return
    if not cli_args:
        _print_usage()
        exit_with_error("Work directory is required")

    try:
        (
            verbose_flag,
            delete_flag,
            work_dir,
        ) = _parse_cli_args(cli_args)
    except ValueError as error:
        exit_with_error(f"Error: {error}")

    if not work_dir:
        _print_usage()
        exit_with_error("Work directory is required")

    work_dir_path = Path(work_dir)
    if not work_dir_path.is_dir():
        _print_usage()
        exit_with_error(
            f"Work directory does not exist or is not a directory: "
            f"{work_dir_path}"
        )

    if delete_flag:
        _delete_outputs(work_dir_path)
        return

    try:
        _run_router_level_subspec(work_dir_path, verbose_flag)
    except Exception as error:
        exit_with_error(f"Error: {error}")

    if not verbose_flag:
        print("[✓] Completed: Router-Level Functional Subspecification")


if __name__ == "__main__":
    main()
