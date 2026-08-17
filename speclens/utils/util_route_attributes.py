#!/usr/bin/env python3
"""Build protocol-specific route attributes from dynamic OVERALL_BEST fields."""

from dataclasses import dataclass
from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Set,
    Tuple,
    Union,
)

from utils import util_keyword
from utils.util_data import BgpRoute, OspfRoute, Route, RouteAttributes, RouteProtocol
from utils.util_log import log_warning


AttributeValue = Union[int, str]
CommunityResult = Union[Dict[str, str], str, None]


class RouteAttributeContext(Protocol):
    """Services supplied by router-level analysis to attribute handlers."""

    def get_all_bgp_info(
        self,
        device: str,
        network: str,
        protocol: Optional[RouteProtocol] = None,
    ) -> List[BgpRoute]: ...

    def get_selected_bgp_info(
        self,
        device: str,
        routes: List[Route],
        protocol: RouteProtocol,
    ) -> List[BgpRoute]: ...

    def get_all_ospf_info(
        self,
        device: str,
        network: str,
    ) -> List[OspfRoute]: ...

    def get_history_value(self, device: str, protocol: str) -> Optional[str]: ...

    def get_overall_attributes(self, device: str) -> Set[str]: ...

    def generate_community_variables(
        self,
        device: str,
        routes: List[Route],
        negated_mode: bool = False,
    ) -> CommunityResult: ...

    def generate_community_variables_for_no_routes(
        self,
        device: str,
    ) -> Dict[str, str]: ...


class RouteAttributeHandler(Protocol):
    """Construct typed OVERALL_BEST attributes for selected routes."""

    def analyze(
        self,
        context: RouteAttributeContext,
        device: str,
        routes: List[Route],
    ) -> RouteAttributes: ...


def _requested_attributes(
    context: RouteAttributeContext,
    device: str,
    protocol: RouteProtocol,
) -> Dict[str, bool]:
    policy = util_keyword.OVERALL_BEST_ATTRIBUTES_BY_PROTOCOL.get(
        protocol.value, {}
    )
    used = context.get_overall_attributes(device)
    return {
        attribute: from_file
        for attribute, from_file in policy.items()
        if attribute in used
    }


def _unique_value(
    values: Iterable[AttributeValue],
    *,
    device: str,
    protocol: RouteProtocol,
    attribute: str,
    source_file: str,
) -> Optional[AttributeValue]:
    unique = set(values)
    if not unique:
        return None
    if len(unique) == 1:
        return next(iter(unique))
    log_warning(
        "Conflicting %s values for %s route on device '%s' in %s: %s",
        attribute,
        protocol.value,
        device,
        source_file,
        sorted(unique, key=str),
    )
    raise ValueError(
        f"Ambiguous {attribute} for {protocol.value} route on device '{device}'"
    )


@dataclass(frozen=True)
class _AttributeResolver:
    """Resolve requested attributes from parsed values or protocol defaults."""

    context: RouteAttributeContext
    device: str
    protocol: RouteProtocol
    requested: Mapping[str, bool]

    @classmethod
    def create(
        cls,
        context: RouteAttributeContext,
        device: str,
        protocol: RouteProtocol,
    ) -> "_AttributeResolver":
        return cls(
            context=context,
            device=device,
            protocol=protocol,
            requested=_requested_attributes(context, device, protocol),
        )

    def parse_unique(
        self,
        attribute: str,
        values: Iterable[AttributeValue],
        *,
        source_file: str,
    ) -> Optional[AttributeValue]:
        if not self.requested.get(attribute, False):
            return None
        return _unique_value(
            values,
            device=self.device,
            protocol=self.protocol,
            attribute=attribute,
            source_file=source_file,
        )

    def resolve(
        self,
        attribute: str,
        parsed_value: Optional[AttributeValue],
        default_value: Optional[str],
        *,
        source_file: str,
    ) -> Optional[AttributeValue]:
        from_file = self.requested.get(attribute)
        if from_file is None:
            return None
        value = parsed_value if from_file else default_value
        if value is not None:
            return value
        log_warning(
            "Cannot construct %s for %s route on device '%s' from %s",
            attribute,
            self.protocol.value,
            self.device,
            source_file if from_file else "the configured default",
        )
        raise ValueError(
            f"Missing {attribute} for {self.protocol.value} route on "
            f"device '{self.device}'"
        )

    def communities(
        self,
        routes: List[Route],
    ) -> Tuple[Dict[str, str], Optional[str]]:
        attribute = util_keyword.ATTR_COMMUNITY
        if attribute not in self.requested:
            return {}, None
        source_routes = routes if self.requested[attribute] else []
        normal = self.context.generate_community_variables(
            self.device, source_routes, False
        )
        negated = self.context.generate_community_variables(
            self.device, source_routes, True
        )
        if isinstance(normal, dict) and normal and isinstance(negated, str):
            return normal, negated
        log_warning("Cannot construct community for device '%s'", self.device)
        raise ValueError(
            f"Missing community encoding for device '{self.device}'"
        )

    def history(self, history_key: str) -> Optional[str]:
        if util_keyword.ATTR_HISTORY not in self.requested:
            return None
        value = self.context.get_history_value(self.device, history_key)
        if value is not None:
            return value
        log_warning(
            "Cannot construct history for device '%s' and protocol '%s'",
            self.device,
            self.protocol.value,
        )
        raise ValueError(
            f"Missing history attribute for device '{self.device}'"
        )


@dataclass(frozen=True)
class DefaultRouteAttributeHandler:
    """Construct dynamic static/connected attributes using symbolic defaults."""

    protocol: RouteProtocol
    history_key: str

    def analyze(
        self,
        context: RouteAttributeContext,
        device: str,
        routes: List[Route],
    ) -> RouteAttributes:
        resolver = _AttributeResolver.create(context, device, self.protocol)
        source_file = util_keyword.DATA_PLANE_FILE
        route = routes[0]
        communities, negated_community = resolver.communities(routes)
        return RouteAttributes(
            protocol=self.protocol,
            permitted=True,
            prefix_length=resolver.resolve(
                util_keyword.ATTR_PREFIX_LENGTH,
                route.prefix_length,
                None,
                source_file=source_file,
            ),
            admin_dist=resolver.resolve(
                util_keyword.ATTR_ADMIN_DIST,
                route.ad,
                None,
                source_file=source_file,
            ),
            local_pref=resolver.resolve(
                util_keyword.ATTR_LOCAL_PREF,
                None,
                util_keyword.DEFAULT_ATTR_LOCAL_PREF,
                source_file=source_file,
            ),
            metric=resolver.resolve(
                util_keyword.ATTR_METRIC,
                None,
                util_keyword.DEFAULT_ATTR_METRIC,
                source_file=source_file,
            ),
            med=resolver.resolve(
                util_keyword.ATTR_MED,
                None,
                util_keyword.DEFAULT_ATTR_MED,
                source_file=source_file,
            ),
            ospf_area=resolver.resolve(
                util_keyword.ATTR_OSPF_AREA,
                None,
                util_keyword.DEFAULT_ATTR_OSPF_AREA,
                source_file=source_file,
            ),
            ospf_type=resolver.resolve(
                util_keyword.ATTR_OSPF_TYPE,
                None,
                util_keyword.DEFAULT_ATTR_OSPF_TYPE,
                source_file=source_file,
            ),
            history=resolver.history(self.history_key),
            communities=communities,
            negated_community_constraint=negated_community,
        )


@dataclass(frozen=True)
class BgpRouteAttributeHandler:
    """Construct dynamic eBGP/iBGP attributes from supplemental routes."""

    protocol: RouteProtocol

    def analyze(
        self,
        context: RouteAttributeContext,
        device: str,
        routes: List[Route],
    ) -> RouteAttributes:
        resolver = _AttributeResolver.create(context, device, self.protocol)
        source_file = util_keyword.BGP_ROUTES_FILE
        route = routes[0]
        bgp_routes = context.get_selected_bgp_info(
            device, routes, self.protocol
        )
        self._validate_bgp_routes(
            device, route.network, resolver.requested, bgp_routes
        )
        communities, negated_community = resolver.communities(routes)
        history_key = (
            util_keyword.HISTORY_KEY_IBGP
            if self.protocol is RouteProtocol.IBGP
            else util_keyword.HISTORY_KEY_BGP
        )
        return RouteAttributes(
            protocol=self.protocol,
            permitted=True,
            prefix_length=resolver.resolve(
                util_keyword.ATTR_PREFIX_LENGTH,
                route.prefix_length,
                None,
                source_file=util_keyword.DATA_PLANE_FILE,
            ),
            admin_dist=resolver.resolve(
                util_keyword.ATTR_ADMIN_DIST,
                route.ad,
                None,
                source_file=util_keyword.DATA_PLANE_FILE,
            ),
            local_pref=resolver.resolve(
                util_keyword.ATTR_LOCAL_PREF,
                resolver.parse_unique(
                    util_keyword.ATTR_LOCAL_PREF,
                    (
                        item.local_pref
                        for item in bgp_routes
                        if item.local_pref is not None
                    ),
                    source_file=source_file,
                ),
                util_keyword.DEFAULT_ATTR_LOCAL_PREF,
                source_file=source_file,
            ),
            metric=resolver.resolve(
                util_keyword.ATTR_METRIC,
                resolver.parse_unique(
                    util_keyword.ATTR_METRIC,
                    (item.aspath_length for item in bgp_routes),
                    source_file=source_file,
                ),
                util_keyword.DEFAULT_ATTR_METRIC,
                source_file=source_file,
            ),
            med=resolver.resolve(
                util_keyword.ATTR_MED,
                resolver.parse_unique(
                    util_keyword.ATTR_MED,
                    (item.med for item in bgp_routes if item.med is not None),
                    source_file=source_file,
                ),
                util_keyword.DEFAULT_ATTR_MED,
                source_file=source_file,
            ),
            ospf_area=resolver.resolve(
                util_keyword.ATTR_OSPF_AREA,
                None,
                util_keyword.DEFAULT_ATTR_OSPF_AREA,
                source_file=source_file,
            ),
            ospf_type=resolver.resolve(
                util_keyword.ATTR_OSPF_TYPE,
                None,
                util_keyword.DEFAULT_ATTR_OSPF_TYPE,
                source_file=source_file,
            ),
            history=resolver.history(history_key),
            communities=communities,
            negated_community_constraint=negated_community,
        )

    def _validate_bgp_routes(
        self,
        device: str,
        network: str,
        requested: Mapping[str, bool],
        bgp_routes: List[BgpRoute],
    ) -> None:
        needs_bgp_route = any(
            requested.get(attribute, False)
            for attribute in (
                util_keyword.ATTR_LOCAL_PREF,
                util_keyword.ATTR_METRIC,
                util_keyword.ATTR_MED,
                util_keyword.ATTR_COMMUNITY,
            )
        )
        if needs_bgp_route and not bgp_routes:
            log_warning(
                "No matching %s route in %s for device '%s', network '%s'",
                self.protocol.value,
                util_keyword.BGP_ROUTES_FILE,
                device,
                network,
            )
            raise ValueError(
                f"Missing {self.protocol.value} route attributes for "
                f"device '{device}'"
            )


class OspfRouteAttributeHandler:
    """Construct dynamic OSPF attributes from dataplane and OSPF routes."""

    _OSPF_TYPES = {
        "O": "#b00",
        "OIA": "#b01",
        "E1": "#b10",
        "E2": "#b11",
    }

    def analyze(
        self,
        context: RouteAttributeContext,
        device: str,
        routes: List[Route],
    ) -> RouteAttributes:
        protocol = RouteProtocol.OSPF
        resolver = _AttributeResolver.create(context, device, protocol)
        source_file = util_keyword.OSPF_ROUTES_FILE
        route = routes[0]
        ospf_routes = context.get_all_ospf_info(device, route.network)
        needs_ospf_route = any(
            resolver.requested.get(attribute, False)
            for attribute in (
                util_keyword.ATTR_METRIC,
                util_keyword.ATTR_OSPF_AREA,
                util_keyword.ATTR_OSPF_TYPE,
            )
        )
        if needs_ospf_route and not ospf_routes:
            log_warning(
                "No matching OSPF route in %s for device '%s', network '%s'",
                source_file,
                device,
                route.network,
            )
            raise ValueError(
                f"Missing OSPF route attributes for device '{device}'"
            )

        ospf_types = []
        if resolver.requested.get(util_keyword.ATTR_OSPF_TYPE, False):
            for ospf_route in ospf_routes:
                ospf_type = self._OSPF_TYPES.get(ospf_route.route_type.upper())
                if ospf_type is None:
                    log_warning(
                        "Unsupported OSPF route type '%s' for device '%s' in %s",
                        ospf_route.route_type,
                        device,
                        source_file,
                    )
                    raise ValueError(
                        f"Unsupported OSPF route type for device '{device}'"
                    )
                ospf_types.append(ospf_type)

        communities, negated_community = resolver.communities(routes)
        return RouteAttributes(
            protocol=protocol,
            permitted=True,
            prefix_length=resolver.resolve(
                util_keyword.ATTR_PREFIX_LENGTH,
                route.prefix_length,
                None,
                source_file=util_keyword.DATA_PLANE_FILE,
            ),
            admin_dist=resolver.resolve(
                util_keyword.ATTR_ADMIN_DIST,
                route.ad,
                None,
                source_file=util_keyword.DATA_PLANE_FILE,
            ),
            local_pref=resolver.resolve(
                util_keyword.ATTR_LOCAL_PREF,
                None,
                util_keyword.DEFAULT_ATTR_LOCAL_PREF,
                source_file=source_file,
            ),
            metric=resolver.resolve(
                util_keyword.ATTR_METRIC,
                resolver.parse_unique(
                    util_keyword.ATTR_METRIC,
                    (item.path_cost for item in ospf_routes),
                    source_file=source_file,
                ),
                util_keyword.DEFAULT_ATTR_METRIC,
                source_file=source_file,
            ),
            med=resolver.resolve(
                util_keyword.ATTR_MED,
                None,
                util_keyword.DEFAULT_ATTR_MED,
                source_file=source_file,
            ),
            ospf_area=resolver.resolve(
                util_keyword.ATTR_OSPF_AREA,
                resolver.parse_unique(
                    util_keyword.ATTR_OSPF_AREA,
                    (
                        item.area
                        for item in ospf_routes
                        if item.area is not None
                    ),
                    source_file=source_file,
                ),
                util_keyword.DEFAULT_ATTR_OSPF_AREA,
                source_file=source_file,
            ),
            ospf_type=resolver.resolve(
                util_keyword.ATTR_OSPF_TYPE,
                resolver.parse_unique(
                    util_keyword.ATTR_OSPF_TYPE,
                    ospf_types,
                    source_file=source_file,
                ),
                util_keyword.DEFAULT_ATTR_OSPF_TYPE,
                source_file=source_file,
            ),
            history=resolver.history(util_keyword.HISTORY_KEY_OSPF),
            communities=communities,
            negated_community_constraint=negated_community,
        )


class NoRouteAttributeHandler:
    """Construct the explicit route-attribute state for no matching route."""

    def analyze(
        self,
        context: RouteAttributeContext,
        device: str,
    ) -> RouteAttributes:
        negated = context.generate_community_variables(device, [], True)
        return RouteAttributes(
            protocol=None,
            permitted=False,
            metric=0,
            prefix_length=0,
            communities=context.generate_community_variables_for_no_routes(device),
            negated_community_constraint=(
                negated if isinstance(negated, str) else None
            ),
        )


def build_protocol_handlers() -> Dict[RouteProtocol, RouteAttributeHandler]:
    """Build the route-attribute handler registry."""
    return {
        RouteProtocol.CONNECTED: DefaultRouteAttributeHandler(
            RouteProtocol.CONNECTED, util_keyword.HISTORY_KEY_CONNECTED
        ),
        RouteProtocol.STATIC: DefaultRouteAttributeHandler(
            RouteProtocol.STATIC, util_keyword.HISTORY_KEY_STATIC
        ),
        RouteProtocol.EBGP: BgpRouteAttributeHandler(RouteProtocol.EBGP),
        RouteProtocol.IBGP: BgpRouteAttributeHandler(RouteProtocol.IBGP),
        RouteProtocol.OSPF: OspfRouteAttributeHandler(),
    }
