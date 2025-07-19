#!/bin/bash

PKGNAME="piper"
VERSION="1.0.0"
PREFIX="/data/data/com.termux/files/usr"

# Cleanup
rm -rf build
rm -f ${PKGNAME}*.deb
mkdir -p build

# ---- Package with espeak dependency ----

PKGDIR=build/$PKGNAME

mkdir -p $PKGDIR/DEBIAN
mkdir -p $PKGDIR$PREFIX/bin
mkdir -p $PKGDIR$PREFIX/lib

# Copy the Python module
mkdir -p $PKGDIR$PREFIX/lib/python3.12/site-packages/
cp -r src/piper $PKGDIR$PREFIX/lib/python3.12/site-packages/

chmod 755 $PKGDIR/DEBIAN

cat > $PKGDIR/DEBIAN/control <<EOF
Package: $PKGNAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: aarch64
Maintainer: Your Name <you@example.com>
Depends: python3, espeak
Conflicts: ${PKGNAME}-no-espeak
Description: Piper TTS CLI with espeak-ng data and shared libraries.
EOF

dpkg-deb --build $PKGDIR
mv $PKGDIR.deb $PKGNAME-$VERSION.deb

echo "Successfully created $PKGNAME-$VERSION.deb"
