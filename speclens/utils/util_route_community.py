#!/usr/bin/env python3
"""Encode router-level OVERALL_BEST communities as a single SMT BitVec."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Protocol, Union

from utils import util_file, util_keyword
from utils.util_data import BgpRoute, Route, RouteProtocol
from utils.util_log import get_logger
from utils.util_smt import SmtVariableNamer

logger = get_logger(__name__)

CommunityEncoding = Union[Dict[str, str], str, None]
_OVERALL_OR_CONSTRAINT_KEY = "_overall_or_constraint"


class _CommunityEncoderHost(Protocol):
    """Router-level services required by the community encoder."""

    work_dir: Path
    namer: SmtVariableNamer

    def get_selected_bgp_info(
        self,
        device: str,
        routes: List[Route],
        protocol: RouteProtocol,
    ) -> List[BgpRoute]: ...


class CommunityEncoder:
    """Encode indexed communities in one BitVec variable per device."""

    def __init__(self, host: _CommunityEncoderHost) -> None:
        self._host = host
        self.community_bit_width = 0
        self.community_to_index: Dict[str, int] = {}

    def load(self) -> None:
        """Load and validate the SMT community index."""
        (
            self.community_bit_width,
            self.community_to_index,
        ) = util_file.load_community_index(self._host.work_dir)

    def log_load_summary(self) -> None:
        logger.info(
            "  -> Communities index: width=%d, %d entries",
            self.community_bit_width,
            len(self.community_to_index),
        )

    def generate_community_variables(
        self,
        device: str,
        routes: List[Route],
        negated_mode: bool = False,
    ) -> CommunityEncoding:
        """Encode the selected route communities or their negation."""
        if not self.community_to_index:
            return None if negated_mode else {}

        variable = self._community_variable(device)
        if not routes:
            return self._encode_exact(
                variable,
                self._zero_bitvec(),
                negated_mode,
            )

        bgp_routes = self._host.get_selected_bgp_info(
            device,
            routes,
            RouteProtocol.from_token(routes[0].protocol),
        )
        if len(bgp_routes) == 1:
            communities = bgp_routes[0].communities if bgp_routes else []
            return self._encode_exact(
                variable,
                self._to_bitvec(communities),
                negated_mode,
            )

        if not bgp_routes:
            raise ValueError(
                f"Cannot encode ECMP communities for device '{device}': "
                "no matching BGP routes"
            )
        alternatives = sorted(
            {
                self._to_bitvec(sorted(route.communities))
                for route in bgp_routes
            }
        )
        return self._encode_alternatives(
            variable,
            alternatives,
            negated_mode,
        )

    def generate_community_variables_for_no_routes(
        self,
        device: str,
    ) -> Dict[str, str]:
        if not self.community_to_index:
            return {}
        return {self._community_variable(device): self._zero_bitvec()}

    def _community_variable(self, device: str) -> str:
        return self._host.namer.overall_best(
            device,
            util_keyword.ATTR_COMMUNITY,
        )

    def _zero_bitvec(self) -> str:
        if self.community_bit_width <= 0:
            return "#b0"
        return f"#b{'0' * self.community_bit_width}"

    def _to_bitvec(self, communities: List[str]) -> str:
        if self.community_bit_width <= 0:
            return "#b0"
        value = 0
        for community in communities:
            index = self.community_to_index.get(community)
            if index is None:
                logger.warning(
                    "Community '%s' is absent from the community index; ignoring it",
                    community,
                )
                continue
            value |= 1 << index
        return f"#b{value:0{self.community_bit_width}b}"

    @staticmethod
    def _encode_exact(
        variable: str,
        bitvec: str,
        negated_mode: bool,
    ) -> Union[Dict[str, str], str]:
        if negated_mode:
            return f"(not (= {variable} {bitvec}))"
        return {variable: bitvec}

    @staticmethod
    def _encode_alternatives(
        variable: str,
        alternatives: List[str],
        negated_mode: bool,
    ) -> Union[Dict[str, str], str]:
        equalities = [
            f"(= {variable} {bitvec})"
            for bitvec in alternatives
        ]
        if len(equalities) == 1:
            if negated_mode:
                return f"(not {equalities[0]})"
            return {variable: alternatives[0]}

        disjunction = f"(or {' '.join(equalities)})"
        if negated_mode:
            return f"(not {disjunction})"
        return {_OVERALL_OR_CONSTRAINT_KEY: disjunction}
