"""Path construction plus file and directory persistence for the pipeline."""

import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import (
    Dict,
    FrozenSet,
    Hashable,
    List,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
)

from utils import util_keyword, util_smt
from utils.util_data import (
    BgpPeerTables,
    BgpRoute,
    ConfigVariable,
    HistoryEnumTables,
    Internet2PatchSummary,
    Internet2ReconstructionResult,
    OspfPeerTables,
    OspfRoute,
    PeerTables,
    Route,
    RouterLevelAnalysisReport,
    SubspecDirectoryLayout,
)
from utils.util_log import get_logger

logger = get_logger(__name__)

_KeyT = TypeVar("_KeyT", bound=Hashable)
_ValueT = TypeVar("_ValueT")

_SUBSPEC_OUTPUT_DIRECTORIES = {
    4: util_keyword.SUBSPEC_DIR,
    5: util_keyword.SUBSPEC_NOSCOPE_DIR,
    6: util_keyword.SUBSPEC_FULLSYM_DIR,
}
_SUBSPEC_OUTPUT_FILES = {
    "field": util_keyword.FIELD_LEVEL_SUBSPECS_FILE,
    "line": util_keyword.LINE_LEVEL_SUBSPECS_FILE,
    "joint": util_keyword.JOINT_LEVEL_SUBSPECS_FILE,
}


# ============================================================================
# Generic filesystem primitives
# ============================================================================

def load_text(file_path: Path) -> str:
    """Read a UTF-8 text file."""
    return file_path.read_text(encoding="utf-8")


def load_text_lines(file_path: Path, *, keepends: bool = False) -> List[str]:
    """Read a UTF-8 text file and split it into lines."""
    return load_text(file_path).splitlines(keepends=keepends)


def load_data_lines(file_path: Path, *, comment_prefix: str = "#") -> List[str]:
    """Read stripped, non-empty, non-comment UTF-8 lines."""
    return [
        line
        for raw_line in load_text_lines(file_path)
        if (line := raw_line.strip()) and not line.startswith(comment_prefix)
    ]


def load_community_index(work_dir: Path) -> Tuple[int, Dict[str, int]]:
    """Load and validate the indexed SMT community BitVec mapping."""
    index_file = work_dir / util_keyword.COMMUNITY_INDEXES_FILE
    lines = load_data_lines(index_file)
    if not lines:
        raise ValueError(f"Empty community index file: {index_file}")

    try:
        bit_width = int(lines[0])
    except ValueError as error:
        raise ValueError(
            f"Invalid community bit width '{lines[0]}' in {index_file}:1"
        ) from error
    if bit_width < 0:
        raise ValueError(
            f"Negative community bit width {bit_width} in {index_file}:1"
        )

    community_to_index: Dict[str, int] = {}
    index_to_community: Dict[int, str] = {}
    for line_number, line in enumerate(lines[1:], start=2):
        community, separator, raw_index = line.rpartition(":")
        community = community.strip()
        if not separator or not community or not raw_index.strip():
            raise ValueError(
                f"Malformed community index entry in "
                f"{index_file}:{line_number}: {line}"
            )
        try:
            index = int(raw_index.strip())
        except ValueError as error:
            raise ValueError(
                f"Invalid community index in "
                f"{index_file}:{line_number}: {line}"
            ) from error
        if not 0 <= index < bit_width:
            raise ValueError(
                f"Community index {index} for '{community}' is outside "
                f"[0, {bit_width}) in {index_file}:{line_number}"
            )
        if community in community_to_index:
            raise ValueError(
                f"Duplicate community '{community}' in "
                f"{index_file}:{line_number}"
            )
        if index in index_to_community:
            raise ValueError(
                f"Community index {index} is assigned to both "
                f"'{index_to_community[index]}' and '{community}' in "
                f"{index_file}:{line_number}"
            )
        community_to_index[community] = index
        index_to_community[index] = community

    return bit_width, community_to_index


def write_text(file_path: Path, content: str) -> None:
    """Write UTF-8 text, replacing an existing file."""
    file_path.write_text(content, encoding="utf-8")


def copy_file(source: Path, destination: Path) -> None:
    """Copy one file while preserving its metadata."""
    shutil.copy2(source, destination)


def write_temporary_text(content: str, *, suffix: str = "") -> Path:
    """Write UTF-8 text to a persistent temporary file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=suffix, delete=False
    ) as temp_file:
        temp_file.write(content)
        return Path(temp_file.name)


def create_temporary_directory(
    *, prefix: str = ""
) -> tempfile.TemporaryDirectory:
    """Create a temporary directory object whose caller controls cleanup."""
    return tempfile.TemporaryDirectory(prefix=prefix)


def delete_file(file_path: Union[str, Path], *, missing_ok: bool = True) -> bool:
    """Delete one file and return whether a file was removed."""
    path = Path(file_path)
    try:
        path.unlink()
    except FileNotFoundError:
        if not missing_ok:
            raise
        return False
    return True


def safe_filename_component(value: str) -> str:
    """Replace separators that are unsafe in generated metadata filenames."""
    return value.replace("/", "_").replace(":", "_").replace(" ", "_")


def router_local_encoding_file_name(router: str) -> str:
    """Return the stage-2 SMT filename for one router."""
    return f"{util_keyword.LOCAL_ENCODING_FILE_PREFIX}_{router}.smt2"


def assume_guarantee_file_name(router: str, *, satisfaction: bool) -> str:
    """Return one stage-1 assume-guarantee filename."""
    prefix = (
        util_keyword.SATISFACTION_ASSUMEGUARANTEE_PREFIX
        if satisfaction
        else util_keyword.VIOLATION_ASSUMEGUARANTEE_PREFIX
    )
    return f"{prefix}_{router}.txt"


def subspec_output_directory_name(stage: int) -> str:
    """Return the fixed output directory for subspec stages 4 through 6."""
    try:
        return _SUBSPEC_OUTPUT_DIRECTORIES[stage]
    except KeyError as exc:
        raise ValueError(f"Unsupported public subspec stage: {stage}") from exc


def intermediate_directory_name(stage: int, suffix: str) -> str:
    """Return a stage-prefixed intermediate directory name."""
    return f"{stage}_{suffix}"


def ensure_directory(directory: Path) -> Path:
    """Create a directory when needed and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def path_exists(path: Union[str, Path]) -> bool:
    """Return whether a filesystem path exists."""
    return Path(path).exists()


def require_file(
    file_path: Union[str, Path], *, description: str = "Required file"
) -> Path:
    """Return an existing regular file or raise ``FileNotFoundError``."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    return path


def _create_subspec_intermediate_root(
    work_dir: Path,
    *,
    verbose: bool,
) -> Tuple[Path, Optional[tempfile.TemporaryDirectory]]:
    if verbose:
        return work_dir, None

    temporary_directory = create_temporary_directory()
    intermediate_root = Path(temporary_directory.name)
    logger.info(
        "Verbose mode disabled. Intermediate files will be stored in "
        "temporary directory: %s",
        intermediate_root,
    )
    return intermediate_root, temporary_directory


def _stage_intermediate_directory(
    root: Path,
    stage: int,
    suffix: str,
) -> Path:
    return ensure_directory(root / intermediate_directory_name(stage, suffix))


def initialize_subspec_directories(
    work_dir: Path,
    *,
    stage: int,
    verbose: bool,
    persistent_metadata: bool = False,
) -> SubspecDirectoryLayout:
    """Create the standard output/intermediate directory layout for one stage."""
    intermediate_root, temporary_directory = (
        _create_subspec_intermediate_root(work_dir, verbose=verbose)
    )

    output_dir = ensure_directory(work_dir / subspec_output_directory_name(stage))
    metadata_root = work_dir if persistent_metadata else intermediate_root
    metadata_dir = _stage_intermediate_directory(
        metadata_root,
        stage,
        util_keyword.INTERMEDIATE_METADATA_DIR_SUFFIX,
    )
    field_dir = _stage_intermediate_directory(
        intermediate_root,
        stage,
        util_keyword.INTERMEDIATE_FIELD_DIR_SUFFIX,
    )
    line_dir = _stage_intermediate_directory(
        intermediate_root,
        stage,
        util_keyword.INTERMEDIATE_LINE_DIR_SUFFIX,
    )
    return SubspecDirectoryLayout(
        output_dir=output_dir,
        metadata_dir=metadata_dir,
        field_intermediate_dir=field_dir,
        line_intermediate_dir=line_dir,
        temporary_directory=temporary_directory,
    )


def satisfaction_check_file_name(router: str) -> str:
    """Return the stage-3 satisfaction-check SMT filename for one router."""
    return f"{util_keyword.SATISFACTION_CHECK_FILE_PREFIX}_{router}.smt2"


def violation_check_file_name(router: str) -> str:
    """Return the stage-3 violation-check SMT filename for one router."""
    return f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_{router}.smt2"


# ============================================================================
# Metadata (extract / find)
# ============================================================================

def extract_synthesis_metadata(
    synthesis_file_path: Union[str, Path],
) -> Tuple[List[str], List[str]]:
    """Extract metadata from synthesis file:
    1. All VAR type declarations (declare-fun)
    2. All commented Config variable assignments ;(assert (= Config_XXX value))
    """
    source_file = Path(synthesis_file_path)
    declare_funs: List[str] = []
    commented_config_asserts: List[str] = []

    if not source_file.is_file():
        logger.warning(f"Synthesis file not found: {source_file}")
        return declare_funs, commented_config_asserts

    try:
        lines = source_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning(f"Failed to read synthesis file {source_file}: {exc}")
        return declare_funs, commented_config_asserts

    current_declare = []
    in_declare = False
    depth = 0

    for line in lines:
        stripped = line.strip()

        if "(declare-fun" in stripped:
            if in_declare:
                declare_fun_str = " ".join(current_declare)
                declare_funs.append(declare_fun_str)
                current_declare = []
                in_declare = False
                depth = 0
            in_declare = True
            current_declare = [stripped]
            depth = stripped.count('(') - stripped.count(')')
            if depth == 0:
                declare_fun_str = " ".join(current_declare)
                declare_funs.append(declare_fun_str)
                current_declare = []
                in_declare = False
                depth = 0
        elif in_declare:
            if stripped:
                current_declare.append(stripped)
                depth += stripped.count('(') - stripped.count(')')
            if depth == 0:
                declare_fun_str = " ".join(current_declare)
                declare_funs.append(declare_fun_str)
                current_declare = []
                in_declare = False
                depth = 0

        if (
            not in_declare
            and stripped.startswith(";")
            and "(assert (= Config_" in stripped
        ):
            assert_part = stripped.lstrip(";").strip()
            if assert_part.startswith("(assert (= Config_"):
                if assert_part.count("(") == assert_part.count(")"):
                    commented_config_asserts.append(stripped)

    if in_declare and current_declare:
        declare_fun_str = " ".join(current_declare)
        declare_funs.append(declare_fun_str)

    return declare_funs, commented_config_asserts


def find_metadata_file(
    config_name: str,
    device: str,
    metadata_type: str,
    metadata_dir: Path,
) -> Optional[Path]:
    """Find metadata file for a given Config variable name, device, and metadata type."""
    safe_config_name = safe_filename_component(config_name)
    expected_filename = (
        f"synthesis_metadata_{metadata_type}_{device}_{safe_config_name}.txt"
    )
    metadata_file = metadata_dir / expected_filename

    if metadata_file.is_file():
        return metadata_file

    patterns = (
        f"synthesis_metadata_{metadata_type}_{device}_{safe_config_name}*.txt",
        f"synthesis_metadata_{metadata_type}_*_{safe_config_name}*.txt",
    )
    for pattern in patterns:
        matching_files = sorted(metadata_dir.glob(pattern))
        if matching_files:
            return matching_files[0]

    return None


def load_synthesis_metadata_file(
    metadata_file: Path,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Load declarations, commented equalities, and device from metadata."""
    declares: List[str] = []
    commented_equalities: List[str] = []
    device: Optional[str] = None
    if not metadata_file.is_file():
        return declares, commented_equalities, device

    try:
        lines = load_text_lines(metadata_file)
    except OSError as exc:
        logger.warning("Failed to read metadata file %s: %s", metadata_file, exc)
        return declares, commented_equalities, device

    in_declares_section = False
    in_commented_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("; Device:"):
            device_match = re.search(r"Device:\s*(\S+)", stripped)
            if device_match:
                device = device_match.group(1)
        if "All VAR type declarations" in line or "declare-fun" in stripped:
            in_declares_section = True
            in_commented_section = False
        if "All commented Config variable assignments" in line or "commented Config" in line:
            in_declares_section = False
            in_commented_section = True
        if in_declares_section and stripped.startswith("(declare-fun"):
            declares.append(stripped)
        if in_commented_section and stripped.startswith(";") and "(assert" in stripped:
            uncommented = stripped.lstrip(";").strip()
            if uncommented.startswith("(assert"):
                commented_equalities.append(uncommented)
    return declares, commented_equalities, device


def write_normalization_smt_input(
    content: str,
    *,
    metadata_file: Path,
    config_name: str,
    iteration: int,
    device: Optional[str],
    output_dir: Optional[Path] = None,
) -> Path:
    """Persist one generated Z3-normalization input and return its path."""
    target_dir = output_dir if output_dir is not None else metadata_file.parent
    safe_name = safe_filename_component(config_name)
    if device:
        file_name = (
            f"compute_subspec_from_{device}_{safe_name}_norm_iter{iteration}.smt2"
        )
    else:
        file_name = f"compute_subspec_from_{safe_name}_norm_iter{iteration}.smt2"
    output_file = target_dir / file_name
    write_text(output_file, content)
    return output_file


def prepare_config_synthesis_metadata(
    config_name: str,
    device: str,
    *,
    compute_dir: Path,
    metadata_dir: Optional[Path],
    metadata_type: str = "field",
) -> Optional[Path]:
    """Save and locate metadata for one generated subspec-computation file."""
    safe_name = safe_filename_component(config_name)
    compute_file = compute_dir / f"compute_subspec_from_{device}_{safe_name}.smt2"
    require_file(compute_file, description="Compute subspec file")
    if metadata_dir is None:
        return None

    save_synthesis_metadata(
        device,
        config_name,
        str(compute_file),
        metadata_dir,
        metadata_type,
    )
    return find_metadata_file(config_name, device, metadata_type, metadata_dir)


# ============================================================================
# Load Functions
# ============================================================================

def _missing_named_files(
    work_dir: Path,
    file_names: Sequence[str],
) -> List[str]:
    return [
        file_name
        for file_name in file_names
        if not (work_dir / file_name).is_file()
    ]


def _require_named_files(
    work_dir: Path,
    file_names: Sequence[str],
) -> None:
    missing_files = _missing_named_files(work_dir, file_names)
    if missing_files:
        raise FileNotFoundError(
            f"Missing required files in {work_dir}: "
            f"{', '.join(missing_files)}"
        )


def _require_files(
    file_paths: Sequence[Path],
    *,
    description: str,
) -> None:
    missing_files = [str(path) for path in file_paths if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(
            f"Missing required {description}: {', '.join(missing_files)}"
        )


def validate_router_level_inputs(work_dir: Path) -> None:
    """Raise when any required router-analysis input file is missing."""
    _require_named_files(
        work_dir,
        util_keyword.ROUTER_LEVEL_SUBSPEC_REQUIRED_FILES,
    )
    logger.info("All required files found in %s", work_dir)


def validate_router_local_encoding_inputs(work_dir: Path) -> None:
    """Validate the source files required by stage 2."""
    _require_named_files(
        work_dir,
        util_keyword.ROUTER_LOCAL_ENCODING_REQUIRED_FILES,
    )


def validate_router_local_encoding_outputs(work_dir: Path) -> None:
    """Validate stage-2 inputs needed for router-specific encoding."""
    _require_files(
        (
            work_dir / util_keyword.HOSTNAMES_FILE,
            work_dir
            / util_keyword.ROUTER_LOCAL_ENCODING_DIR
            / util_keyword.GLOBAL_ENCODING_FILE,
        ),
        description="router-local encoding files",
    )


def validate_consistency_checker_inputs(work_dir: Path) -> None:
    """Validate stage-1 and stage-2 outputs required by stage 3."""
    router_local_dir = work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
    router_level_dir = work_dir / util_keyword.ROUTER_LEVEL_SUBSPEC_DIR
    missing_items = []

    if not router_local_dir.is_dir():
        missing_items.append(f"{util_keyword.ROUTER_LOCAL_ENCODING_DIR}/ (directory)")
    elif not any(
        router_local_dir.glob(
            f"{util_keyword.LOCAL_ENCODING_FILE_PREFIX}_*.smt2"
        )
    ):
        missing_items.append(
            f"{util_keyword.ROUTER_LOCAL_ENCODING_DIR}/ "
            "(no router-local SMT files found)"
        )
    if not router_level_dir.is_dir():
        missing_items.append(f"{util_keyword.ROUTER_LEVEL_SUBSPEC_DIR}/ (directory)")

    if missing_items:
        raise FileNotFoundError(
            "Missing required input files/directories: " + ", ".join(missing_items)
        )


def validate_local_subspec_inputs(work_dir: Path) -> None:
    """Validate router-local and consistency-check inputs for stages 4/5."""
    router_local_dir = work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
    consistency_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    missing_items = []

    if not router_local_dir.is_dir():
        missing_items.append(f"{util_keyword.ROUTER_LOCAL_ENCODING_DIR}/ (directory)")
    elif not any(
        router_local_dir.glob(
            f"{util_keyword.LOCAL_ENCODING_FILE_PREFIX}_*.smt2"
        )
    ):
        missing_items.append(
            f"{util_keyword.ROUTER_LOCAL_ENCODING_DIR}/ "
            "(no router-local SMT files found)"
        )

    if not consistency_dir.is_dir():
        missing_items.append(f"{util_keyword.CONSISTENCY_CHECK_DIR}/ (directory)")
    else:
        if not any(
            consistency_dir.glob(
                f"{util_keyword.SATISFACTION_CHECK_FILE_PREFIX}_*.smt2"
            )
        ):
            missing_items.append(
                f"{util_keyword.CONSISTENCY_CHECK_DIR}/"
                f"{util_keyword.SATISFACTION_CHECK_FILE_PREFIX}_*.smt2 (missing)"
            )
        if not any(
            consistency_dir.glob(
                f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_*.smt2"
            )
        ):
            missing_items.append(
                f"{util_keyword.CONSISTENCY_CHECK_DIR}/"
                f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_*.smt2 (missing)"
            )

    if missing_items:
        raise FileNotFoundError(
            "Missing required input files/directories: " + ", ".join(missing_items)
        )


def validate_global_subspec_inputs(work_dir: Path) -> Tuple[Path, Path]:
    """Validate and return the impact/subspecification baselines for Stage 6."""
    router_local_dir = work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
    verification_file = (
        router_local_dir / util_keyword.GLOBAL_ENCODING_FILE
    )
    subspec_file = (
        router_local_dir
        / util_keyword.GLOBAL_SUBSPEC_ENCODING_FILE
    )
    _require_files(
        (verification_file, subspec_file),
        description="full-symbolic baseline files",
    )
    return verification_file, subspec_file


def load_model_igp(work_dir: Path) -> bool:
    """Load the model igp flag from 0_model_igp.txt.

    The file must contain either "0" or "1".
    """
    model_igp_file = work_dir / util_keyword.MODEL_IGP_FILE

    try:
        value = model_igp_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(
            f"Failed to load model IGP flag from {model_igp_file}: {exc}"
        ) from exc

    if value not in {"0", "1"}:
        raise ValueError(
            f"Invalid model IGP flag in {model_igp_file}: "
            f"expected '0' or '1', got {value!r}"
        )

    logger.info(f"Loaded model_igp.txt from {model_igp_file}: {value}")
    return value == "1"


def load_optional_model_igp(work_dir: Path) -> bool:
    """Load the stage-2 model-IGP flag, defaulting to false when unavailable."""
    model_igp_file = work_dir / util_keyword.MODEL_IGP_FILE
    if not model_igp_file.is_file():
        return False
    try:
        for raw_line in model_igp_file.read_text(encoding="utf-8").splitlines():
            value = raw_line.strip()
            if value:
                return value == "1"
    except OSError:
        return False
    return False


def _route_parse_error(
    file_path: Path,
    line_number: int,
    line: str,
    reason: str,
) -> ValueError:
    message = (
        f"Error parsing route file {file_path} at line {line_number}: "
        f"{reason}: {line}"
    )
    logger.warning(message)
    return ValueError(message)


def load_data_plane(work_dir: Path) -> List[Route]:
    """Load route entries from 0_data_plane.txt."""
    data_plane_file = work_dir / util_keyword.DATA_PLANE_FILE
    logger.info("Loading dataplane from %s", data_plane_file)

    routes: List[Route] = []
    with data_plane_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "Node" in line and "VRF" in line:
                continue
            if "=" in line and len(line) > 50:
                continue

            parts = line.split()
            if len(parts) < 10:
                raise _route_parse_error(
                    data_plane_file,
                    line_number,
                    line,
                    "expected at least 10 fields",
                )
            try:
                routes.append(
                    Route(
                        node=parts[0],
                        vrf=parts[1],
                        network=parts[2],
                        protocol=parts[3],
                        nexthop_ip=parts[4],
                        nexthop_interface=parts[5],
                        nexthop=parts[6],
                        metric=int(parts[7]),
                        ad=int(parts[8]),
                        tag=parts[9],
                    )
                )
            except (ValueError, IndexError) as exc:
                raise _route_parse_error(
                    data_plane_file,
                    line_number,
                    line,
                    str(exc),
                ) from exc
    return routes


def load_bgp_routes(work_dir: Path) -> Dict[str, List[BgpRoute]]:
    """Load supplemental BGP routes keyed by ``{node}_{network}``."""
    bgp_file = work_dir / util_keyword.BGP_ROUTES_FILE
    logger.info("Loading BGP routes from %s", bgp_file)

    routes_by_key: Dict[str, List[BgpRoute]] = defaultdict(list)
    with bgp_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "Node" in line and "VRF" in line:
                continue
            if "=" in line and len(line) > 50:
                continue

            parts = line.split()
            if len(parts) < 10:
                raise _route_parse_error(
                    bgp_file,
                    line_number,
                    line,
                    "expected at least 10 fields",
                )
            try:
                route, route_key = _parse_bgp_route(parts)
            except (ValueError, IndexError) as exc:
                raise _route_parse_error(
                    bgp_file,
                    line_number,
                    line,
                    str(exc),
                ) from exc
            routes_by_key[route_key].append(route)
    return dict(routes_by_key)


def load_overall_attributes(work_dir: Path) -> Dict[str, FrozenSet[str]]:
    """Load the OVERALL_BEST attributes referenced for each device."""
    input_file = work_dir / util_keyword.OVERALL_ATTRIBUTES_FILE
    variable_prefixes = "|".join(
        re.escape(prefix)
        for prefix in (
            util_keyword.SMT_VAR_DEFAULT_PREFIX,
            util_keyword.SMT_VAR_MODEL_IGP_PREFIX,
        )
    )
    overall_best_infix = (
        f"_{util_keyword.SMT_OVERALL_BEST_TOKEN}_None_"
    )
    variable_pattern = re.compile(
        rf"^\|(?:{variable_prefixes})(.+?)"
        rf"{re.escape(overall_best_infix)}([^|]+)\|$"
    )
    attributes_by_device: Dict[str, Set[str]] = defaultdict(set)

    with input_file.open("r", encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = variable_pattern.fullmatch(line)
            if match is None:
                logger.warning(
                    "Malformed OVERALL_BEST variable at %s:%s: %s",
                    input_file,
                    line_number,
                    line,
                )
                raise ValueError(
                    f"Cannot parse {util_keyword.OVERALL_ATTRIBUTES_FILE} line "
                    f"{line_number}"
                )
            device, attribute = match.groups()
            if attribute not in util_keyword.OVERALL_BEST_ATTRIBUTES:
                logger.warning(
                    "Unknown OVERALL_BEST attribute at %s:%s: %s",
                    input_file,
                    line_number,
                    attribute,
                )
                raise ValueError(
                    f"Unsupported attribute in {util_keyword.OVERALL_ATTRIBUTES_FILE}: "
                    f"{attribute}"
                )
            attributes_by_device[device].add(attribute)

    return {
        device: frozenset(attributes)
        for device, attributes in attributes_by_device.items()
    }


def _parse_bgp_route(parts: List[str]) -> Tuple[BgpRoute, str]:
    """Parse one tokenized supplemental BGP route."""
    node, vrf, network, protocol, next_hop = parts[:5]
    as_path_text, index = _consume_bracket_field(parts, 5)
    as_path = (
        [int(item.strip()) for item in as_path_text.split(",")]
        if as_path_text
        else []
    )
    communities: List[str] = []
    community_text, index = _consume_bracket_field(parts, index)
    if community_text:
        communities = [
            item.strip()
            for item in community_text.split(",")
            if item.strip() and ":" in item
        ]

    numeric_tail = [int(item) for item in parts[index:]]
    if len(numeric_tail) != 3:
        raise ValueError(
            "Expected LocalPreference, Med, and Weight after communities"
        )
    local_preference, med, weight = numeric_tail

    route = BgpRoute(
        node=node,
        vrf=vrf,
        network=network,
        protocol=protocol,
        next_hop=next_hop,
        aspath=as_path,
        communities=communities,
        local_pref=local_preference,
        med=med,
        weight=weight,
    )
    return route, f"{node}_{network}"


def _consume_bracket_field(
    parts: List[str],
    start: int,
) -> Tuple[Optional[str], int]:
    """Consume a whitespace-separated ``[...]`` field."""
    if start >= len(parts) or not parts[start].startswith("["):
        return None, start

    bracket_parts: List[str] = []
    index = start
    while index < len(parts):
        bracket_parts.append(parts[index])
        if parts[index].endswith("]"):
            index += 1
            break
        index += 1

    raw_value = " ".join(bracket_parts)
    if raw_value.startswith("[") and raw_value.endswith("]"):
        return raw_value[1:-1].strip(), index
    return None, start


def load_ospf_routes(work_dir: Path) -> Dict[str, List[OspfRoute]]:
    """Load supplemental OSPF routes keyed by ``{node}_{network}``."""
    ospf_file = work_dir / util_keyword.OSPF_ROUTES_FILE
    logger.info("Loading OSPF routes from %s", ospf_file)

    routes_by_key: Dict[str, List[OspfRoute]] = defaultdict(list)
    with ospf_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "Node" in line and "VRF" in line:
                continue
            if "=" in line and len(line) > 50:
                continue

            parts = line.split()
            if len(parts) != 8:
                raise _route_parse_error(
                    ospf_file,
                    line_number,
                    line,
                    "expected exactly 8 fields",
                )
            try:
                route, route_key = _parse_ospf_route(parts)
            except (ValueError, IndexError) as exc:
                raise _route_parse_error(
                    ospf_file,
                    line_number,
                    line,
                    str(exc),
                ) from exc
            routes_by_key[route_key].append(route)
    return dict(routes_by_key)


def _parse_ospf_route(parts: List[str]) -> Tuple[OspfRoute, str]:
    """Parse one tokenized supplemental OSPF route."""
    (
        node,
        vrf,
        network,
        route_type,
        area_text,
        metric_text,
        path_cost_text,
        next_hop,
    ) = parts
    area = None if area_text == "-" else int(area_text)
    route = OspfRoute(
        node=node,
        vrf=vrf,
        network=network,
        route_type=route_type,
        area=area,
        metric=int(metric_text),
        path_cost=int(path_cost_text),
        next_hop=next_hop,
    )
    return route, f"{node}_{network}"


def load_target_prefixes(work_dir: Path) -> List[str]:
    """Load target IPs or prefixes from 0_dst_ips.txt."""
    target_file = work_dir / util_keyword.DST_IPS_FILE
    logger.info("Loading destination IPs from %s", target_file)
    with target_file.open("r", encoding="utf-8") as input_file:
        target_prefixes = [
            line
            for raw_line in input_file
            if (line := raw_line.strip()) and not line.startswith("#")
        ]
    logger.info(
        "Loaded %s destination IPs: %s",
        len(target_prefixes),
        target_prefixes,
    )
    return target_prefixes


def load_bgp_peers(work_dir: Path) -> BgpPeerTables:
    """Load directed BGP neighbor interfaces and session AS numbers."""
    tables = BgpPeerTables()
    peers_file = work_dir / util_keyword.BGP_PEERS_FILE
    if not peers_file.is_file():
        logger.warning("BGP peers file not found: %s", peers_file)
        return tables

    logger.info("Loading BGP peers from %s", peers_file)
    with peers_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                if "->" not in line:
                    raise ValueError("expected '->' between peer endpoints")
                left, right = line.split("->", 1)
                left_device, left_interface, left_as = _parse_neighbor_endpoint(left)
                right_device, _, right_as = _parse_neighbor_endpoint(
                    right
                )
                if left_as is None or right_as is None:
                    raise ValueError("BGP peer endpoints must include AS numbers")
                _store_peer_interface(
                    tables,
                    left_device,
                    right_device,
                    left_interface,
                )
                tables.autonomous_systems.setdefault(
                    (left_device, right_device), set()
                ).add((left_as, right_as))
            except (ValueError, IndexError) as exc:
                raise _peer_parse_error(
                    peers_file, line_number, line, str(exc)
                ) from exc

    logger.info("Loaded %s BGP peer mappings", len(tables.interfaces))
    return tables


def load_ospf_peers(work_dir: Path) -> OspfPeerTables:
    """Load directed OSPF neighbor and interface mappings."""
    tables = OspfPeerTables()
    peers_file = work_dir / util_keyword.OSPF_PEERS_FILE
    if not peers_file.is_file():
        logger.warning("OSPF peers file not found: %s", peers_file)
        return tables

    logger.info("Loading OSPF peers from %s", peers_file)
    with peers_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                if "->" not in line:
                    raise ValueError("expected '->' between peer endpoints")
                left, right = line.split("->", 1)
                left_device, left_interface, _ = _parse_neighbor_endpoint(left)
                right_device, _, _ = _parse_neighbor_endpoint(right)
                _store_peer_interface(
                    tables,
                    left_device,
                    right_device,
                    left_interface,
                )
            except (ValueError, IndexError) as exc:
                raise _peer_parse_error(
                    peers_file, line_number, line, str(exc)
                ) from exc

    logger.info("Loaded %s OSPF peer mappings", len(tables.interfaces))
    return tables


def _peer_parse_error(
    file_path: Path,
    line_number: int,
    line: str,
    reason: str,
) -> ValueError:
    message = (
        f"Error parsing peer file {file_path} at line {line_number}: "
        f"{reason}: {line}"
    )
    logger.warning(message)
    return ValueError(message)


def _store_peer_interface(
    tables: PeerTables,
    device: str,
    peer: str,
    interface: str,
) -> None:
    tables.interfaces.setdefault((device, peer), set()).add(interface)


def _store_unique_peer_value(
    mapping: MutableMapping[_KeyT, _ValueT],
    key: _KeyT,
    value: _ValueT,
    field_name: str,
) -> None:
    existing = mapping.get(key)
    if existing is not None and existing != value:
        raise ValueError(
            f"conflicting {field_name} for {key}: {existing} and {value}"
        )
    mapping[key] = value


def _parse_neighbor_endpoint(
    endpoint: str,
) -> Tuple[str, str, Optional[int]]:
    """Parse ``device,interface (asn)`` from one side of a neighbor line."""
    device, remainder = endpoint.strip().split(",", 1)
    interface = remainder.split("(", 1)[0].strip()
    device = device.strip()
    if not device or not interface:
        raise ValueError("peer endpoint requires a device and interface")
    as_number = None
    match = re.search(r"\((\d+)\)", remainder)
    if match:
        as_number = int(match.group(1))
    return device, interface, as_number


def load_unused_control_forwarding_variables(work_dir: Path) -> Set[str]:
    """Load unused CONTROL-FORWARDING SMT variable names."""
    unused_file = work_dir / util_keyword.CONTROLFWD_IGNORES_FILE
    if not unused_file.is_file():
        logger.info("No unused control forwarding file found")
        return set()

    logger.info("Loading unused control forwarding variables from %s", unused_file)
    with unused_file.open("r", encoding="utf-8") as input_file:
        unused = {
            line
            for raw_line in input_file
            if (line := raw_line.strip()) and not line.startswith("#")
        }
    logger.info("Loaded %s unused control forwarding variables", len(unused))
    logger.info(
        "Extracted %s unused control forwarding: %s",
        len(unused),
        sorted(unused),
    )
    return unused


def load_history_enums(work_dir: Path) -> HistoryEnumTables:
    """Load history enum values and per-device bit widths."""
    history_file = work_dir / util_keyword.HISTORY_ENUMS_FILE
    logger.info("Loading history enums from %s", history_file)

    tables = HistoryEnumTables()
    current_device: Optional[str] = None
    current_enum: Dict[str, Optional[int]] = {}
    current_bit_width: Optional[int] = None

    with history_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if (
                line.startswith("|")
                and util_keyword.SMT_ATTR_HISTORY_VAR_SUFFIX in line
            ):
                _store_history_table(
                    tables,
                    current_device,
                    current_enum,
                    current_bit_width,
                )
                current_device, current_bit_width = _parse_history_header(line)
                current_enum = {}
                continue
            if current_device and current_bit_width and ":" in line:
                protocol, value_text = line.split(":", 1)
                if value_text.strip().lower() == "null":
                    current_enum[protocol.strip()] = None
                    continue
                try:
                    current_enum[protocol.strip()] = int(value_text.strip())
                except ValueError:
                    logger.warning(
                        "Invalid history enum value at line %s: %s",
                        line_number,
                        line,
                    )

    _store_history_table(
        tables,
        current_device,
        current_enum,
        current_bit_width,
    )
    logger.info(
        "Loaded history enums for %s devices: %s",
        len(tables.enums),
        list(tables.enums),
    )
    logger.info("Loaded history bit widths: %s", tables.bit_widths)
    return tables


def _parse_history_header(
    line: str,
) -> Tuple[Optional[str], Optional[int]]:
    """Extract device and bit width from a history variable header."""
    bit_width_match = re.search(r"\((\d+)\)", line)
    if not bit_width_match:
        return None, None
    bit_width = int(bit_width_match.group(1))
    if bit_width <= 0:
        return None, None

    variable = line.split("(", 1)[0].strip()
    if not (variable.startswith("|") and variable.endswith("|")):
        return None, None
    inner = variable[1:-1]
    for prefix in (
        util_keyword.SMT_VAR_MODEL_IGP_PREFIX,
        util_keyword.SMT_VAR_DEFAULT_PREFIX,
    ):
        if inner.startswith(prefix):
            inner = inner[len(prefix) :]
            break
    else:
        return None, None

    suffix = util_keyword.SMT_ATTR_HISTORY_VAR_SUFFIX
    if not inner.endswith(suffix):
        return None, None
    return inner[: -len(suffix)], bit_width


def _store_history_table(
    tables: HistoryEnumTables,
    device: Optional[str],
    values: Dict[str, Optional[int]],
    bit_width: Optional[int],
) -> None:
    """Store a complete history block when it contains usable values."""
    if device and values and bit_width and bit_width > 0:
        tables.enums[device] = values
        tables.bit_widths[device] = bit_width


def load_interfaces(work_dir: Path) -> Dict[str, Set[str]]:
    """Load ``device,interface`` entries from 0_interfaces.txt."""
    interfaces_file = work_dir / util_keyword.INTERFACES_FILE
    logger.info("Loading interfaces from %s", interfaces_file)

    interfaces: Dict[str, Set[str]] = {}
    with interfaces_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "," not in line:
                logger.warning(
                    "Skip interface line %s: expected 'device,interface': %s",
                    line_number,
                    line,
                )
                continue
            device, interface = (part.strip() for part in line.split(",", 1))
            if device and interface:
                interfaces.setdefault(device, set()).add(interface)
    logger.info("Loaded interfaces for %s devices", len(interfaces))
    return interfaces


def load_smt_source_lines(file_path: Path) -> List[str]:
    """Load an SMT-LIB source file as text lines."""
    try:
        return file_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Failed to load SMT file {file_path}: {exc}") from exc


def load_config_variables_from_smt(file_path: Path) -> List[ConfigVariable]:
    """Load active or commented simple ``Config_*`` equality assertions."""
    variables: List[ConfigVariable] = []
    for line_number, line in enumerate(load_text_lines(file_path), 1):
        parsed = util_smt.parse_config_equality_assertion(line)
        if not parsed:
            continue
        config_name, config_value = parsed
        variables.append(
            ConfigVariable(
                name=config_name,
                value=config_value,
                line_number=line_number,
                file_path=str(file_path),
            )
        )
    return variables


def load_key_prefixlists(
    work_dir: Path,
) -> Tuple[Set[str], Dict[str, List[int]]]:
    """Load key RouteFilterList lines and index their line numbers by base name."""
    source_file = work_dir / util_keyword.KEY_PREFIXLISTS_FILE
    if not source_file.is_file():
        raise FileNotFoundError(f"Key prefix-list file not found: {source_file}")

    prefixes = set(load_data_lines(source_file))
    by_base: Dict[str, List[int]] = {}
    pattern = re.compile(r"(Config_\S+_RouteFilterList_\S+)__Line(\d+)$")
    for prefix in prefixes:
        match = pattern.search(prefix)
        if match:
            by_base.setdefault(match.group(1), []).append(int(match.group(2)))
    for line_numbers in by_base.values():
        line_numbers.sort()
    return prefixes, by_base


def load_line_config_equalities(
    sliced_file: Path, line_prefix: str
) -> List[str]:
    """Load commented Config equality assertions belonging to one config line."""
    if not sliced_file.is_file():
        return []
    return [
        f"; (assert (= {config_var.name} {config_var.value}))"
        for config_var in load_config_variables_from_smt(sliced_file)
        if config_var.name == line_prefix
        or config_var.name.startswith(f"{line_prefix}__")
    ]


def copy_line_synthesis_metadata(
    source_file: Path,
    output_file: Path,
    source_line_prefix: str,
    target_line_prefix: str,
    target_equalities: Sequence[str],
) -> None:
    """Copy line metadata while replacing its identifier and equality section."""
    content = load_text(source_file)
    equality_start = content.find("; All commented Config variable assignments")
    if equality_start == -1:
        equality_start = content.find("; (assert (= Config_")
    if equality_start != -1 and target_equalities:
        summary_start = content.find(
            "; " + "=" * 78,
            equality_start,
        )
        if summary_start == -1:
            summary_start = len(content)
        equality_header = (
            "; All commented Config variable assignments "
            ";(assert (= Config_XXX value))\n"
            "; " + "-" * 78 + "\n"
        )
        content = (
            content[:equality_start]
            + equality_header
            + "\n".join(target_equalities)
            + "\n"
            + content[summary_start:]
        )

    content = content.replace(
        f"; Identifier: {source_line_prefix}",
        f"; Identifier: {target_line_prefix}",
    ).replace(
        f"; Identifier: {safe_filename_component(source_line_prefix)}",
        f"; Identifier: {safe_filename_component(target_line_prefix)}",
    )
    if target_equalities:
        summary = (
            f"; Summary: {content.count('(declare-fun')} declare-fun declarations, "
            f"{len(target_equalities)} commented Config assignments"
        )
        content = re.sub(
            r"; Summary: \d+ declare-fun declarations, "
            r"\d+ commented Config assignments",
            summary,
            content,
        )
    write_text(output_file, content)


def load_target_smt_variables(file_path: Path) -> Set[str]:
    """Load distinct SMT variables used as dependency-slice roots."""
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(
            f"Failed to load target SMT variables from {file_path}: {exc}"
        ) from exc

    variables = set()
    for line_number, raw_line in enumerate(lines, 1):
        variable = raw_line.strip()
        if not variable or variable.startswith(("#", ";")):
            continue
        parsed_variables = util_smt.extract_smt_symbolic_variables(variable)
        if parsed_variables != [variable]:
            raise ValueError(
                f"Expected one SMT variable at {file_path}:{line_number}, "
                f"found: {raw_line}"
            )
        if variable in variables:
            raise ValueError(
                f"Duplicate SMT variable {variable} at "
                f"{file_path}:{line_number}"
            )
        variables.add(variable)

    if not variables:
        raise ValueError(f"No target SMT variables found in {file_path}")
    return variables


def load_router_local_encoding(work_dir: Path, router: str) -> str:
    """Load the stage-2 SMT encoding for one router."""
    encoding_file = (
        work_dir
        / util_keyword.ROUTER_LOCAL_ENCODING_DIR
        / router_local_encoding_file_name(router)
    )
    if not encoding_file.is_file():
        raise FileNotFoundError(f"Router-local SMT file not found: {encoding_file}")
    return encoding_file.read_text(encoding="utf-8")


def load_consistency_encoding(
    work_dir: Path,
    router: str,
    *,
    satisfaction: bool,
) -> str:
    """Load one generated stage-3 consistency-check SMT encoding."""
    file_name = (
        satisfaction_check_file_name(router)
        if satisfaction
        else violation_check_file_name(router)
    )
    encoding_file = work_dir / util_keyword.CONSISTENCY_CHECK_DIR / file_name
    if not encoding_file.is_file():
        direction = "satisfaction" if satisfaction else "violation"
        raise FileNotFoundError(
            f"{direction.title()} consistency encoding not found: {encoding_file}"
        )
    return encoding_file.read_text(encoding="utf-8")


def load_routers_from_local_encodings(work_dir: Path) -> List[str]:
    """Discover router names from stage-2 per-router SMT files."""
    router_local_dir = work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
    routers = []
    prefix = f"{util_keyword.LOCAL_ENCODING_FILE_PREFIX}_"
    for encoding_file in router_local_dir.glob(f"{prefix}*.smt2"):
        router = encoding_file.stem.removeprefix(prefix)
        routers.append(router)
    return sorted(routers)


def load_consistency_routers(
    work_dir: Path,
    router_filter: Optional[str] = None,
) -> List[str]:
    """Load stage-3 routers from existing checks or stage-2 encodings."""
    consistency_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    routers = []

    if consistency_dir.is_dir():
        prefix = f"{util_keyword.SATISFACTION_CHECK_FILE_PREFIX}_"
        for satisfaction_file in consistency_dir.glob(f"{prefix}*.smt2"):
            router = satisfaction_file.stem.removeprefix(
                prefix
            )
            if router_filter is None or router == router_filter:
                routers.append(router)

    if not routers:
        routers = [
            router
            for router in load_routers_from_local_encodings(work_dir)
            if router_filter is None or router == router_filter
        ]

    if router_filter and not routers:
        valid_routers = load_hostnames(work_dir)
        if router_filter not in valid_routers:
            raise ValueError(
                f"Router '{router_filter}' not found in "
                f"{util_keyword.HOSTNAMES_FILE}\n"
                f"Available routers: {', '.join(valid_routers)}"
            )
        routers = [router_filter]

    return sorted(routers)


def load_existing_consistency_routers(
    work_dir: Path,
    router_filter: Optional[str] = None,
) -> List[str]:
    """Discover routers from existing satisfaction and violation checks."""
    consistency_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    routers: Set[str] = set()
    prefixes = (
        f"{util_keyword.SATISFACTION_CHECK_FILE_PREFIX}_",
        f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_",
    )
    for prefix in prefixes:
        for encoding_file in consistency_dir.glob(f"{prefix}*.smt2"):
            routers.add(encoding_file.stem.removeprefix(prefix))

    if router_filter is not None:
        if router_filter not in routers:
            raise ValueError(
                f"Device '{router_filter}' not found in {consistency_dir} "
                f"(available: {', '.join(sorted(routers))})"
            )
        return [router_filter]
    return sorted(routers)


def patch_internet2_violation_encoding(
    encoding_file: Path,
    *,
    dry_run: bool = False,
) -> Tuple[str, int]:
    """Patch one Internet2 violation check with disabled EXPORT_ENV routes."""
    prefix = f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_"
    if not encoding_file.name.startswith(prefix) or encoding_file.suffix != ".smt2":
        raise ValueError(f"Unexpected violation filename: {encoding_file.name}")
    device = encoding_file.stem.removeprefix(prefix)
    original = load_text(encoding_file)
    updated, assertion_count = util_smt.patch_internet2_export_env_assumptions(
        original,
        device,
    )
    if not assertion_count:
        logger.info(
            "%s: no BGP_EXPORT_ENV *_permitted variables, skipped",
            encoding_file.name,
        )
        return device, 0
    if updated == original:
        logger.info(
            "%s: already up to date (%d asserts)",
            encoding_file.name,
            assertion_count,
        )
        return device, assertion_count
    if dry_run:
        logger.info(
            "%s: would add %d EXPORT_ENV asserts",
            encoding_file.name,
            assertion_count,
        )
        return device, assertion_count
    write_text(encoding_file, updated)
    logger.info(
        "%s: added %d EXPORT_ENV asserts",
        encoding_file.name,
        assertion_count,
    )
    return device, assertion_count


def patch_internet2_violation_encodings(
    work_dir: Path,
    *,
    router_filter: Optional[str] = None,
    dry_run: bool = False,
) -> Internet2PatchSummary:
    """Patch selected Internet2 violation checks and return a summary."""
    consistency_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    violation_files = sorted(
        consistency_dir.glob(
            f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_*.smt2"
        )
    )
    if router_filter is not None:
        expected_name = (
            f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_{router_filter}.smt2"
        )
        violation_files = [
            path for path in violation_files if path.name == expected_name
        ]
    if not violation_files:
        logger.error(
            "No matching %s*.smt2 files found in %s",
            util_keyword.VIOLATION_CHECK_FILE_PREFIX,
            consistency_dir,
        )
        return Internet2PatchSummary(errors=1)

    processed_files = 0
    inserted_assertions = 0
    skipped_files = 0
    errors = 0
    for violation_file in violation_files:
        try:
            _, assertion_count = patch_internet2_violation_encoding(
                violation_file,
                dry_run=dry_run,
            )
            processed_files += 1
            inserted_assertions += assertion_count
            skipped_files += assertion_count == 0
        except Exception as error:
            errors += 1
            logger.error("%s: %s", violation_file.name, error)
    return Internet2PatchSummary(
        processed_files=processed_files,
        inserted_assertions=inserted_assertions,
        skipped_files=skipped_files,
        errors=errors,
    )


def reconstruct_internet2_constraints_from_model(
    work_dir: Path,
    router: str,
    model: Dict[str, str],
) -> Internet2ReconstructionResult:
    """Apply a reverse-SAT model directly to final assume-guarantee files."""
    output_dir = work_dir / util_keyword.ROUTER_LEVEL_SUBSPEC_DIR
    output_files = (
        require_file(
            output_dir
            / assume_guarantee_file_name(router, satisfaction=True)
        ),
        require_file(
            output_dir
            / assume_guarantee_file_name(router, satisfaction=False)
        ),
    )
    contents = {output_file: load_text(output_file) for output_file in output_files}
    router_token = f"_{router}_"
    target_variables = {
        variable
        for content in contents.values()
        for variable in util_smt.extract_internet2_constraint_variables(content)
        if router_token in variable
    }
    scoped_model = {
        variable: model[variable]
        for variable in target_variables
        if variable in model
    }
    missing_variables = tuple(
        sorted(variable for variable in target_variables if variable not in model)
    )

    changed_values = 0
    updated_variables: Set[str] = set()
    for output_file, content in contents.items():
        updated_content, file_changes = util_smt.update_equality_values(
            content,
            scoped_model,
        )
        if file_changes:
            updated_content = util_smt.mark_internet2_model_refinement(
                updated_content
            )
            write_text(output_file, updated_content)
            changed_values += file_changes
            updated_variables.update(
                variable
                for variable in scoped_model
                if variable in updated_content
            )

    return Internet2ReconstructionResult(
        changed_values=changed_values,
        updated_variables=tuple(sorted(updated_variables)),
        matched_variables=len(scoped_model),
        total_variables=len(target_variables),
        missing_variables=missing_variables,
    )


def load_router_assume_guarantee(
    work_dir: Path,
    router: str,
    *,
    satisfaction: bool,
) -> str:
    """Load one required stage-1 assume-guarantee constraint fragment."""
    fragment_file = (
        work_dir
        / util_keyword.ROUTER_LEVEL_SUBSPEC_DIR
        / assume_guarantee_file_name(router, satisfaction=satisfaction)
    )
    if not fragment_file.is_file():
        direction = "Satisfaction" if satisfaction else "Violation"
        raise FileNotFoundError(
            f"{direction} assume-guarantee fragment not found: {fragment_file}"
        )
    return fragment_file.read_text(encoding="utf-8")


def update_router_assume_guarantee_declarations(
    work_dir: Path,
    router: str,
    available_declarations: Dict[str, str],
) -> int:
    """Add declarations absent from one router's local encoding to its AG files."""
    local_encoding = load_router_local_encoding(work_dir, router)
    updated_files = 0
    for satisfaction in (True, False):
        fragment_file = (
            work_dir
            / util_keyword.ROUTER_LEVEL_SUBSPEC_DIR
            / assume_guarantee_file_name(router, satisfaction=satisfaction)
        )
        if not fragment_file.is_file():
            continue
        content = load_text(fragment_file)
        updated_content = util_smt.add_assume_guarantee_declarations(
            content,
            local_encoding,
            available_declarations,
        )
        if updated_content != content:
            write_text(fragment_file, updated_content)
            updated_files += 1
    return updated_files


def load_target_dst_ip(work_dir: Path) -> Optional[str]:
    """Load the first target entry from 0_dst_ips.txt when available."""
    target_file = work_dir / util_keyword.DST_IPS_FILE
    if not target_file.is_file():
        return None

    try:
        with target_file.open("r", encoding="utf-8") as input_file:
            target = input_file.readline().strip()
    except OSError as exc:
        logger.warning(f"Failed to read {target_file}: {exc}")
        return None

    if target:
        logger.info(f"Loaded target_dst_ip from {target_file}: {target}")
        return target
    return None


def load_hostnames(work_dir: Path) -> List[str]:
    """Load non-empty device names from 0_hostnames.txt."""
    hostnames_file = work_dir / util_keyword.HOSTNAMES_FILE
    if not hostnames_file.is_file():
        raise FileNotFoundError(f"Hostnames file not found: {hostnames_file}")

    devices = []
    first_line_by_device = {}
    with hostnames_file.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, 1):
            device = raw_line.strip()
            if not device:
                continue
            first_line = first_line_by_device.get(device)
            if first_line is not None:
                raise ValueError(
                    f"Duplicate hostname {device!r} in {hostnames_file} at "
                    f"lines {first_line} and {line_number}"
                )
            first_line_by_device[device] = line_number
            devices.append(device)

    if not devices:
        raise ValueError(f"No hostnames found in {hostnames_file}")

    logger.info(f"Loaded {len(devices)} devices from {hostnames_file}: {devices}")
    return devices


def load_device_info(
    work_dir: Path,
    device_filter: Optional[str] = None,
) -> List[str]:
    """Load device information from router-local SMT files."""
    logger.info("Loading device information...")

    if device_filter:
        hostnames_file = work_dir / util_keyword.HOSTNAMES_FILE
        valid_devices = []

        if hostnames_file.is_file():
            valid_devices = load_hostnames(work_dir)

            if device_filter not in valid_devices:
                error_msg = f"Device '{device_filter}' not found in {util_keyword.HOSTNAMES_FILE}\n"
                error_msg += f"Available devices: {', '.join(valid_devices)}"
                raise ValueError(error_msg)
            logger.info(f"Device '{device_filter}' validated against {util_keyword.HOSTNAMES_FILE}")
        else:
            logger.warning(
                f"{util_keyword.HOSTNAMES_FILE} not found, will validate device "
                "from router-local SMT files"
            )

    router_local_dir = work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
    if not router_local_dir.is_dir():
        raise FileNotFoundError(
            f"Router-local SMT directory not found: {router_local_dir}"
        )

    prefix = f"{util_keyword.LOCAL_ENCODING_FILE_PREFIX}_"
    smt_files = list(router_local_dir.glob(f"{prefix}*.smt2"))
    devices = []
    all_devices_from_smt = []

    for smt_file in smt_files:
        if smt_file.name.startswith(prefix):
            device = smt_file.stem.removeprefix(prefix)
            all_devices_from_smt.append(device)
            if device_filter is None or device == device_filter:
                devices.append(device)

    if device_filter:
        if not devices:
            error_msg = (
                f"Device '{device_filter}' not found in router-local SMT files\n"
            )
            if all_devices_from_smt:
                error_msg += f"Available devices from SMT files: {', '.join(sorted(set(all_devices_from_smt)))}"
            raise ValueError(error_msg)
        logger.info(f"Filtered to device: {devices[0]}")
    else:
        logger.info(f"Found {len(devices)} devices: {devices}")

    return devices


# ============================================================================
# Save Functions
# ============================================================================

def write_smt_expressions(
    output_file: Path,
    expressions: List[str],
) -> None:
    """Write one SMT expression per line."""
    with output_file.open("w", encoding="utf-8") as output:
        for expression in expressions:
            output.write(f"{expression}\n")


def write_router_local_encoding(
    output_dir: Path,
    router: str,
    declarations: List[str],
    assertions: List[str],
) -> Path:
    """Write one stage-2 router-local SMT encoding."""
    output_file = output_dir / router_local_encoding_file_name(router)
    with output_file.open("w", encoding="utf-8") as output:
        output.write("; ---- Declarations ----\n")
        for declaration in declarations:
            output.write(f"{declaration}\n")
        output.write("\n; ---- Assertions ----\n")
        for assertion in assertions:
            output.write(f"{assertion}\n")
    return output_file


def write_consistency_encoding(
    work_dir: Path,
    router: str,
    content: str,
    *,
    satisfaction: bool,
) -> Path:
    """Write one stage-3 satisfaction or violation SMT check file."""
    output_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    output_dir.mkdir(exist_ok=True)
    file_name = (
        satisfaction_check_file_name(router)
        if satisfaction
        else violation_check_file_name(router)
    )
    output_file = output_dir / file_name
    output_file.write_text(content, encoding="utf-8")
    return output_file


def write_consistency_summary(
    work_dir: Path,
    lines: List[str],
    router_filter: Optional[str] = None,
) -> Path:
    """Write the stage-3 consistency-check summary."""
    output_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    output_dir.mkdir(exist_ok=True)
    if router_filter:
        stem = util_keyword.CONSISTENCY_CHECK_FILE.removesuffix(".txt")
        output_file = output_dir / f"{stem}_{router_filter}.txt"
    else:
        output_file = output_dir / util_keyword.CONSISTENCY_CHECK_FILE
    output_file.write_text("\n".join(lines), encoding="utf-8")
    return output_file


def write_router_level_analysis_report(
    work_dir: Path,
    report: RouterLevelAnalysisReport,
) -> None:
    """Write final per-router assume-guarantee constraint fragments."""
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: Extracting device-specific constraints")
    logger.info("=" * 60)

    output_dir = work_dir / util_keyword.ROUTER_LEVEL_SUBSPEC_DIR
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir()
    logger.info(f"Device-specific constraints extracted to: {output_dir}")

    normal_routes: Dict[str, str] = {}
    normal_stable_states: Dict[str, str] = {}
    combined_negated_constraints: Dict[str, str] = {}

    for device, analysis in sorted(report.routers.items()):
        logger.info(f"Processing device: {device}")
        normal_route = [
            item.render() for item in analysis.normal_route_constraints
        ]
        normal_stable = [
            item.render() for item in analysis.normal_control_constraints
        ]
        negated_stable = [
            item.render() for item in analysis.negated_control_constraints
        ]
        negated_route = [
            item.render() for item in analysis.negated_route_constraints
        ]
        prefix_bounds = [item.render() for item in analysis.prefix_length_bounds]

        normal_routes[device] = _render_constraints(normal_route)
        normal_stable_states[device] = _render_constraints(normal_stable)
        combined_negated_constraints[device] = (
            _render_combined_negated_constraint(
                normal_stable,
                negated_stable,
                negated_route,
                prefix_bounds,
            )
        )
    _write_assume_guarantee_fragments(
        output_dir,
        report,
        normal_routes,
        normal_stable_states,
        combined_negated_constraints,
    )
    logger.info(
        "Final assume-guarantee files created for: %s",
        sorted(report.routers),
    )


def _render_constraints(constraints: List[str]) -> str:
    return "".join(f"{constraint}\n" for constraint in constraints)


def _render_combined_negated_constraint(
    normal_stable: List[str],
    negated_stable: List[str],
    negated_route: List[str],
    prefix_bounds: List[str],
) -> str:
    expression = util_smt.build_combined_negated_constraint(
        normal_stable,
        negated_stable,
        negated_route,
    )
    bounds = "".join(f"{bound}\n" for bound in prefix_bounds)
    return f"(assert {expression})\n{bounds}"


def _write_assume_guarantee_fragments(
    output_dir: Path,
    report: RouterLevelAnalysisReport,
    normal_routes: Dict[str, str],
    normal_stable_states: Dict[str, str],
    combined_negated_constraints: Dict[str, str],
) -> None:
    """Write peer assumptions with normal and negated local guarantees."""
    for device in sorted(report.routers):
        peer_variables = report.peer_control_variables.get(device, {})
        # Every routing peer contributes its OVERALL_BEST route assumption.
        peer_route_assumptions = []
        for peer in sorted(peer_variables):
            peer_analysis = report.routers.get(peer)
            if peer_analysis is None:
                raise ValueError(
                    f"Cannot build assume-guarantee for router '{device}': "
                    f"peer '{peer}' has no router-level analysis"
                )
            peer_route_assumptions.append(
                (
                    peer,
                    util_smt.build_peer_route_assumption_constraints(
                        device,
                        peer,
                        peer_variables[peer],
                        peer_analysis.route_assumption_cases,
                        peer_analysis.normal_control_constraints,
                    ),
                )
            )
        # Satisfaction requires the expected local best route and forwarding.
        satisfaction_content = (
            util_smt.build_satisfaction_assume_guarantee_constraints(
                peer_route_assumptions,
                normal_routes[device],
                normal_stable_states[device],
            )
        )
        # Violation requires the negation of the expected local behavior.
        violation_content = util_smt.build_violation_assume_guarantee_constraints(
            peer_route_assumptions,
            combined_negated_constraints[device],
        )
        write_text(
            output_dir
            / assume_guarantee_file_name(device, satisfaction=True),
            satisfaction_content,
        )
        write_text(
            output_dir
            / assume_guarantee_file_name(device, satisfaction=False),
            violation_content,
        )


def save_synthesis_metadata(
    device: str,
    identifier: str,
    synthesis_file_path: str,
    metadata_dir: Path,
    metadata_type: str = "field",
) -> None:
    """Save synthesis file metadata to file."""
    declare_funs, commented_config_asserts = extract_synthesis_metadata(
        synthesis_file_path
    )

    safe_identifier = safe_filename_component(identifier)
    output_file = (
        metadata_dir
        / f"synthesis_metadata_{metadata_type}_{device}_{safe_identifier}.txt"
    )

    with output_file.open("w", encoding="utf-8") as f:
        f.write(f"; Synthesis file metadata for {metadata_type}-level subspec calculation\n")
        f.write(f"; Device: {device}\n")
        f.write(f"; Identifier: {identifier}\n")
        f.write(f"; Source file: {synthesis_file_path}\n")
        f.write("; " + "="*80 + "\n\n")

        f.write("; All VAR type declarations (declare-fun)\n")
        f.write("; " + "-"*78 + "\n")
        if declare_funs:
            for declare_fun in declare_funs:
                f.write(f"{declare_fun}\n")
        else:
            f.write("; No declare-fun declarations found\n")
        f.write("\n")

        f.write("; All commented Config variable assignments ;(assert (= Config_XXX value))\n")
        f.write("; " + "-"*78 + "\n")
        if commented_config_asserts:
            for commented_assert in commented_config_asserts:
                f.write(f"{commented_assert}\n")
        else:
            f.write("; No commented Config variable assignments found\n")
        f.write("\n")

        f.write("; " + "="*78 + "\n")
        f.write(f"; Summary: {len(declare_funs)} declare-fun declarations, {len(commented_config_asserts)} commented Config assignments\n")

    logger.info(f"    Synthesis metadata saved to: {output_file}")


def save_field_level_subspecs(
    output_file: Path,
    subspecs: Dict[str, Set[str]],
    exclude_config_names: Optional[Set[str]] = None,
) -> None:
    """Save field-level subspecs in the shared grouped text format."""
    if exclude_config_names:
        subspecs = {
            name: values
            for name, values in subspecs.items()
            if name not in exclude_config_names
        }
    _write_grouped_subspecs(
        output_file=output_file,
        title="Field-Level Subspecs",
        underline="====================",
        group_label="Config Variable",
        empty_message="No field-level subspecs found.",
        groups=subspecs,
        drop_mixed_empty=True,
    )


def save_line_level_subspecs(
    output_file: Path,
    line_level_subspecs: Dict[str, Set[str]],
) -> None:
    """Save line-level subspecs in the shared grouped text format."""
    _write_grouped_subspecs(
        output_file=output_file,
        title="Line-Level Subspecs",
        underline="==================",
        group_label="Line Group",
        empty_message="No line-level subspecs found.",
        groups=line_level_subspecs,
        drop_mixed_empty=False,
    )


def save_full_symbolic_field_level_subspecs(
    output_file: Path,
    subspecs: Dict[str, Set[str]],
    exclude_config_names: Optional[Set[str]] = None,
) -> None:
    """Save a full-symbolic field report in the shared historical format."""
    lines = ["Field-Level Subspecs (Full Symbolic)", "====================", ""]
    if not subspecs:
        lines.append("No field-level subspecs found.")
    else:
        for config_name in sorted(subspecs):
            if exclude_config_names and config_name in exclude_config_names:
                continue
            values = subspecs[config_name]
            lines.append(f"Config Variable: {config_name}")
            if values:
                lines.append(f"Subspecs ({len(values)}):")
                lines.extend(
                    f"  {index}. {value}"
                    for index, value in enumerate(sorted(values), 1)
                )
            else:
                lines.append("No subspecs found.")
            lines.extend(["-" * 50, ""])
    write_text(output_file, "\n".join(lines) + "\n")


def save_full_symbolic_line_level_subspecs(
    output_file: Path, line_level_subspecs: Dict[str, Set[str]]
) -> None:
    """Save a full-symbolic line report in the shared historical format."""
    _write_grouped_subspecs(
        output_file=output_file,
        title="Line-Level Subspecs (Full Symbolic)",
        underline="===================",
        group_label="Line Group",
        empty_message="No line-level subspecs found.",
        groups=line_level_subspecs,
        drop_mixed_empty=False,
    )


def _write_grouped_subspecs(
    *,
    output_file: Path,
    title: str,
    underline: str,
    group_label: str,
    empty_message: str,
    groups: Dict[str, Set[str]],
    drop_mixed_empty: bool,
) -> None:
    """Write the common field/line subspec text format."""
    with output_file.open("w", encoding="utf-8") as output:
        output.write(f"{title}\n")
        output.write(f"{underline}\n\n")
        if not groups:
            output.write(f"{empty_message}\n")
            return

        for group_name in sorted(groups):
            values = groups[group_name]
            if (
                drop_mixed_empty
                and "empty" in values
                and any(value != "empty" for value in values)
            ):
                values = {value for value in values if value != "empty"}

            output.write(f"{group_label}: {group_name}\n")
            if values:
                output.write(f"Subspecs ({len(values)}):\n")
                for index, value in enumerate(sorted(values), 1):
                    output.write(f"  {index}. {_display_subspec(value)}\n")
            else:
                output.write("No subspecs found.\n")
            output.write("-" * 50 + "\n\n")


def _display_subspec(value: str) -> str:
    """Convert an internal same-line reference to its persisted display form."""
    if value.startswith("same_as_Line"):
        line_number = value[len("same_as_Line") :]
        return f"same as Line{line_number}"
    return value


def load_line_level_subspecs_from_file(file_path: Path) -> Dict[str, List[str]]:
    """Load line-level subspecs from a line_level_subspecs.txt-format file."""
    parsed = _load_subspecs_from_output_file(file_path, "Line Group")
    return {
        group_name: [
            _normalize_loaded_line_subspec(value)
            for value in values
            if value.lower() != "empty"
        ]
        for group_name, values in parsed.items()
    }


def _normalize_loaded_line_subspec(value: str) -> str:
    """Restore the internal form of a persisted same-line reference."""
    prefix = "same as Line"
    if value.startswith(prefix):
        return f"same_as_Line{value[len(prefix) :].strip()}"
    return value


def _load_subspecs_from_output_file(
    file_path: Path,
    location_label: str,
) -> Dict[str, List[str]]:
    """Parse field_level_subspecs.txt / line_level_subspecs.txt into name -> subspec strings."""
    subspecs: Dict[str, List[str]] = {}
    current_name: Optional[str] = None
    current_subspecs: List[str] = []

    if not file_path.is_file():
        return subspecs

    prefix = f"{location_label}:"
    subspec_line_re = re.compile(r"^\s*\d+\.\s+(.+)$")
    subspec_count_re = re.compile(r"Subspecs\s*\((\d+)\)\s*?:?")

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.error(f"Failed to load subspecs from {file_path}: {exc}")
        return {}

    line_index = 0
    while line_index < len(lines):
        line = lines[line_index].strip()
        line_index += 1
        if line.startswith(prefix):
            if current_name is not None:
                subspecs[current_name] = current_subspecs
            current_name = line[len(prefix) :].strip()
            current_subspecs = []
        elif line.startswith("Subspecs ("):
            count_match = subspec_count_re.match(line)
            if not count_match:
                continue

            subspec_count = int(count_match.group(1))
            for _ in range(subspec_count):
                if line_index >= len(lines):
                    break
                next_line = lines[line_index].strip()
                line_index += 1
                subspec_match = subspec_line_re.match(next_line)
                if subspec_match:
                    current_subspecs.append(subspec_match.group(1).strip())
        elif line.startswith("No subspecs found"):
            current_subspecs = []

    if current_name is not None:
        subspecs[current_name] = current_subspecs
    return subspecs


def load_field_level_subspecs_from_file(file_path: Path) -> Dict[str, List[str]]:
    """Load field-level subspecs from a field_level_subspecs.txt-format file."""
    return _load_subspecs_from_output_file(file_path, "Config Variable")


def nonempty_subspec_location_names(
    file_path: Path,
    *,
    level: str,
) -> Set[str]:
    """Return location names with at least one non-empty subspec entry."""
    if level == "field":
        parsed = _load_subspecs_from_output_file(file_path, "Config Variable")
    elif level == "line":
        parsed = _load_subspecs_from_output_file(file_path, "Line Group")
    else:
        raise ValueError(f"level must be 'field' or 'line', got {level!r}")

    return {
        name
        for name, entries in parsed.items()
        if any(entry.lower() != "empty" for entry in entries)
    }


def delete_subspec_target_intermediates(
    intermediate_dir: Path,
    device: str,
    safe_name: str,
    *,
    extra_safe_names: Optional[List[str]] = None,
) -> List[Path]:
    """Delete check, compute, normalization, and community files for one target."""
    if not intermediate_dir.is_dir():
        return []

    candidates = [
        intermediate_dir / f"check_subspec_from_{device}_{safe_name}.smt2",
        intermediate_dir / f"compute_subspec_from_{device}_{safe_name}.smt2",
        *intermediate_dir.glob(
            f"compute_subspec_from_{device}_{safe_name}_norm_iter*.smt2"
        ),
        *intermediate_dir.glob(
            f"community_replacement_test_{device}_{safe_name}*.smt2"
        ),
    ]
    for extra_name in extra_safe_names or []:
        candidates.extend(
            intermediate_dir.glob(
                f"community_replacement_test_{device}_{extra_name}*.smt2"
            )
        )

    deleted: List[Path] = []
    for path in candidates:
        if delete_file(path):
            deleted.append(path)
    return deleted


def delete_subspec_metadata_files(
    metadata_dir: Path,
    metadata_type: str,
    device: str,
    safe_name: str,
) -> List[Path]:
    """Delete metadata files matching one type/device/target tuple."""
    if not metadata_dir.is_dir():
        return []
    pattern = f"synthesis_metadata_{metadata_type}_{device}_{safe_name}*.txt"
    deleted: List[Path] = []
    for path in sorted(metadata_dir.glob(pattern)):
        if delete_file(path):
            deleted.append(path)
    return deleted


# ============================================================================
# Helper Functions
# ============================================================================

def _delete_directory(directory: Path) -> bool:
    if not directory.exists():
        return False
    shutil.rmtree(directory)
    return True


def _delete_directories(directories: Sequence[Path]) -> List[Path]:
    return [
        directory
        for directory in directories
        if _delete_directory(directory)
    ]


def delete_router_level_outputs(work_dir: Path) -> List[Path]:
    """Delete the stage-1 output directory when present."""
    output_dir = work_dir / util_keyword.ROUTER_LEVEL_SUBSPEC_DIR
    return [output_dir] if _delete_directory(output_dir) else []


def delete_router_local_encoding_outputs(work_dir: Path) -> List[Path]:
    """Delete the stage-2 output directory when present."""
    output_dir = work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
    return [output_dir] if _delete_directory(output_dir) else []


def delete_router_consistency_outputs(
    work_dir: Path,
    router: str,
) -> List[Path]:
    """Delete stage-3 files produced for one router."""
    output_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    candidates = (
        output_dir / satisfaction_check_file_name(router),
        output_dir / violation_check_file_name(router),
        output_dir
        / f"{util_keyword.CONSISTENCY_CHECK_FILE.removesuffix('.txt')}_{router}.txt",
    )
    return [path for path in candidates if delete_file(path)]


def clear_router_local_encoding_files(
    work_dir: Path,
    *,
    preserve_subspec_baseline: bool = True,
) -> List[Path]:
    """Delete Stage 2 encodings, optionally preserving the Stage 6 baseline."""
    output_dir = ensure_directory(
        work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
    )
    deleted: List[Path] = []
    for encoding_file in sorted(output_dir.glob("*.smt2")):
        if (
            preserve_subspec_baseline
            and encoding_file.name == util_keyword.GLOBAL_SUBSPEC_ENCODING_FILE
        ):
            continue
        if delete_file(encoding_file):
            deleted.append(encoding_file)
    return deleted


def delete_consistency_checker_outputs(work_dir: Path) -> List[Path]:
    """Delete all stage-3 consistency-check and subspec outputs."""
    return _delete_directories(
        (
            work_dir / util_keyword.CONSISTENCY_CHECK_DIR,
            work_dir / util_keyword.ROUTEMAP_SUBSPEC_DIR,
        )
    )


def delete_subspec_stage_outputs(
    work_dir: Path,
    stage: int,
    *,
    include_joint: bool = False,
    extra_directory_names: Optional[Sequence[str]] = None,
) -> List[Path]:
    """Delete generated intermediate and final directories for a subspec stage."""
    directory_names = [
        intermediate_directory_name(
            stage, util_keyword.INTERMEDIATE_FIELD_DIR_SUFFIX
        ),
        intermediate_directory_name(
            stage, util_keyword.INTERMEDIATE_LINE_DIR_SUFFIX
        ),
        intermediate_directory_name(
            stage, util_keyword.INTERMEDIATE_METADATA_DIR_SUFFIX
        ),
        subspec_output_directory_name(stage),
    ]
    if include_joint:
        directory_names.append(
            intermediate_directory_name(
                stage, util_keyword.INTERMEDIATE_JOINT_DIR_SUFFIX
            )
        )
    directory_names.extend(extra_directory_names or ())

    return _delete_directories(
        [work_dir / directory_name for directory_name in directory_names]
    )


def get_subspec_output_file_path(
    subspec_files_dir: Path,
    subspec_type: str,
    device_filter: Optional[str] = None,
) -> Path:
    """Get output file path for subspecs."""
    try:
        base_file_name = _SUBSPEC_OUTPUT_FILES[subspec_type]
    except KeyError as exc:
        raise ValueError(f"Unknown subspec type: {subspec_type}") from exc

    if device_filter:
        stem = base_file_name.removesuffix(".txt")
        filename = f"{stem}_{device_filter}.txt"
    else:
        filename = base_file_name

    return subspec_files_dir / filename
