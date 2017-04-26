#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function


from os.path import abspath, split, join, exists

def up(path):
    return split(path)[0]

pathdir = up(up(abspath(__file__)))
vendordir = join(pathdir, 'gruvi_vendor')

if not exists(vendordir):
    # This is a development install. The setuptools "develop" command appears
    # not to correctly handle multiple entries in package_dir. Therefore, pull
    # in the vendorized packages directly from the top of the source tree.
    vendordir = join(up(pathdir), 'vendor')

__package__ = 'vendor'
__path__ = [vendordir]
