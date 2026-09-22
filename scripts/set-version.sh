#!/usr/bin/env bash

set -euo pipefail

readonly VERSION_PATTERN='^[0-9]+\.[0-9]+\.[0-9]+([-+].*)?$'

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readonly VERSION_FILE="${root}/src/fdstoolkit/version.py"

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

version_recorded_in_file() {
  sed -n 's/^VERSION = "\(.*\)"$/\1/p' "${VERSION_FILE}"
}

replace_recorded_version() {
  local wanted=$1
  local scratch
  scratch=$(mktemp "${TMPDIR:-/tmp}/fdstoolkit-version-XXXXXX")

  sed "s/^VERSION = \".*\"$/VERSION = \"${wanted}\"/" "${VERSION_FILE}" >"${scratch}"
  cat "${scratch}" >"${VERSION_FILE}"
  rm -f "${scratch}"
}

main() {
  local wanted=${1:?version required}

  [[ ${wanted} =~ ${VERSION_PATTERN} ]] || fail "not a version: ${wanted}"
  [[ -f ${VERSION_FILE} ]] || fail "no version file at ${VERSION_FILE}"
  [[ -n $(version_recorded_in_file) ]] || fail "no VERSION assignment in ${VERSION_FILE}"

  replace_recorded_version "${wanted}"

  local written
  written=$(version_recorded_in_file)
  [[ ${written} == "${wanted}" ]] || fail "wanted ${wanted} in ${VERSION_FILE}, found ${written}"

  printf 'version set to %s\n' "${written}"
}

main "$@"
