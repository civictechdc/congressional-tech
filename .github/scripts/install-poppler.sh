#!/usr/bin/env bash
# Build the Poppler release pinned in test-suites.toml ([environment.poppler]) into
# PREFIX. The sniff parser_version hashes `pdfinfo -v`/`pdftotext -v`, so CI, hosted
# jobs and local machines must all run that exact release, and no maintained Linux
# distribution ships it. Only the command-line utilities are built, linked against
# a static libpoppler; poppler-data comes from the system (/usr/share/poppler).
# Brotli stays on so BrotliDecode streams read as in Homebrew's build; HarfBuzz
# only subsets fonts when writing, so it is off.
# Build dependencies on Ubuntu 24.04: see the setup-python-project action.
set -euo pipefail
prefix=${1:?usage: install-poppler.sh PREFIX}
root=$(cd "$(dirname "$0")/../.." && pwd)
read -r version sha256 < <(python3 -c 'import sys, tomllib
pin = tomllib.load(open(sys.argv[1], "rb"))["environment"]["poppler"]
print(pin["version"], pin["source_sha256"])' "$root/test-suites.toml")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fsSL --retry 3 -o "$work/poppler.tar.xz" "https://poppler.freedesktop.org/poppler-$version.tar.xz"
echo "$sha256  $work/poppler.tar.xz" | sha256sum -c -
tar -xJf "$work/poppler.tar.xz" -C "$work"
cmake -S "$work/poppler-$version" -B "$work/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DBUILD_SHARED_LIBS=OFF \
  -DPOPPLER_DATADIR=/usr/share/poppler -DENABLE_UTILS=ON \
  -DENABLE_CPP=OFF -DENABLE_GLIB=OFF -DENABLE_GOBJECT_INTROSPECTION=OFF -DENABLE_QT5=OFF -DENABLE_QT6=OFF \
  -DENABLE_NSS3=OFF -DENABLE_GPGME=OFF -DENABLE_LIBCURL=OFF -DENABLE_BOOST=OFF -DENABLE_HARFBUZZ=OFF \
  -DBUILD_GTK_TESTS=OFF -DBUILD_QT5_TESTS=OFF -DBUILD_QT6_TESTS=OFF -DBUILD_CPP_TESTS=OFF -DBUILD_MANUAL_TESTS=OFF
cmake --build "$work/build"
cmake --install "$work/build"
"$prefix/bin/pdfinfo" -v
