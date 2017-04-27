#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys

from setuptools import setup, Extension


version_info = {
    'name': 'gruvi',
    'version': '0.10.3',
    'description': 'Pythonic async IO with libuv and fibers',
    'author': 'Geert Jansen',
    'author_email': 'geertj@gmail.com',
    'url': 'https://github.com/geertj/gruvi',
    'license': 'MIT',
    'classifiers': [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: MacOS :: MacOS X',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6'
    ]
}

topdir, _ = os.path.split(os.path.abspath(__file__))


def get_requirements():
    """Parse a requirements.txt file and return as a list."""
    with open(os.path.join(topdir, 'requirements.txt')) as fin:
        lines = fin.readlines()
    lines = [line.strip() for line in lines]
    return lines


def main():
    os.chdir(topdir)
    ext_modules = []
    # Note that on Windows it's more involved to compile _sslcompat because
    # there's no system provided OpenSSL and you need to match the version that
    # was used to compile your Python.
    if sys.version_info[:2] < (3, 5):
        ext_modules.append(Extension('_sslcompat', ['src/sslcompat.c'],
                                     libraries=['ssl', 'crypto']))
    setup(
        packages=['gruvi', 'gruvi_vendor.txdbus'],
        package_dir={'': 'lib', 'gruvi_vendor': 'vendor'},
        setup_requires=['cffi >= 1.0.0'],
        install_requires=get_requirements(),
        cffi_modules=['src/build_http.py:ffi', 'src/build_jsonrpc.py:ffi'],
        ext_package='gruvi',
        ext_modules=ext_modules,
        zip_safe=False,
        **version_info
    )


if __name__ == '__main__':
    main()
