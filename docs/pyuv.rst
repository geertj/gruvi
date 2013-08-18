************************************
:mod:`gruvi.pyuv` -- pyuv transports
************************************

All transports in this module are thin wrappers around handles in pyuv. The
main difference is that in pyuv the constructor for these classes requires at
least one argument specifying the event loop to register to. The classes below
do not require this and will automatically register to the event loop of the
Hub.

.. automodule:: gruvi.pyuv
   :members:
