#!/usr/bin/env bash
# Build the libtesseract release pinned in test-suites.toml ([environment.tesseract])
# into PREFIX, with the pinned eng tessdata_fast model in PREFIX/share/tessdata. The
# opt-in Tesseract recovery declares 5.5.4, measured on Homebrew's build, and Ubuntu
# 24.04 ships 5.3.4. Like Homebrew's formula this runs autotools on the release tag,
# whose tarball and model it pins; OpenMP stays off, as in Homebrew's clang build, so
# each page is one thread. No training tools, ScrollView, libarchive or libcurl.
# Build dependencies on Ubuntu 24.04: see the setup-python-project action.
set -euo pipefail
prefix=${1:?usage: install-tesseract.sh PREFIX}
root=$(cd "$(dirname "$0")/../.." && pwd)
read -r version sha256 eng_sha256 < <(python3 -c 'import sys, tomllib
pin = tomllib.load(open(sys.argv[1], "rb"))["environment"]["tesseract"]
print(pin["version"], pin["source_sha256"], pin["eng_fast_sha256"])' "$root/test-suites.toml")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fsSL --retry 3 -o "$work/tesseract.tar.gz" \
  "https://github.com/tesseract-ocr/tesseract/archive/refs/tags/$version.tar.gz"
echo "$sha256  $work/tesseract.tar.gz" | sha256sum -c -
tar -xzf "$work/tesseract.tar.gz" -C "$work"
(
  cd "$work/tesseract-$version"
  ./autogen.sh
  ./configure --prefix="$prefix" --disable-openmp --disable-graphics --disable-doc \
    --without-archive --without-curl
  make -j"$(nproc)"
  make install
)
mkdir -p "$prefix/share/tessdata"
curl -fsSL --retry 3 -o "$prefix/share/tessdata/eng.traineddata" \
  "https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/eng.traineddata"
echo "$eng_sha256  $prefix/share/tessdata/eng.traineddata" | sha256sum -c -
"$prefix/bin/tesseract" --version
