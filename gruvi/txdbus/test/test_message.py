import os
import unittest

from gruvi.txdbus import error, message

class MessageTester(unittest.TestCase):
    def test_too_long(self):
        class E(message.ErrorMessage):
            _maxMsgLen         = 1

        def c():
            E('foo.bar', 5)

        self.assertRaises(error.MarshallingError, c)

    def test_reserved_path(self):
        def c():
            message.MethodCallMessage('/org/freedesktop/DBus/Local', 'foo')
        self.assertRaises(error.MarshallingError, c)

    def test_invalid_message_type(self):
        class E(message.ErrorMessage):
            _messageType=99
        try:
            message.parseMessage(E('foo.bar', 5).rawMessage)
            self.assertTrue(False)
        except Exception as e:
            self.assertEquals(str(e), 'Unknown Message Type: 99')
        
    
