import unittest
from struct import pack

import gruvi.txdbus.marshal as m

#dbus_types = [ ('BYTE',        'y',     1),
#               ('BOOLEAN',     'b',     4),
#               ('INT16',       'n',     2),
#               ('UINT16',      'q',     2),
#               ('INT32',       'i',     4),
#               ('UINT32',      'u',     4),
#               ('INT64',       'x',     8),
#               ('UINT64',      't',     8),
#               ('DOUBLE',      'd',     8),
#               ('STRING',      's',     4), # (4-byte align for length)
#               ('OBJECT_PATH', '4',     4), # (4-byte align for length)
#               ('SIGNATURE',   'g',     1),
#               ('ARRAY',       'a',     4), # (4-byte align for length)
#               ('STRUCT',      '(',     8),
#               ('VARIANT',     'v',     1), # (1-byte align for signature)
#               ('DICT_ENTRY',  '{',     8),
#               ('UNIX_FD',     'h',     4)
#               ]

class SigFromPyTests(unittest.TestCase):

    def t(self, p, s):
        self.assertEquals( m.sigFromPy(p), s )

    def test_int(self):
        self.t(1,'i')

    def test_float(self):
        self.t(1.0,'d')

    def test_string(self):
        self.t('foo','s')

    def test_list(self):
        self.t([1],'ai')

    def test_dict(self):
        self.t(dict(foo=1),'a{si}')

    def test_fail(self):
        class I(object):
            pass
        self.assertRaises(m.MarshallingError, m.sigFromPy, I())

    def test_class(self):
        class V(object):
            dbusSignature = 'ii'
        self.t(V(), 'ii')
        

class AlignmentTests(unittest.TestCase):

    def test_no_padding(self):
        self.assertEquals( m.pad['y']( 1 ), b'' )

    def test_2align(self):
        self.assertEquals( m.pad['n']( 1 ), b'\0')

    def test_8align(self):
        self.assertEquals( m.pad['t']( 1 ), b'\0'*7)

    def test_0align(self):
        self.assertEquals( m.pad['t']( 8 ), b'')

    def test_mid_align(self):
        self.assertEquals( m.pad['t']( 4 ), b'\0'*4)


        
class SignatureIteratorTests(unittest.TestCase):

    def ae(self, sig, expected):
        self.assertEquals( list(m.genCompleteTypes(sig)), expected )
    
    def test_one(self):
        self.ae( 'i', ['i'])

    def test_two(self):
        self.ae( 'ii', ['i', 'i'])

    def test_multi(self):
        self.ae( 'isydnq', ['i', 's', 'y', 'd', 'n', 'q'])

    def test_struct(self):
        self.ae( 'i(ii)i', ['i', '(ii)', 'i'] )

    def test_embedded_struct(self):
        self.ae( 'i(i(ss)i)i', ['i', '(i(ss)i)', 'i'] )

    def test_embedded_array(self):
        self.ae( 'i(iaii)i', ['i', '(iaii)', 'i'] )

    def test_array_of_struct(self):
        self.ae( 'ia(iii)i', ['i', 'a(iii)', 'i'] )

    def test_array_of_dict(self):
        self.ae( 'ia{s(ii)}i', ['i', 'a{s(ii)}', 'i'] )


class TestMarshal(unittest.TestCase):

    def check(self, sig, var_list, expected_encoding, little_endian=True):
        if not isinstance(var_list, list):
            var_list = [var_list]
        nbytes, chunks = m.marshal( sig, var_list, 0, little_endian  )
        bin_str = b''.join(chunks)
        self.assertEquals( nbytes, len(expected_encoding), "Byte length mismatch. Expected %d. Got %d" % (len(expected_encoding), nbytes) )
        self.assertEquals( bin_str, expected_encoding, "Binary encoding differs from expected value" )
        
        

class TestSimpleMarshal(TestMarshal):
    
    def test_byte(self):
        self.check( 'y', 1, b'\1' )

    def test_int16(self):
        self.check( 'n', -1024, pack('h', -1024))

    def test_uint16(self):
        self.check( 'q', 1024, pack('H', 1024))

    def test_int32(self):
        self.check( 'i', -70000, pack('i', -70000))

    def test_uint32(self):
        self.check( 'u', 70000, pack('I', 70000))

    def test_int64(self):
        self.check( 'x', -70000, pack('q', -70000))

    def test_uint64(self):
        self.check( 't', 70000, pack('Q', 70000))

    def test_double(self):
        self.check( 'd', 3.14, pack('d', 3.14))

    def test_boolean(self):
        self.check( 'b', True, pack('i',1))

    def test_string(self):
        self.check( 's', 'Hello World', pack('i12s', 11, b'Hello World'))

    def test_string_wrong_type(self):
        self.assertRaises(m.MarshallingError, self.check, 's', 1, b'')

    def test_string_embedded_null(self):
        self.assertRaises(m.MarshallingError, self.check, 's', b'Hello\0World', b'')

    def test_signature1(self):
        self.check( 'g', 'i', pack('BcB', 1, b'i', 0) )

    def test_signature2(self):
        self.check( 'g', '(ii)', pack('B4sB', 4, b'(ii)', 0) )

    def test_endian(self):
        self.check( 'x', 70000, pack('>q', 70000), False)

        
        

class TestStructMarshal(TestMarshal):

    def test_one(self):
        self.check('(i)', [[1]], pack('i',1))

    def test_two(self):
        self.check('(ii)', [[2,3]], pack('ii',2,3))

    def test_pad(self):
        self.check('(yx)', [[1,70000]], pack('Bxxxxxxxq',1,70000))

    def test_string(self):
        self.check('(ysy)', [[1, 'foo', 2]], pack('Bxxxi3sxB', 1, 3, b'foo', 2))

    def test_substruct(self):
        self.check('(y(ii)y)', [[1, [3,4], 2]], pack('BxxxxxxxiiB', 1, 3, 4, 2))

    def test_substruct_endian(self):
        self.check('(y(ii)y)', [[1, [3,4], 2]], pack('>BxxxxxxxiiB', 1, 3, 4, 2), False)

    def test_custom(self):
        class S:
            dbusOrder  = 'a b'.split()

            def __init__(self):
                self.a = 1
                self.b = 2

        self.check('(ii)', [S()], pack('ii',1,2))




class TestArrayMarshal(TestMarshal):

    def test_byte(self):
        self.check('ay', [[1,2,3,4]], pack('iBBBB', 4, 1,2,3,4))

    def test_string(self):
        self.check('as', [['x', 'foo']], pack('ii2sxxi4s', 16, 1, b'x', 3, b'foo'))

    def test_struct(self):
        self.check('a(ii)', [[[1,2],[3,4]]], pack('ixxxxiiii', 16, 1,2,3,4))

    def test_struct_padding(self):
        self.check('a(yy)', [[[1,2],[3,4]]], pack('ixxxxBBxxxxxxBB', 10, 1,2,3,4))

    def test_dict(self):
        self.check('a{yy}', [{1:2, 3:4}], pack('ixxxxBBxxxxxxBB', 10, 1,2,3,4))

    def test_dict_strings(self):
        self.check('a{ss}',
                   [[('foo','bar'), ('x','y')]],
                   pack('ixxxxi4si4si2sxxi2s', 30, 3, b'foo', 3, b'bar', 1, b'x', 1, b'y'))

    def test_invalid_array(self):
        self.assertRaises(m.MarshallingError, self.check, 'a{yy}', 1, '')
    
                
class TestVariantMarshal(TestMarshal):

    def test_byte(self):
        self.check('v', [1], pack('B2si', 1, b'i', 1))

    def test_struct(self):
        class S:
            dbusSignature = '(ii)'
            dbusOrder     = 'a b'.split()

            def __init__(self):
                self.a = 1
                self.b = 2

        self.check('v', [S()], pack('B5sxxii', 4, b'(ii)', 1,2))


#-------------------------------------------------------------------------------
# Unmarshalling
#-------------------------------------------------------------------------------

def check_equal( a, b ):
    try:
        if isinstance(a, list):
            check_list(a,b)
        elif isinstance(a, dict):
            check_dict(a,b)
        elif not a == b:
            raise Exception()
    except:
        return False

    return True


def check_list( a, b ):
    if not isinstance(b, list):
        raise Exception()
    if len(a) != len(b):
        raise Exception()
    for x,y in zip(a,b):
        check_equal(x,y)

        
def check_dict( a, b ):
    if not isinstance( b, dict ):
        raise Exception()
    if not len(a.keys()) == len(b.keys()):
        raise Exception()
    aset = set(a.keys())
    bset = set(b.keys())
    if aset - bset:
        raise Exception()
    for x in a.keys():
        check_equal( a[x], b[x] )
    
        
class TestUnmarshal(unittest.TestCase):

    def check(self, sig, expected_value, encoding):
        nbytes, value = m.unmarshal( sig, encoding, 0 )
        self.assertEquals( nbytes, len(encoding), "Unmarshalling length mismatch. Expected %d bytes consumed. Got %d" % (len(encoding), nbytes) )        
        self.assertTrue( check_equal([expected_value], value), 'Value mismatch. Expected: "%s". Got: "%s"' % (repr(expected_value), repr(value)))
        
        

class TestSimpleUnmarshal(TestUnmarshal):
    
    def test_byte(self):
        self.check( 'y', 1, b'\1' )

    def test_int16(self):
        self.check( 'n', -1024, pack('h', -1024))

    def test_uint16(self):
        self.check( 'q', 1024, pack('H', 1024))

    def test_int32(self):
        self.check( 'i', -70000, pack('i', -70000))

    def test_uint32(self):
        self.check( 'u', 70000, pack('I', 70000))

    def test_int64(self):
        self.check( 'x', -70000, pack('q', -70000))

    def test_uint64(self):
        self.check( 't', 70000, pack('Q', 70000))

    def test_double(self):
        self.check( 'd', 3.14, pack('d', 3.14))

    def test_boolean(self):
        self.check( 'b', True, pack('i',1))

    def test_string(self):
        self.check( 's', 'Hello World', pack('i12s', 11, b'Hello World'))

    def test_signature1(self):
        self.check( 'g', 'i', pack('BcB', 1, b'i', 0) )

    def test_signature2(self):
        self.check( 'g', '(ii)', pack('B4sB', 4, b'(ii)', 0) )


        
        

class TestStructUnmarshal(TestUnmarshal):

    def test_one(self):
        self.check('(i)', [[1]], pack('i',1))

    def test_two(self):
        self.check('(ii)', [[2,3]], pack('ii',2,3))

    def test_pad(self):
        self.check('(yx)', [[1,70000]], pack('Bxxxxxxxq',1,70000))

    def test_string(self):
        self.check('(ysy)', [[1, 'foo', 2]], pack('Bxxxi3sxB', 1, 3, b'foo', 2))

    def test_substruct(self):
        self.check('(y(ii)y)', [[1, [3,4], 2]], pack('BxxxxxxxiiB', 1, 3, 4, 2))




class TestArrayUnmarshal(TestUnmarshal):

    def test_byte(self):
        self.check('ay', [[1,2,3,4]], pack('iBBBB', 4, 1,2,3,4))

    def test_string(self):
        self.check('as', [['x', 'foo']], pack('ii2sxxi4s', 16, 1, b'x', 3, b'foo'))

    def test_struct(self):
        self.check('a(ii)', [[[1,2],[3,4]]], pack('ixxxxiiii', 16, 1,2,3,4))

    def test_struct_padding(self):
        self.check('a(yy)', [[[1,2],[3,4]]], pack('ixxxxBBxxxxxxBB', 10, 1,2,3,4))

    def test_dict(self):
        self.check('a{yy}', [{1:2, 3:4}], pack('ixxxxBBxxxxxxBB', 10, 1,2,3,4))

    def test_dict_strings(self):
        self.check('a{ss}',
                   [{'foo':'bar', 'x':'y'}],
                   pack('ixxxxi4si4si2sxxi2s', 30, 3, b'foo', 3, b'bar', 1, b'x', 1, b'y'))

    def test_bad_length(self):
        self.assertRaises(m.MarshallingError, self.check, 'a(ii)', [[[1,2],[3,4]]], pack('ixxxxiiii', 15, 1,2,3,4))
    
                
class TestVariantUnmarshal(TestUnmarshal):

    def test_byte(self):
        self.check('v', [1], pack('B2si', 1, b'i', 1))

    def test_struct(self):
        self.check('v', [[1,2]], pack('B5sxxii', 4, b'(ii)', 1,2))

        

if __name__ == '__main__':
    unittest.main()
