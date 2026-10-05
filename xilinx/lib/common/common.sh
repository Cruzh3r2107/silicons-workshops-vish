# shellcheck shell=sh
# Shared paths, logging, stage runner and state files for the Workshop SDKs.
# Callers set PROJECT_DIR (default /project, the Workshop project mount) and
# source this file.

: "${PROJECT_DIR:=/project}"
COMMON_DIR="$PROJECT_DIR/lib/common"
BUILD_DIR="$PROJECT_DIR/build"
OUT_DIR="$PROJECT_DIR/out"
LOG_DIR="$BUILD_DIR/logs"
STATE_DIR="$BUILD_DIR/state"
LINUX_DIR="$BUILD_DIR/linux"

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

info() {
	printf '==> %s\n' "$*"
}

wscfg() {
	python3 "$COMMON_DIR/wsconfig.py" --project "$PROJECT_DIR" "$@"
}

# run_stage NAME FUNC [ARGS...]: run FUNC with errexit in a subshell, logging to
# $LOG_DIR/NAME.log. errexit is ignored inside functions called from a
# conditional, so the subshell's status is captured outside any `if`.
run_stage() {
	_rs_name=$1
	shift
	mkdir -p "$LOG_DIR"
	info "$_rs_name"
	set +e
	(
		set -e
		"$@"
	) >"$LOG_DIR/$_rs_name.log" 2>&1
	_rs_status=$?
	set -e
	if [ "$_rs_status" -ne 0 ]; then
		printf 'error: stage "%s" failed; last lines of %s:\n' "$_rs_name" "$LOG_DIR/$_rs_name.log" >&2
		tail -n 25 "$LOG_DIR/$_rs_name.log" >&2
		exit 1
	fi
}

state_matches() {
	[ -f "$STATE_DIR/$1" ] && [ "$(cat "$STATE_DIR/$1")" = "$2" ]
}

state_write() {
	mkdir -p "$STATE_DIR"
	printf '%s\n' "$2" >"$STATE_DIR/$1"
}

state_clear() {
	for _sc in "$@"; do
		rm -f "$STATE_DIR/$_sc"
	done
}
