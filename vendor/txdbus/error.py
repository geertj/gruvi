"""
DBus errors
@author: Tom Cocagne
"""

class DBusException (Exception):
    """
    Base class for all expected DBus exceptions
    """
    pass


class DBusAuthenticationFailed (DBusException):
    pass


class MarshallingError (DBusException):
    """
    Thrown when errors are encountered by the marshalling/unmarshalling
    code
    """
    pass


class TimeOut (DBusException):
    """
    Used to indicate a timeout for remote DBus method calls that
    request a timeout value
    """
    pass


class IntrospectionFailed (DBusException):
    """
    Thrown if remote object introspection fails
    """
    pass


class RemoteError (DBusException):
    """
    Thrown in response to errors encountered during a remote
    method invocation. 

    @ivar errName: DBus error name
    @type errName: C{string}
    """
    message = ''

    def __init__(self, errName):
        self.errName = errName

    def __str__(self):
        return '%s: %s' % (self.errName, self.message) if self.message else self.errName

        
class FailedToAcquireName(DBusException):
    """
    Indicates a failed attempt to acquire a bus name
    """
    def __init__(self, new_name, returnCode):
        head = 'Failed to acquire bus name "%s": ' % (new_name,)
        if returnCode == 2:
            tail = 'Queued for name acquisition'
        elif returnCode == 3:
            tail = 'Name in use'
        else:
            tail = 'Unknown reason'

        DBusException.__init__(self, head + tail)
        
        self.returnCode = returnCode
        
