.. _installation:

************
Installation
************

Gruvi uses the setuptools, so installation is relatively straightforward. The
following Python / OS combinations are supported:

==========  ==================  ===============================
OS          Python versions     Notes
==========  ==================  ===============================
Posix       2.7, 3.3+           Only Linux is regularly tested
Mac OSX     2.7, 3.3+           PPC is not tested
Windows     2.7, 3.3+           No SSL backports on 2.7
==========  ==================  ===============================

Gruvi and some of its dependencies contain C extensions. This means that you
need to have a C compiler, and also the Python development files. Gruvi also
uses CFFI_ so you need to have that installed as well.

Installation using pip
**********************

If you have the "pip" package manager, then you can install Gruvi directly from
the Python Package Index::

  $ pip install cffi
  $ pip install gruvi

You need to install CFFI first because the Gruvi setup script depends on it.

Installation from source
************************

The following instructions install Gruvi in a virtualenv development
environment::

  $ pyvenv gruvi-dev  # "virtualenv gruvi-dev" with Python <= 3.3
  $ . gruvi-dev/bin/activate
  $ git clone https://github.com/geertj/gruvi
  $ cd gruvi
  $ pip install -r requirements.txt
  $ python setup.py develop

Linux Specific Notes
********************

Most mainstream Linux versions have a supported version of Python installed by
default, with the notable exception of RHEL/CentOS version 6. For this OS you
can use `Software Collections`_ to install a supported Python version.

To install the required dependencies on Debian/Ubuntu systems::

  $ sudo apt-get update
  $ sudo apt-get install -y gcc python-dev python-virtualenv libffi-dev

On Red Hat/Fedora type systems::

  $ sudo yum install -y gcc python-devel python-virtualenv libffi-devel

Mac OSX Specific Notes
**********************

Recent versions of OSX have a supported Python version available.

The easiest way to install a C compiler is to install Xcode from the Mac App
Store. This is a free download.

Since OSX Mavericks, the required libffi dependency has become part of OSX
itself, so there's no need to install it separately. If you are on an earlier
version of OSX, it's recommended to install libffi via Homebrew.

Windows Specific Notes
**********************

Windows does not come with a system provided version of Python, so you have to
install one from python.org. It is recommended to use version 3.3 or 3.4.

For the C compiler, I recommend to use Microsoft `Visual C++ 2010 Express`_.
It is a free download, and it is the same compiler used to create the official
Python builds for Windows since version 3.3.

You can also use MinGW. In that case make sure you use either Python 2.7.6,
3.3.3, 3.4 or later. These version contain a fix for issue12641_.


.. _CFFI: https://pypi.python.org/pypi/cffi
.. _issue12641: http://bugs.python.org/issue12641
.. _`Visual C++ 2010 Express`: https://www.microsoft.com/visualstudio/eng/downloads#d-2010-express
.. _`Software Collections`: http://softwarecollections.org/
