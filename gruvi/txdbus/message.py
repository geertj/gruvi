"""
Module to represent DBus Messages

@author: Tom Cocagne
"""

from __future__ import absolute_import, print_function

from . import marshal, error


_headerFormat = 'yyyyuua(yv)'


class DBusMessage (object):
    """
    Abstract base class for DBus messages

    @ivar _messageType: C{int} DBus message type
    @ivar expectReply: True if a method return message is expected
    @ivar autoStart: True if a service should be auto started by this message
    @ivar signature: C{str} DBus signature describing the body content
    @ivar endian: C{int} containing endian code: Little endian = ord('l'). Big
                  endian is ord('B'). Defaults to little-endian
    @ivar bodyLength: Length of the body in bytes
    @ivar serial: C{int} message serial number
    @ivar rawMessage: Raw binary message data
    @ivar rawHeader: Raw binary message header
    @ivar rawBody: Raw binary message body
    @ivar interface: C{str} DBus interface name
    @ivar path: C{str} DBus object path
    @ivar sender: C{str} DBus bus name for sending connection
    @ivar destination: C{str} DBus bus name for destination connection
    
    """
    _maxMsgLen         = 2**27
    _nextSerial        = 1
    _protocolVersion   = 1

    # Overriden by subclasses
    _messageType       = 0    
    _headerAttrs       = None # [(attr_name, code, is_required), ...]

    # Set prior to marshal or during/after unmarshalling
    expectReply        = True 
    autoStart          = True
    signature          = None
    body               = None

    # Set during marshalling/unmarshalling
    endian             = ord('l')
    bodyLength         = 0     
    serial             = None
    headers            = None
    rawMessage         = None

    # Required/Optional
    interface          = None
    path               = None
    
    # optional
    sender             = None
    destination        = None


#    def printSelf(self):
#        mtype = { 1 : 'MethodCall',
#                  2 : 'MethodReturn',
#                  3 : 'Error',
#                  4 : 'Signal' }
#        print mtype[self._messageType]
#        keys = self.__dict__.keys()
#        keys.sort()
#        for a in keys:
#            if not a.startswith('raw'):
#                print '    %s = %s' % (a.ljust(15), str(getattr(self,a)))

    
    def _marshal(self, newSerial=True):
        """
        Encodes the message into binary format. The resulting binary message is
        stored in C{self.rawMessage}
        """
        flags = 0

        if not self.expectReply:
            flags |= 0x1

        if not self.autoStart:
            flags |= 0x2
        
        self.headers = list()
        
        for attr_name, code, is_required in self._headerAttrs:
            hval = getattr(self, attr_name, None)
            
            if hval is not None:
                if attr_name == 'path':
                    hval = marshal.ObjectPath(hval)
                elif attr_name == 'signature':
                    hval = marshal.Signature(hval)
                    
                self.headers.append( [code, hval] )

        if self.signature:
            binBody = b''.join( marshal.marshal( self.signature, self.body )[1] )
        else:
            binBody = b''

        self.bodyLength = len(binBody)

        if newSerial:
            self.serial = DBusMessage._nextSerial

            DBusMessage._nextSerial += 1
        
        binHeader = b''.join(marshal.marshal(_headerFormat,
                                            [self.endian,
                                             self._messageType,
                                             flags,
                                             self._protocolVersion,
                                             self.bodyLength,
                                             self.serial,
                                             self.headers],
                                            lendian = self.endian == ord('l') )[1])
        
        headerPadding = marshal.pad['header']( len(binHeader) )

        self.rawHeader  = binHeader
        self.rawPadding = headerPadding
        self.rawBody    = binBody
        
        self.rawMessage = b''.join( [binHeader, headerPadding, binBody] )

        if len(self.rawMessage) > self._maxMsgLen:
            raise error.MarshallingError('Marshalled message exceeds maximum message size of %d' %
                                         (self._maxMsgLen,))



class MethodCallMessage (DBusMessage):
    """
    A DBus Method Call Message
    """
    _messageType = 1
    _headerAttrs = [ ('path',        1, True ),
                     ('interface',   2, False),
                     ('member',      3, True ),
                     ('destination', 6, False),
                     ('sender',      7, False),
                     ('signature',   8, False) ]


    def __init__(self, path, member, interface=None, destination=None,
                 signature=None, body=None,
                 expectReply=True, autoStart=True):
        """
        @param path: C{str} DBus object path
        @param member: C{str} Member name
        @param interface: C{str} DBus interface name or None
        @param destination: C{str} DBus bus name for message destination or
                            None
        @param signature: C{str} DBus signature string for encoding
                          C{self.body}
        @param body: C{list} of python objects to encode. Objects must match
                     the C{self.signature}
        @param expectReply: True if a Method Return message should be sent
                            in reply to this message
        @param autoStart: True if the Bus should auto-start a service to handle
                          this message if the service is not already running.
        """
        
        marshal.validateMemberName( member )
        
        if interface:
            marshal.validateInterfaceName(interface)
            
        if destination:
            marshal.validateBusName(destination)

        if path == '/org/freedesktop/DBus/Local':
            raise error.MarshallingError('/org/freedesktop/DBus/Local is a reserved path')
            
        self.path         = path
        self.member       = member
        self.interface    = interface
        self.destination  = destination
        self.signature    = signature
        self.body         = body
        self.expectReply  = expectReply
        self.autoStart    = autoStart

        self._marshal()
        


class MethodReturnMessage (DBusMessage):
    """
    A DBus Method Return Message
    """
    _messageType = 2
    _headerAttrs = [ ('reply_serial', 5, True ),
                     ('destination',  6, False),
                     ('sender',       7, False),
                     ('signature',    8, False) ]

    def __init__(self, reply_serial, body=None,
                 destination=None, signature=None):
        """
        @param reply_serial: C{int} serial number this message is a reply to
        @param destination: C{str} DBus bus name for message destination or
                            None
        @param signature: C{str} DBus signature string for encoding
                          C{self.body}
        @param body: C{list} of python objects to encode. Objects must match
                     the C{self.signature}
        """
        if destination:
            marshal.validateBusName(destination)

        self.reply_serial = marshal.UInt32(reply_serial)
        self.destination  = destination
        self.signature    = signature
        self.body         = body

        self._marshal()


class ErrorMessage (DBusMessage):
    """
    A DBus Error Message
    """
    _messageType = 3
    _headerAttrs = [ ('error_name',   4, True ),
                     ('reply_serial', 5, True ),
                     ('destination',  6, False),
                     ('sender',       7, False),
                     ('signature',    8, False) ]

    def __init__(self, error_name, reply_serial, destination=None, signature=None,
                 body=None, sender=None):
        """
        @param error_name: C{str} DBus error name
        @param reply_serial: C{int} serial number this message is a reply to
        @param destination: C{str} DBus bus name for message destination or
                            None
        @param signature: C{str} DBus signature string for encoding
                          C{self.body}
        @param body: C{list} of python objects to encode. Objects must match
                     the C{self.signature}
        @param sender: C{str} name of the originating Bus connection
        """
        if destination:
            marshal.validateBusName(destination)

        marshal.validateInterfaceName(error_name)

        self.error_name   = error_name
        self.reply_serial = marshal.UInt32(reply_serial)
        self.destination  = destination
        self.signature    = signature
        self.body         = body
        self.sender       = sender

        self._marshal()


        
class SignalMessage (DBusMessage):
    """
    A DBus Signal Message
    """
    _messageType = 4
    _headerAttrs = [ ('path',        1, True ),
                     ('interface',   2, True ),
                     ('member',      3, True ),
                     ('destination', 6, False),
                     ('sender',      7, False),
                     ('signature',   8, False) ]

    def __init__(self, path, member, interface, destination=None, signature=None,
                 body=None):
        """
        @param path: C{str} DBus object path of the object sending the signal
        @param member: C{str} Member name
        @param interface: C{str} DBus interface name or None
        @param destination: C{str} DBus bus name for message destination or
                            None
        @param signature: C{str} DBus signature string for encoding
                          C{self.body}
        @param body: C{list} of python objects to encode. Objects must match
                     the C{self.signature}
        """
        marshal.validateMemberName( member )
        marshal.validateInterfaceName(interface)
            
        if destination:
            marshal.validateBusName(destination)
            
        self.path        = path
        self.member      = member
        self.interface   = interface
        self.destination = destination
        self.signature   = signature
        self.body        = body

        self._marshal()


_mtype = { 1 : MethodCallMessage,
           2 : MethodReturnMessage,
           3 : ErrorMessage,
           4 : SignalMessage }

_hcode = { 1 : 'path',
           2 : 'interface',
           3 : 'member',
           4 : 'error_name',
           5 : 'reply_serial',
           6 : 'destination',
           7 : 'sender',
           8 : 'signature',
           9 : 'unix_fds' }


def parseMessage( rawMessage ):
    """
    Parses the raw binary message and returns a L{DBusMessage} subclass

    @type rawMessage: C{str}
    @param rawMessage: Raw binary message to parse

    @rtype: L{DBusMessage} subclass
    @returns: The L{DBusMessage} subclass corresponding to the contained
              message
    """

    lendian = rawMessage[0] == b'l'[0]

    nheader, hval = marshal.unmarshal(_headerFormat, rawMessage, 0, lendian)

    messageType = hval[1]

    if not messageType in _mtype:
        raise error.MarshallingError('Unknown Message Type: ' + str(messageType))

    m = object.__new__( _mtype[messageType] )

    m.endian = hval[0]

    m.expectReply = not (hval[2] & 0x1)

    m.autoStart = not (hval[2] & 0x2)

    m.rawHeader = rawMessage[:nheader]

    npad = nheader % 8 and (8 - nheader%8) or 0

    m.rawPadding = rawMessage[nheader: nheader+npad]

    m.rawBody = rawMessage[ nheader + npad: ]

    m.serial = hval[5]
    
    for code, v in hval[6]:
        try:
            setattr(m, _hcode[code], v)
        except KeyError:
            pass
        
    if m.signature:
        nbytes, m.body = marshal.unmarshal(m.signature, m.rawBody, lendian = lendian)

    return m

    
        
        
        
        
