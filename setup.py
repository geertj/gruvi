#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import tempfile
import textwrap
import subprocess

from setuptools import setup, Extension


version_info = {
    'name': 'gruvi',
    'version': '0.9.dev',
    'description': 'Synchronous evented IO with pyuv and greenlets',
    'author': 'Geert Jansen',
    'author_email': 'geertj@gmail.com',
    'url': 'https://github.com/geertj/gruvi',
    'license': 'MIT',
    'classifiers': [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX',
        'Operating System :: Windows',
        'Operating System :: Mac OSX',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3'
    ]
}

topdir, _ = os.path.split(os.path.abspath(__file__))


def update_version():
    """Update the _version.py file."""
    fname = os.path.join('.', 'gruvi', '_version.py')
    try:
        with open(fname) as fin:
            current = fin.read()
    except IOError:
        current = None
    new = textwrap.dedent("""\
            # This file is autogenerated. Do not edit.
            __version__ = '{0[version]}'
            """.format(version_info))
    if current == new:
        return
    tmpname = '{0}.{1}-tmp'.format(fname, os.getpid())
    with open(tmpname, 'w') as fout:
        fout.write(new)
    os.rename(tmpname, fname)
    print('Updated _version.py')


def update_manifest():
    """Update the MANIFEST.in file from git, if necessary."""
    # It would be more efficient to create MANIFEST directly, rather
    # than creating a MANIFEST.in where every line just includes one file.
    # Unfortunately, setuptools/distribute do not support this (distutils
    # does).
    gitdir = os.path.join('.', '.git')
    try:
        st = os.stat(gitdir)
    except OSError:
        return
    cmd = subprocess.Popen(['git', 'ls-tree', '-r', 'master', '--name-only'],
                           stdout=subprocess.PIPE)
    stdout, _ = cmd.communicate()
    files = stdout.splitlines()
    files.append('gruvi/_version.py')
    lines = ['include {0}\n'.format(fname.decode('ascii')) for fname in files]
    new = ''.join(sorted(lines))
    try:
        with open('MANIFEST.in', 'r') as fin:
            current = fin.read()
    except IOError:
        current = None
    if new == current:
        return
    tmpname = 'MANIFEST.in.{0}-tmp'.format(os.getpid())
    with open(tmpname, 'w') as fout:
        fout.write(new)
    os.rename(tmpname, 'MANIFEST.in')
    print('Updated MANIFEST.in')
    # Remove the SOURCES.txt that setuptools maintains. It appears not to
    # accurately regenerate it when MANIFEST.in changes.
    sourcestxt = os.path.join('lib', 'gruvi.egg-info', 'SOURCES.txt')
    if not os.access(sourcestxt, os.R_OK):
        return
    os.unlink(sourcestxt)
    print('Removed {0}'.format(sourcestxt))


def main():
    os.chdir(topdir)
    update_version()
    update_manifest()
    setup(
        packages = ['gruvi', 'gruvi.test'],
        install_requires = ['greenlet>=0.4.0', 'pyuv>=0.10.3'],
        test_suite = 'nose.collector',
        **version_info
    )


if __name__ == '__main__':
    main()
