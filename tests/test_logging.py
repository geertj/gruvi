#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import re
import logging
import unittest
import six

from support import UnitTest
from gruvi.logging import get_logger


class TestLogging(UnitTest):

    @classmethod
    def setUpClass(cls):
        super(TestLogging, cls).setUpClass()
        logger = logging.getLogger('gruvi_test')
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        stream = six.StringIO()
        handler = logging.StreamHandler(stream)
        template = '%(levelname)s %(message)s'
        handler.setFormatter(logging.Formatter(template))
        logger.addHandler(handler)
        cls.logger = logger
        cls.stream = stream

    @classmethod
    def get_messages(cls):
        value = cls.stream.getvalue()
        cls.stream.seek(0)
        cls.stream.truncate()
        messages = [m.rstrip() for m in value.splitlines()]
        return messages

    def test_get_logger(self):
        # Ensure that get_logger() returns the correct logger.
        logger = get_logger(name='gruvi_test')
        self.assertIs(logger._logger, self.logger)
        logger = get_logger()
        self.assertIsNot(logger._logger, self.logger)

    def test_get_logger_context(self):
        # Ensure that a different logger is returned for different contexts.
        l1 = get_logger(name='gruvi_test')
        l2 = get_logger(context='foo', name='gruvi_test')
        self.assertIsNot(l1, l2)
        l3 = get_logger(context='bar', name='gruvi_test')
        self.assertIsNot(l2, l3)

    def test_debug(self):
        # Ensure that DEBUG level output works if the level is set accordingly
        self.logger.setLevel(logging.DEBUG)
        logger = get_logger(name='gruvi_test')
        logger.debug('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('DEBUG', messages[0])
        self.assertIn('foo bar', messages[0])
        self.logger.setLevel(100)
        logger.debug('foo baz')
        messages = self.get_messages()
        self.assertEqual(len(messages), 0)

    def test_info(self):
        # Ensure that INFO level output works if the level is set accordingly
        self.logger.setLevel(logging.INFO)
        logger = get_logger(name='gruvi_test')
        logger.info('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('INFO', messages[0])
        self.assertIn('foo bar', messages[0])
        self.logger.setLevel(100)
        logger.info('foo baz')
        messages = self.get_messages()
        self.assertEqual(len(messages), 0)

    def test_warning(self):
        # Ensure that WARNING level output works if the level is set accordingly
        self.logger.setLevel(logging.WARNING)
        logger = get_logger(name='gruvi_test')
        logger.warning('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('WARNING', messages[0])
        self.assertIn('foo bar', messages[0])
        self.logger.setLevel(100)
        logger.warning('foo baz')
        messages = self.get_messages()
        self.assertEqual(len(messages), 0)

    def test_error(self):
        # Ensure that ERROR level output works if the level is set accordingly
        self.logger.setLevel(logging.ERROR)
        logger = get_logger(name='gruvi_test')
        logger.error('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('ERROR', messages[0])
        self.assertIn('foo bar', messages[0])
        self.logger.setLevel(100)
        logger.error('foo baz')
        messages = self.get_messages()
        self.assertEqual(len(messages), 0)

    def test_critical(self):
        # Ensure that CRITCAL level output works if the level is set accordingly
        self.logger.setLevel(logging.CRITICAL)
        logger = get_logger(name='gruvi_test')
        logger.critical('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('CRITICAL', messages[0])
        self.assertIn('foo bar', messages[0])
        self.logger.setLevel(100)
        logger.critical('foo baz')
        messages = self.get_messages()
        self.assertEqual(len(messages), 0)

    def test_exception(self):
        # Ensure that a logged exception includes a backtrace
        self.logger.setLevel(logging.ERROR)
        logger = get_logger(name='gruvi_test')
        try:
            raise ValueError('foo bar')
        except ValueError:
            logger.exception('baz qux')
        messages = self.get_messages()
        self.assertGreater(len(messages), 2)
        self.assertIn('ERROR', messages[0])
        self.assertIn('baz qux', messages[0])
        self.assertIn('Traceback', messages[1])
        self.assertIn('foo bar', messages[-1])

    re_frame = re.compile(r'\|test_[a-z]+\.py:[0-9]+\]')

    def test_debug_frame_info(self):
        # Ensure that frame info is appended when the level is DEBUG
        self.logger.setLevel(logging.DEBUG)
        logger = get_logger(name='gruvi_test')
        logger.info('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertTrue(self.re_frame.search(messages[0]))
        self.logger.setLevel(logging.INFO)
        logger.info('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertFalse(self.re_frame.search(messages[0]))

    def test_context(self):
        # Ensure that a logging context is added.
        self.logger.setLevel(logging.DEBUG)
        logger = get_logger('fooctx', name='gruvi_test')
        logger.debug('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('fooctx', messages[0])
        self.assertIn('foo bar', messages[0])
        logger = get_logger('barctx', name='gruvi_test')
        logger.debug('foo bar')
        messages = self.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertNotIn('fooctx', messages[0])
        self.assertIn('barctx', messages[0])
        self.assertIn('foo bar', messages[0])


if __name__ == '__main__':
    unittest.main()
