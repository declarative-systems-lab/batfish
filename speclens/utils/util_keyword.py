#!/usr/bin/env python3


######################################################################
# Input file names based on the work-directory.
######################################################################

SMT_ENCODING_FILE                   = "smt_encoding.smt2"

DATA_PLANE_FILE                     = "0_sim_data_plane.txt"
BGP_ROUTES_FILE                     = "0_sim_bgp_routes.txt"
BGP_PEERS_FILE                      = "0_sim_bgp_peers.txt"
OSPF_ROUTES_FILE                    = "0_sim_ospf_routes.txt"
OSPF_PEERS_FILE                     = "0_sim_ospf_peers.txt"

HOSTNAMES_FILE                      = "0_all_hostnames.txt"
INTERFACES_FILE                     = "0_all_interfaces.txt"
DST_IPS_FILE                        = "0_all_dst_ips.txt"
MODEL_IGP_FILE                      = "0_all_model_igp.txt"

HISTORY_ENUMS_FILE                  = "0_smt_history_enums.txt"
COMMUNITY_INDEXES_FILE              = "0_smt_community_indexes.txt"
OVERALL_ATTRIBUTES_FILE             = "0_smt_overall_attributes.txt"
CONTROLFWD_IGNORES_FILE             = "0_smt_controlfwd_ignores.txt"
PROPERTY_FILE                       = "0_smt_property.txt"
PROPERTY_VARIABLES_FILE             = "0_smt_property_variables.txt"

KEY_PREFIXLISTS_FILE                = "0_opt_key_prefixlists.txt"
EMPTY_COMMUNITIES_FILE              = "0_opt_empty_communities.txt"

MULTIPLE_LOCATIONS_FILE             = "0_subspec_multiple_locations.txt"

ROUTER_LEVEL_SUBSPEC_REQUIRED_FILES = (
    DATA_PLANE_FILE,
    BGP_ROUTES_FILE,
    BGP_PEERS_FILE,
    OSPF_ROUTES_FILE,
    OSPF_PEERS_FILE,
    HOSTNAMES_FILE,
    INTERFACES_FILE,
    DST_IPS_FILE,
    MODEL_IGP_FILE,
    HISTORY_ENUMS_FILE,
    COMMUNITY_INDEXES_FILE,
    OVERALL_ATTRIBUTES_FILE,
    CONTROLFWD_IGNORES_FILE,
)

ROUTER_LOCAL_ENCODING_REQUIRED_FILES = (
    SMT_ENCODING_FILE,
    HOSTNAMES_FILE,
    MODEL_IGP_FILE,
    PROPERTY_VARIABLES_FILE,
)


######################################################################
# Output directory and file names (including prefixes and suffixes).
######################################################################

ROUTER_LEVEL_SUBSPEC_DIR            = "1_router_level_subspec"
ROUTER_LOCAL_ENCODING_DIR           = "2_router_local_encoding"
CONSISTENCY_CHECK_DIR               = "3_consistency_check"
ROUTEMAP_SUBSPEC_DIR                = "3_routemap_subspec"
SUBSPEC_DIR                         = "4_subspec"
SUBSPEC_NOSCOPE_DIR                 = "5_subspec_noscope"
SUBSPEC_FULLSYM_DIR                 = "6_subspec_fullsym"

INTERMEDIATE_FIELD_DIR_SUFFIX       = "intermediate_subspec_field_files"
INTERMEDIATE_LINE_DIR_SUFFIX        = "intermediate_subspec_line_files"
INTERMEDIATE_JOINT_DIR_SUFFIX       = "intermediate_subspec_joint_files"
INTERMEDIATE_METADATA_DIR_SUFFIX    = "intermediate_subspec_metadata_files"

SATISFACTION_ASSUMEGUARANTEE_PREFIX = "satisfaction_assume_guarantee"
VIOLATION_ASSUMEGUARANTEE_PREFIX    = "violation_assume_guarantee"

SATISFACTION_CHECK_FILE_PREFIX      = "satisfaction_check"
VIOLATION_CHECK_FILE_PREFIX         = "violation_check"

LOCAL_ENCODING_FILE_PREFIX          = "router_local_encoding"

GLOBAL_ENCODING_FILE                = "global_encoding.smt2"
GLOBAL_SUBSPEC_ENCODING_FILE        = "global_encoding_subspec.smt2"

CONSISTENCY_CHECK_FILE              = "consistency_check.txt"

ROUTEMAP_SUBSPECS_FILE              = "routemap_subspecs.txt"

FIELD_LEVEL_SUBSPECS_FILE           = "field_level_subspecs.txt"
LINE_LEVEL_SUBSPECS_FILE            = "line_level_subspecs.txt"
JOINT_LEVEL_SUBSPECS_FILE           = "joint_level_subspecs.txt"


######################################################################
# SMT variable names (token, prefix, suffix), and default values.
######################################################################

ATTR_PERMITTED                      = "permitted"
ATTR_PREFIX_LENGTH                  = "prefixLength"
ATTR_ADMIN_DIST                     = "adminDist"
ATTR_LOCAL_PREF                     = "localPref"
ATTR_METRIC                         = "metric"
ATTR_MED                            = "med"
ATTR_OSPF_AREA                      = "ospfArea"
ATTR_OSPF_TYPE                      = "ospfType"
ATTR_ROUTER_ID                      = "routerID"
ATTR_HISTORY                        = "history"
ATTR_BGP_INTERNAL                   = "bgpInternal"
ATTR_CLIENT_ID                      = "clientId"
ATTR_IGP_METRIC                     = "igpMetric"
ATTR_COMMUNITY                      = "community"

SMT_ZERO_TOKEN                      = "0"
SMT_SLICE_MAIN_TOKEN                = "SLICE-MAIN"
SMT_CONTROL_FORWARDING_TOKEN        = "CONTROL-FORWARDING"
SMT_OVERALL_BEST_TOKEN              = "OVERALL_BEST"

SMT_VAR_DEFAULT_PREFIX              = f"{SMT_ZERO_TOKEN}_"
SMT_VAR_MODEL_IGP_PREFIX            = f"{SMT_ZERO_TOKEN}_{SMT_SLICE_MAIN_TOKEN}_"

SMT_ATTR_PERMITTED_VAR_SUFFIX       = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_PERMITTED}"
SMT_ATTR_PREFIX_LENGTH_VAR_SUFFIX   = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_PREFIX_LENGTH}"
SMT_ATTR_ADMIN_DIST_VAR_SUFFIX      = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_ADMIN_DIST}"
SMT_ATTR_LOCAL_PREF_VAR_SUFFIX      = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_LOCAL_PREF}"
SMT_ATTR_METRIC_VAR_SUFFIX          = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_METRIC}"
SMT_ATTR_MED_VAR_SUFFIX             = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_MED}"
SMT_ATTR_OSPF_AREA_VAR_SUFFIX       = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_OSPF_AREA}"
SMT_ATTR_OSPF_TYPE_VAR_SUFFIX       = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_OSPF_TYPE}"
SMT_ATTR_ROUTER_ID_VAR_SUFFIX       = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_ROUTER_ID}"
SMT_ATTR_HISTORY_VAR_SUFFIX         = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_HISTORY}"
SMT_ATTR_BGP_INTERNAL_VAR_SUFFIX    = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_BGP_INTERNAL}"
SMT_ATTR_CLIENT_ID_VAR_SUFFIX       = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_CLIENT_ID}"
SMT_ATTR_IGP_METRIC_VAR_SUFFIX      = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_IGP_METRIC}"
SMT_ATTR_COMMUNITY_VAR_SUFFIX       = f"_{SMT_OVERALL_BEST_TOKEN}_None_{ATTR_COMMUNITY}"


######################################################################
# Overall best attributes, and protocols.
######################################################################

PROTOCOL_BGP                        = "bgp"
PROTOCOL_EBGP                       = "ebgp"
PROTOCOL_IBGP                       = "ibgp"
PROTOCOL_OSPF                       = "ospf"
PROTOCOL_CONNECTED                  = "connected"
PROTOCOL_STATIC                     = "static"
PROTOCOL_LOCAL                      = "local"

HISTORY_KEY_BGP                     = "BGP"
HISTORY_KEY_IBGP                    = "IBGP"
HISTORY_KEY_OSPF                    = "OSPF"
HISTORY_KEY_CONNECTED               = "CONNECTED"
HISTORY_KEY_STATIC                  = "STATIC"

DEFAULT_ATTR_LOCAL_PREF             = "100"
DEFAULT_ATTR_METRIC                 = "0"
DEFAULT_ATTR_MED                    = "0"
DEFAULT_ATTR_OSPF_AREA              = "0"
DEFAULT_ATTR_OSPF_TYPE              = "0b00"
DEFAULT_ATTR_COMMUNITY              = "0b"

OVERALL_BEST_ATTRIBUTES = frozenset(
    {
        ATTR_PREFIX_LENGTH,
        ATTR_ADMIN_DIST,
        ATTR_LOCAL_PREF,
        ATTR_METRIC,
        ATTR_MED,
        ATTR_OSPF_AREA,
        ATTR_OSPF_TYPE,
        ATTR_ROUTER_ID,
        ATTR_HISTORY,
        ATTR_BGP_INTERNAL,
        ATTR_CLIENT_ID,
        ATTR_IGP_METRIC,
        ATTR_COMMUNITY,
    }
)

OVERALL_BEST_ATTRIBUTES_BY_PROTOCOL = {
    PROTOCOL_EBGP: {
        ATTR_PREFIX_LENGTH  : True,
        ATTR_ADMIN_DIST     : True,
        ATTR_METRIC         : True,
        ATTR_HISTORY        : True,
        ATTR_COMMUNITY      : True,
        ATTR_OSPF_AREA      : False,
        ATTR_OSPF_TYPE      : False,
    },
    PROTOCOL_IBGP: {
        ATTR_PREFIX_LENGTH  : True,
        ATTR_ADMIN_DIST     : True,
        ATTR_LOCAL_PREF     : True,
        ATTR_METRIC         : True,
        ATTR_MED            : True,
        ATTR_HISTORY        : True,
        ATTR_COMMUNITY      : True,
        ATTR_OSPF_AREA      : False,
        ATTR_OSPF_TYPE      : False,
    },
    PROTOCOL_STATIC: {
        ATTR_PREFIX_LENGTH  : True,
        ATTR_ADMIN_DIST     : True,
        ATTR_HISTORY        : True,
        ATTR_LOCAL_PREF     : False,
        ATTR_METRIC         : False,
        ATTR_MED            : False,
        ATTR_COMMUNITY      : False,
        ATTR_OSPF_AREA      : False,
        ATTR_OSPF_TYPE      : False,
    },
    PROTOCOL_CONNECTED: {
        ATTR_PREFIX_LENGTH  : True,
        ATTR_ADMIN_DIST     : True,
        ATTR_HISTORY        : True,
        ATTR_LOCAL_PREF     : False,
        ATTR_METRIC         : False,
        ATTR_MED            : False,
        ATTR_COMMUNITY      : False,
        ATTR_OSPF_AREA      : False,
        ATTR_OSPF_TYPE      : False,
    },
    PROTOCOL_OSPF: {
        ATTR_PREFIX_LENGTH  : True,
        ATTR_ADMIN_DIST     : True,
        ATTR_METRIC         : True,
        ATTR_OSPF_AREA      : True,
        ATTR_OSPF_TYPE      : True,
        ATTR_HISTORY        : True,
        ATTR_LOCAL_PREF     : False,
        ATTR_MED            : False,
        ATTR_COMMUNITY      : False,
    }
}


######################################################################
# Important global parameters.
######################################################################

Z3                                  = "z3"

SMT_CHECK_SAT                       = "(check-sat)"
SMT_GET_MODEL                       = "(get-model)"

SMT_SIMPLIFICATION_TACTICS          = (
    "simplify",
    "propagate-values",
    "solve-eqs",
    "ctx-solver-simplify",
)

SUBSPEC_NORM_COUNT                  = 3
