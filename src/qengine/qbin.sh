#!/usr/bin/env bash
#
# Print the path of the q binary the qlite arm runs, fetching and verifying the
# pinned release if it is not cached yet.
#
#   ./src/qengine/qbin.sh              # the pinned release below
#   ./src/qengine/qbin.sh duckdb       # the pinned release's DuckDB build (QBIN_DUCKDB overrides)
#   QBIN=/path/to/q ./src/qengine/qbin.sh   # an explicit override
#
# The override never happens implicitly: an unusable QBIN is an error, not a
# reason to fall back to the release, because a benchmark run has to say which
# binary produced it.

set -euo pipefail

# Bump these three together to pin a new release.
QLITE_ENGINE="peachq"
QLITE_VERSION="0.89.0"
QLITE_SHA256="f429f21b24fb12cf28915f8c3c6ba8b06057c3732ee91e2c2e163fe893a95da7"
QLITE_DUCKDB_SHA256="78115aea9d5d50b1c2fdf999b38ca7263661e174801af12db8b4b3115b1e61d0"

QLITE_URL_BASE="${QLITE_URL_BASE:-https://peachq.org/file}"
QLITE_TARBALL="${QLITE_ENGINE}-v${QLITE_VERSION}-linux-x86_64.tar.gz"
QLITE_FLAVOUR=""
if [[ "${1:-}" == "duckdb" ]]; then
    QBIN="${QBIN_DUCKDB:-}"
    QLITE_TARBALL="${QLITE_ENGINE}-v${QLITE_VERSION}-linux-x86_64-glibc-duckdb.tar.gz"
    QLITE_SHA256="${QLITE_DUCKDB_SHA256}"
    QLITE_FLAVOUR="-duckdb"
fi
QLITE_CACHE_DIR="${QLITE_CACHE_DIR:-./external/qlite}"

if [[ -n "${QBIN:-}" ]]; then
    if [[ ! -x "${QBIN}" ]]; then
        echo "QBIN is set to '${QBIN}', which is not an executable file." >&2
        exit 1
    fi
    echo "qlite: using the QBIN override '${QBIN}', NOT the pinned ${QLITE_ENGINE} v${QLITE_VERSION}" >&2
    echo "${QBIN}"
    exit 0
fi

install_dir="${QLITE_CACHE_DIR}/${QLITE_ENGINE}-v${QLITE_VERSION}${QLITE_FLAVOUR}"
binary="${install_dir}/q"

if [[ ! -x "${binary}" ]]; then
    tarball="${QLITE_CACHE_DIR}/${QLITE_TARBALL}"
    mkdir -p "${QLITE_CACHE_DIR}"
    echo "qlite: fetching ${QLITE_URL_BASE}/${QLITE_TARBALL}" >&2
    curl -fsSL --retry 3 -o "${tarball}" "${QLITE_URL_BASE}/${QLITE_TARBALL}"
    echo "${QLITE_SHA256}  ${tarball}" | sha256sum --check --status || {
        echo "sha256 mismatch for ${tarball}; expected ${QLITE_SHA256}" >&2
        rm -f "${tarball}"
        exit 1
    }
    mkdir -p "${install_dir}"
    tar -xzf "${tarball}" -C "${install_dir}"
    rm -f "${tarball}"
fi

[[ -x "${binary}" ]] || {
    echo "${QLITE_ENGINE} v${QLITE_VERSION} unpacked without a 'q' binary at ${binary}" >&2
    exit 1
}
echo "${binary}"
