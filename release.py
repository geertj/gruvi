#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import subprocess
from setup import version_info as vinfo

if sys.version_info[0] == 2:
    input = __builtins__.raw_input


def sh(cmd, *args):
    """Execute shell command *cmd*. Exit on failure."""
    if args:
        cmd = cmd.format(*args)
    ret = subprocess.call(cmd, shell=True)
    if ret == 0:
        return
    print('Error: cmd {0!r} exited with status {1}'.format(cmd, ret), file=sys.stderr)
    sys.exit(1)


def confirm(prompt):
    """Get a confirmation from the user for an action."""
    response = None
    prompt += ' (y/n) '
    while True:
        response = input(prompt)
        if response in 'yn':
            break
        print('Please answer "y" or "n"')
    return response == 'y'


def get_release_versions():
    """Prompt the user for the current and next release versions."""
    version = vinfo['version']
    if version.endswith('.dev'):
        print('Current development version: {0}'.format(version))
        relver = version[:-4]
        override = input('What version do you want to release [{0}]: '.format(relver))
        if override:
            relver = override
    else:
        print('Current version is NOT a development version: {0}'.format(version))
        if not confirm('Do you want to release this version?'):
            return None, None
        relver = version
    try:
        nums = list(map(int, relver.split('.')))
        nums[-1] += 1
        nextver = '.'.join(map(str, nums))
    except ValueError:
        nextver = ''
    override = input('What will be the next version [{0}]: '.format(nextver))
    if override:
        nextver = override
    print('Version to release: {0}'.format(relver))
    print('New version to start: {0}'.format(nextver or '(none)'))
    if not confirm('Is this correct?'):
        return None, None
    return relver, nextver


def confirm_file_list():
    """Confirm differences between files in Git and in the sdist."""
    sh('git ls-files | sort > files.git')
    print('Comparing files in git against the source distribution...')
    sh('rm -rf gruvi.egg-info')
    sh('python setup.py sdist >/dev/null 2>&1')
    sh('tar tfz dist/{0}-{1}.tar.gz'
       ' | sed -e \'s/^{0}-{1}\///\' -e \'/\/$/d\' -e \'/^$/d\''
       ' | sort > files.sdist', vinfo['name'], vinfo['version'])
    sh('diff -u files.git files.sdist || true')
    sh('rm files.git; rm files.sdist')
    return confirm('Are these differences OK?')


def make_release(relver, nextver):
    """Make a release for *relver*. Next version will be *nextver*."""
    print('Creating the release..')
    if relver != vinfo['version']:
        sh('sed -i -e \'s/{0}/{1}/\' setup.py', vinfo['version'], relver)
        sh('git add setup.py')
        sh('git commit -m "version {0}"', relver)
    sh('git tag -a -m "version {0}" {1}-{0}', relver, vinfo['name'])
    sh('python setup.py sdist upload >/dev/null')
    if nextver:
        sh('sed -i -e \'s/{0}/{1}.dev/\' setup.py', relver, nextver)
        sh('git add setup.py')
        sh('git commit -m "start working on {0}"', nextver)
    sh('git push')
    sh('git push --tags')
    print('Done!')


def main():
    relver, nextver = get_release_versions()
    if relver is None:
        return
    if not confirm_file_list():
        return
    if not confirm('Make release?'):
        return
    make_release(relver, nextver)


if __name__ == '__main__':
    main()
