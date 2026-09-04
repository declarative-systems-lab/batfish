#!/usr/bin/env bash
set -euo pipefail

if ((EUID == 0)); then
    echo "Error: Do not run install.sh as root or with sudo." >&2
    echo "Run it as your normal user; the script invokes sudo when required." >&2
    exit 1
fi

OS=$(uname -s)
ARCH=$(uname -m)

if [[ "${OS}" == "Darwin" || "${OS}" == "Linux" ]]; then
    ROOT_DIR=$(cd "$(dirname "$0")" && pwd -P)
else
    echo "Error: install.sh supports Linux and macOS only (detected ${OS})." >&2
    exit 1
fi

SMT_PATH="${ROOT_DIR}/smts"
BAZELRC_PATH="${ROOT_DIR}/.bazelrc"
Z3_VERSION="4.14.0"
Z3_INSTALL_DIR="${HOME}/.local/share/batfish/z3-${Z3_VERSION}"
Z3_BIN_DIR="${Z3_INSTALL_DIR}/bin"
Z3_LINUX_LIB_DIR="${Z3_BIN_DIR}"
BAZELISK_VERSION="1.25.0"
JAVA_REQUIRED_MAJOR="11"
MACOS_MIN_VERSION="14.0.0"
PYTHON_PACKAGES=(
    "ipykernel"
    "matplotlib"
    "notebook"
    "numpy"
    "pandas"
)

echo "Detected system: ${OS} (${ARCH})"

update_managed_block() {
    local file="$1"
    local start_marker="$2"
    local end_marker="$3"
    local start_count end_count temp_file managed_line_1 managed_line_2
    shift 3
    managed_line_1="$1"
    managed_line_2="$2"

    touch "${file}"
    start_count=$(awk -v marker="${start_marker}" '$0 == marker { count++ } END { print count + 0 }' "${file}")
    end_count=$(awk -v marker="${end_marker}" '$0 == marker { count++ } END { print count + 0 }' "${file}")
    if ((start_count != end_count || start_count > 1)); then
        echo "Error: Invalid Batfish-managed block in ${file}." >&2
        echo "Fix or remove the ${start_marker} / ${end_marker} markers and retry." >&2
        exit 1
    fi

    temp_file=$(mktemp "${TEMP_DIR}/shell-profile.XXXXXX")
    if ((start_count == 1)); then
        awk -v start="${start_marker}" -v end="${end_marker}" \
            -v managed1="${managed_line_1}" -v managed2="${managed_line_2}" '
            $0 == start { skipping = 1; next }
            $0 == end { skipping = 0; next }
            $0 == managed1 || $0 == managed2 { next }
            !skipping { print }
        ' "${file}" >"${temp_file}"
    else
        awk -v managed1="${managed_line_1}" -v managed2="${managed_line_2}" '
            $0 != managed1 && $0 != managed2 { print }
        ' "${file}" >"${temp_file}"
    fi

    {
        printf '\n%s\n' "${start_marker}"
        printf '%s\n' "$@"
        printf '%s\n' "${end_marker}"
    } >>"${temp_file}"
    cat "${temp_file}" >"${file}"
}

version_at_least() {
    local current_major current_minor current_patch
    local required_major required_minor required_patch

    IFS=. read -r current_major current_minor current_patch <<<"$1"
    IFS=. read -r required_major required_minor required_patch <<<"$2"
    current_major=$((10#${current_major:-0}))
    current_minor=$((10#${current_minor:-0}))
    current_patch=$((10#${current_patch:-0}))
    required_major=$((10#${required_major:-0}))
    required_minor=$((10#${required_minor:-0}))
    required_patch=$((10#${required_patch:-0}))

    ((current_major > required_major ||
        (current_major == required_major && current_minor > required_minor) ||
        (current_major == required_major && current_minor == required_minor &&
         current_patch >= required_patch)))
}

cleanup_temp_dir() {
    local temp_dir="${TEMP_DIR:-}"

    if [[ -n "${temp_dir}" && -d "${temp_dir}" &&
        "${temp_dir}" == "${ROOT_DIR}"/.install-z3.* ]]; then
        rm -rf -- "${temp_dir}"
    fi
}

configure_homebrew_env() {
    local brew_bin="$1"
    local shellenv_line

    shellenv_line="eval \"\$(${brew_bin} shellenv)\""
    eval "$("${brew_bin}" shellenv)"

    update_managed_block \
        "${HOME}/.zshrc" \
        "# BEGIN BATFISH HOMEBREW" \
        "# END BATFISH HOMEBREW" \
        "# Homebrew environment for Batfish dependencies" \
        "${shellenv_line}"
    update_managed_block \
        "${HOME}/.bashrc" \
        "# BEGIN BATFISH HOMEBREW" \
        "# END BATFISH HOMEBREW" \
        "# Homebrew environment for Batfish dependencies" \
        "${shellenv_line}"
}

configure_java_env() {
    local java_home="$1"
    local java_cmd="${java_home}/bin/java"
    local version_output version_line version_field major_version

    if [[ ! -x "${java_cmd}" ]]; then
        echo "Error: Java executable not found at ${java_cmd}." >&2
        exit 1
    fi

    version_output="$("${java_cmd}" -version 2>&1)"
    version_line="${version_output%%$'\n'*}"
    version_field="$(sed -n 's/.*"\([0-9][0-9.]*\)".*/\1/p' <<<"${version_line}")"

    if [[ -z "${version_field}" ]]; then
        echo "Error: Unable to parse Java version from: ${version_line}" >&2
        exit 1
    fi

    if [[ "${version_field}" == 1.* ]]; then
        major_version="${version_field#1.}"
        major_version="${major_version%%.*}"
    else
        major_version="${version_field%%.*}"
    fi

    if [[ "${major_version}" != "${JAVA_REQUIRED_MAJOR}" ]]; then
        echo "Error: Batfish requires Java ${JAVA_REQUIRED_MAJOR}," >&2
        echo "       but ${java_cmd} reports Java ${version_field}." >&2
        exit 1
    fi

    JAVA_HOME="${java_home}"
    export JAVA_HOME
    export PATH="${JAVA_HOME}/bin:${Z3_BIN_DIR}:${PATH}"

    update_managed_block \
        "${HOME}/.zshrc" \
        "# BEGIN BATFISH JAVA" \
        "# END BATFISH JAVA" \
        "export JAVA_HOME=${JAVA_HOME}" \
        "export PATH=\"\${JAVA_HOME}/bin:${Z3_BIN_DIR}:\${PATH}\""
    update_managed_block \
        "${HOME}/.bashrc" \
        "# BEGIN BATFISH JAVA" \
        "# END BATFISH JAVA" \
        "export JAVA_HOME=${JAVA_HOME}" \
        "export PATH=\"\${JAVA_HOME}/bin:${Z3_BIN_DIR}:\${PATH}\""

    echo "[✓] Java ${JAVA_REQUIRED_MAJOR} detected and configured: ${JAVA_HOME}"
}

install_python_dependencies() {
    local pip_install_help
    local -a pip_install_args=(--user)

    echo "[*] Installing Python analysis and plotting dependencies ..."
    pip_install_help="$(python3 -m pip install --help)"
    if [[ "${pip_install_help}" == *"--break-system-packages"* ]]; then
        pip_install_args+=(--break-system-packages)
    fi
    python3 -m pip install "${pip_install_args[@]}" "${PYTHON_PACKAGES[@]}"
}

verify_z3_cli() {
    local version_output

    if ! version_output="$("${Z3_BIN_DIR}/z3" --version 2>&1)"; then
        echo "Error: Unable to run Z3 from ${Z3_BIN_DIR}/z3." >&2
        echo "       ${version_output}" >&2
        exit 1
    fi
    if [[ "${version_output}" != "Z3 version ${Z3_VERSION} "* ]]; then
        echo "Error: Expected Z3 ${Z3_VERSION}, but detected: ${version_output}" >&2
        exit 1
    fi
    echo "[✓] Z3 ${Z3_VERSION} CLI installed: ${Z3_BIN_DIR}/z3"
}

update_bazelrc_for_linux() {
    echo "[*] Updating Bazel configuration ..."
    mkdir -p "${SMT_PATH}"
    cat >"${BAZELRC_PATH}" <<EOF
# Automatically generated by install.sh
build --sandbox_writable_path=${SMT_PATH}/ \
      --action_env=SMT_DIRECTORY_PREFIX=${SMT_PATH}/ \
      --explicit_java_test_deps

# Z3 JNI: load user-local native libraries
test --test_env=JAVA_TOOL_OPTIONS=-Djava.library.path=${Z3_LINUX_LIB_DIR}
test --test_env=LD_LIBRARY_PATH=${Z3_LINUX_LIB_DIR}
EOF
}

update_bazelrc_for_macos() {
    echo "[*] Updating Bazel configuration for macOS ..."
    mkdir -p "${SMT_PATH}"
    Z3_JAVA_EXTENSIONS="${HOME}/Library/Java/Extensions"
    cat >"${BAZELRC_PATH}" <<EOF
# Automatically generated by install.sh (macOS)
build --sandbox_writable_path=${SMT_PATH}/ \
      --action_env=SMT_DIRECTORY_PREFIX=${SMT_PATH}/ \
      --explicit_java_test_deps

# Z3 JNI: run tests outside sandbox; load libs from Java Extensions
test --strategy=TestRunner=standalone
test --spawn_strategy=local
test --test_env=JAVA_TOOL_OPTIONS=-Djava.library.path=${Z3_JAVA_EXTENSIONS}
EOF
}

install_for_linux() {
    if [[ "${ARCH}" != "x86_64" ]]; then
        echo "Error: Linux installation supports x86_64 only (detected ${ARCH})." >&2
        exit 1
    fi

    local glibc_version java_home
    if ! glibc_version=$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}') ||
        [[ -z "${glibc_version}" ]]; then
        echo "Error: Unable to detect glibc; Z3 requires glibc 2.35 or newer." >&2
        exit 1
    fi
    if ! version_at_least "${glibc_version}" "2.35"; then
        echo "Error: Z3 ${Z3_VERSION} requires glibc 2.35 or newer" >&2
        echo "       (detected glibc ${glibc_version})." >&2
        exit 1
    fi
    echo "[*] Compatibility check passed: glibc ${glibc_version}"

    TEMP_DIR=$(mktemp -d "${ROOT_DIR}/.install-z3.XXXXXX")
    trap cleanup_temp_dir EXIT

    Z3_PLATFORM="x64-glibc-2.35"
    Z3_BASENAME="z3-${Z3_VERSION}-${Z3_PLATFORM}"
    Z3_URL="https://github.com/Z3Prover/z3/releases/download/z3-${Z3_VERSION}/${Z3_BASENAME}.zip"

    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Error: apt-get is required." >&2
        exit 1
    fi

    echo "[*] Installing Linux dependencies ..."
    sudo apt-get update
    sudo apt-get install -y \
        ca-certificates \
        unzip \
        wget

    echo "[*] Installing OpenJDK 11 ..."
    sudo apt-get install -y openjdk-11-jdk
    java_home="/usr/lib/jvm/java-11-openjdk-$(dpkg --print-architecture)"
    configure_java_env "${java_home}"

    echo "[*] Installing Python 3 ..."
    sudo apt-get install -y \
        python3 \
        python3-pip
    install_python_dependencies

    echo "[*] Installing Z3 ${Z3_VERSION} via apt ..."
    sudo apt-get install -y "z3=${Z3_VERSION}"

    echo "[*] Installing Bazelisk ${BAZELISK_VERSION} ..."
    BAZELISK_URL="https://github.com/bazelbuild/bazelisk/releases/download/v${BAZELISK_VERSION}/bazelisk-linux-amd64"
    wget -O "${TEMP_DIR}/bazelisk" "${BAZELISK_URL}"
    sudo install -m 0755 "${TEMP_DIR}/bazelisk" /usr/local/bin/bazelisk
    sudo ln -sf /usr/local/bin/bazelisk /usr/local/bin/bazel

    echo "[*] Installing Z3 ${Z3_VERSION} CLI and JNI libraries ..."
    wget -O "${TEMP_DIR}/${Z3_BASENAME}.zip" "${Z3_URL}"
    unzip -q "${TEMP_DIR}/${Z3_BASENAME}.zip" -d "${TEMP_DIR}"

    echo "[*] Configuring Z3 JNI for Linux ..."
    mkdir -p "${Z3_LINUX_LIB_DIR}"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/z3" \
        "${Z3_BIN_DIR}/z3"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/libz3.so" \
        "${Z3_LINUX_LIB_DIR}/libz3.so"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/libz3java.so" \
        "${Z3_LINUX_LIB_DIR}/libz3java.so"
    verify_z3_cli

    echo "[✓] Completed: Linux installation"
}

install_for_macos() {
    if [[ "${ARCH}" != "arm64" ]]; then
        echo "Error: macOS installation supports arm64 only (detected ${ARCH})." >&2
        exit 1
    fi

    local brew_bin macos_version java_home
    macos_version=$(sw_vers -productVersion)
    if ! version_at_least "${macos_version}" "${MACOS_MIN_VERSION}"; then
        echo "Error: install.sh requires macOS ${MACOS_MIN_VERSION} or newer" >&2
        echo "       (detected macOS ${macos_version})." >&2
        exit 1
    fi
    echo "[*] Compatibility check passed: macOS ${macos_version}"

    TEMP_DIR=$(mktemp -d "${ROOT_DIR}/.install-z3.XXXXXX")
    trap cleanup_temp_dir EXIT

    Z3_PLATFORM="arm64-osx-13.7.2"
    Z3_BASENAME="z3-${Z3_VERSION}-${Z3_PLATFORM}"
    Z3_URL="https://github.com/Z3Prover/z3/releases/download/z3-${Z3_VERSION}/${Z3_BASENAME}.zip"
    Z3_JAVA_EXTENSIONS="${HOME}/Library/Java/Extensions"

    brew_bin="$(command -v brew || true)"
    if [[ -z "${brew_bin}" ]]; then
        echo "[*] Homebrew not found. Installing Homebrew ..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [[ -x /opt/homebrew/bin/brew ]]; then
            brew_bin=/opt/homebrew/bin/brew
        elif [[ -x /usr/local/bin/brew ]]; then
            brew_bin=/usr/local/bin/brew
        else
            echo "Error: Homebrew installation completed, but brew was not found." >&2
            exit 1
        fi
    fi
    configure_homebrew_env "${brew_bin}"

    echo "[*] Installing macOS dependencies ..."
    brew install \
        ca-certificates \
        unzip \
        wget

    echo "[*] Installing OpenJDK 11 ..."
    brew install openjdk@11
    java_home="$(brew --prefix openjdk@11)/libexec/openjdk.jdk/Contents/Home"
    configure_java_env "${java_home}"

    echo "[*] Installing Python 3 ..."
    brew install python3
    install_python_dependencies

    echo "[*] Installing Bazelisk ..."
    brew install bazelisk

    echo "[*] Installing Z3 ${Z3_VERSION} via Homebrew ..."
    brew install "z3@${Z3_VERSION}"

    echo "[*] Installing Z3 ${Z3_VERSION} CLI and JNI libraries ..."
    wget -O "${TEMP_DIR}/${Z3_BASENAME}.zip" "${Z3_URL}"
    unzip -q "${TEMP_DIR}/${Z3_BASENAME}.zip" -d "${TEMP_DIR}"

    mkdir -p "${Z3_BIN_DIR}"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/z3" \
        "${Z3_BIN_DIR}/z3"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/libz3.dylib" \
        "${Z3_BIN_DIR}/libz3.dylib"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/libz3java.dylib" \
        "${Z3_BIN_DIR}/libz3java.dylib"
    verify_z3_cli

    echo "[*] Configuring Z3 JNI for macOS ..."
    mkdir -p "${Z3_JAVA_EXTENSIONS}"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/libz3.dylib" \
        "${Z3_JAVA_EXTENSIONS}/libz3.dylib"
    install -m 0755 \
        "${TEMP_DIR}/${Z3_BASENAME}/bin/libz3java.dylib" \
        "${Z3_JAVA_EXTENSIONS}/libz3java.dylib"
    install_name_tool -change libz3.dylib @loader_path/libz3.dylib \
        "${Z3_JAVA_EXTENSIONS}/libz3java.dylib"

    echo "[*] Signing Z3 JNI libraries for macOS ..."
    codesign --force --sign - "${Z3_JAVA_EXTENSIONS}/libz3.dylib"
    codesign --force --sign - "${Z3_JAVA_EXTENSIONS}/libz3java.dylib"
    codesign --verify --strict "${Z3_JAVA_EXTENSIONS}/libz3.dylib"
    codesign --verify --strict "${Z3_JAVA_EXTENSIONS}/libz3java.dylib"

    echo "[✓] Completed: macOS installation"
}

case "${OS}" in
    Linux)
        update_bazelrc_for_linux
        install_for_linux
        ;;
    Darwin)
        update_bazelrc_for_macos
        install_for_macos
        ;;
    *)
        echo "Error: Unsupported system: ${OS}" >&2
        exit 1
        ;;
esac

echo "[✓] All done!"
