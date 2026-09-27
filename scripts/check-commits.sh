#!/usr/bin/env bash

set -euo pipefail

readonly TYPES='feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert'
readonly MAX_SUBJECT=50
readonly USAGE='usage: check-commits.sh --message <file> | --range <from>..<to>'

length_of() {
  printf '%s' "$1" | wc -m | tr -d ' '
}

problem_with() {
  local subject=$1 length
  if [[ ! ${subject} =~ ^(${TYPES})(\([a-z0-9-]+\))?!?:\ (.+)$ ]]; then
    printf 'the type must be one of %s, with an optional (scope)' "${TYPES//|/, }"
    return
  fi
  local text=${BASH_REMATCH[3]}
  length=$(length_of "${subject}")
  if [[ ${text} =~ ^[A-Z] ]]; then
    printf 'the description starts lowercase'
  elif [[ ${text} == *. ]]; then
    printf 'the description ends without a full stop'
  elif ((length > MAX_SUBJECT)); then
    printf 'the subject is %d characters and the limit is %d' "${length}" "${MAX_SUBJECT}"
  fi
}

subject_of_file() {
  grep -v '^#' "$1" | sed -n '1p'
}

check_subject() {
  local subject=$1 found
  found=$(problem_with "${subject}")
  if [[ -n ${found} ]]; then
    printf '%s: %s\n' "${subject}" "${found}" >&2
    return 1
  fi
}

check_range() {
  local failed=0 subject
  while IFS= read -r subject; do
    check_subject "${subject}" || failed=1
  done < <(git log --no-merges --format=%s "$1")
  return "${failed}"
}

case "${1:-}" in
  --message) check_subject "$(subject_of_file "$2")" ;;
  --range) check_range "$2" ;;
  *)
    printf '%s\n' "${USAGE}" >&2
    exit 2
    ;;
esac
