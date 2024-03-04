#!/bin/bash

VERSION=$1

if [ -z "$VERSION" ]
then
	echo "Missing version... Exit"
	exit 1
fi

mkdir $VERSION
cp -a descriptions $VERSION/
cp -a tables $VERSION/
cp -a el_corrections $VERSION/

zip -r "$VERSION.zip" $VERSION
