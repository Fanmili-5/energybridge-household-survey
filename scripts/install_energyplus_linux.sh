#!/usr/bin/env bash
# Official EnergyPlus v24.1.0 Linux x86_64 archive and published sha256sums.txt.
set -euo pipefail
install_parent="${1:?Usage: install_energyplus_linux.sh DIRECTORY}"
archive=EnergyPlus-24.1.0-9d7789a3ac-Linux-Ubuntu22.04-x86_64.tar.gz
expected=5a1d30c3bd1a304741c495a683c7d6ffd8c07d00dd06783e543b50a631c29017
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'Requires Linux x86_64' >&2; exit 1; }
mkdir -p "$install_parent"
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
curl --fail --location --retry 3 "https://github.com/NatLabRockies/EnergyPlus/releases/download/v24.1.0/$archive" -o "$work_dir/$archive"
(cd "$work_dir" && printf '%s  %s\n' "$expected" "$archive" | sha256sum --check)
# Extract only into an empty target to avoid overwriting an existing installation.
[[ -z "$(ls -A "$install_parent")" ]] || { echo 'Installation directory must be empty' >&2; exit 1; }
tar -xzf "$work_dir/$archive" -C "$install_parent" --strip-components=1
"$install_parent/energyplus" --version
