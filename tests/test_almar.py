# encoding=utf-8
from __future__ import unicode_literals

import json
import os
import re
import sys
import unittest
from collections import OrderedDict

import pytest
import responses
import logging
import yaml
from mock import Mock, MagicMock, patch, ANY, call
from io import BytesIO
from io import open
from six import text_type
from contextlib import contextmanager
from functools import wraps
from textwrap import dedent

from almar.bib import Bib
from almar.almar import run, get_config, job_args, parse_args, get_concept
from almar.authorities import Vocabulary
from almar.sru import SruClient, SruErrorResponse, TooManyResults, NSMAP
from almar.alma import Alma
from almar.job import Job
from almar.concept import Concept
from almar.util import normalize_term, parse_xml, ANY_VALUE, INTERACTIVITY_NONE
from almar.marc import Record
from almar.task import DeleteTask, ReplaceTask, AddTask

log = logging.getLogger()
log.setLevel(logging.DEBUG)


def get_sample(filename, as_xml=False):
    with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data/%s' % filename), encoding='utf-8') as fp:
        body = fp.read()
    if as_xml:
        return parse_xml(body)
    return body


def record_search(record, tag, sf):
    return len(list(record.search(Concept(tag, sf), ignore_extra_subfields=True)))


def record_search_exact(record, tag, sf):
    return len(list(record.search(Concept(tag, sf), ignore_extra_subfields=False)))


def strip_colors(txt):
    return re.sub(r'\x1b(\[.*?[@-~]|\].*?(\x07|\x1b\\))', '', text_type(txt))


class TestRecord(unittest.TestCase):

    @staticmethod
    def getRecord():
        return Record(parse_xml('''
              <record>
                <datafield tag="245" ind1="1" ind2="0">
                  <subfield code="a">A</subfield>
                  <subfield code="b">B</subfield>
                  <subfield code="c">C</subfield>
                  <subfield code="p">P</subfield>
                  <subfield code="n">N</subfield>
                </datafield>
                <datafield ind1=" " ind2=" " tag="260">
                  <subfield code="a">London</subfield>
                  <subfield code="b">A &amp; C Black</subfield>
                  <subfield code="c">2003</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="2">humord</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Atferd</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="x">Atferd</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Atferd</subfield>
                  <subfield code="x">Mennesker</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="x">Dagbøker</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="648" ind1=" " ind2="7">
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="655" ind1=" " ind2="7">
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="653" ind1=" " ind2=" ">
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="a">Algoritmer</subfield>
                </datafield>
              </record>
        '''.encode('utf-8')))

    def testTitle(self):
        record = self.getRecord()
        assert 'A : B. P. N / C. 2003' == record.title()

    def testFind650a(self):
        """
        1st field should not match because of $2
        2nd field should match
        4th and 6th value should match because we didn't restrict to $x: None
        The rest should not match because of $a or tag != 650
        """
        concept = Concept('650', OrderedDict((('2', 'noubomn'), ('a', 'Mønstre'))))
        fields1 = list(self.getRecord().search(concept, ignore_extra_subfields=False))
        fields2 = list(self.getRecord().search(concept, ignore_extra_subfields=True))

        assert len(fields1) == 1
        assert len(fields2) == 3

    def testFind650x(self):
        """
        4th field should match because of $x
        The rest should not match because of $a or tag != 650
        """
        concept = Concept('650', OrderedDict((('2', 'noubomn'), ('x', 'Atferd'))))
        fields1 = list(self.getRecord().search(concept, ignore_extra_subfields=False))
        fields2 = list(self.getRecord().search(concept, ignore_extra_subfields=True))

        assert len(fields1) == 0
        assert len(fields2) == 1
        assert fields2[0].node.findtext('subfield[@code="a"]') == 'Mønstre'
        assert fields2[0].node.findtext('subfield[@code="x"]') == 'Atferd'

    def testMove(self):
        """
        Test that only the 3rd field is moved. Specifically, the 4th and 5th
        fields should not be moved!
        """
        record = self.getRecord()
        assert record_search(record, '655', {'2': 'noubomn'}) == 1

        src = Concept('650', OrderedDict((('a', 'Atferd'), ('2', 'noubomn'))))
        dst = Concept('655', OrderedDict((('a', 'Atferd'), ('2', 'noubomn'))))
        task = ReplaceTask(src, dst)
        self.assertTrue(self.match_record(task, record))

        task.run(record)
        self.assertFalse(self.match_record(task, record))
        assert record_search(record, '655', {'2': 'noubomn'}) == 2

    def testReplace2to2(self):
        """Replace $a : $x with $a : $x"""
        record = self.getRecord()

        tasks = Job.generate_replace_tasks(Concept('650', OrderedDict((('a', 'Mønstre'), ('x', 'Dagbøker'), ('2', 'noubomn')))),
                                           Concept('650', OrderedDict((('a', 'Test to'), ('x', 'Atlas'), ('2', 'noubomn')))))

        assert len(tasks) == 1
        for task in tasks:
            self.assertTrue(self.match_record(task, record))
            task.run(record)
            self.assertFalse(self.match_record(task, record))
            assert strip_colors(task) == 'Replace `650 $a Mønstre $x Dagbøker $2 noubomn` → `650 $a Test to $x Atlas $2 noubomn`'

        assert record_search(record, '650', {'a': 'Mønstre', 'x': 'Dagbøker', '2': 'noubomn'}) == 0
        assert record_search(record, '650', {'a': 'Test to', 'x': 'Atlas', '2': 'noubomn'}) == 1

    def testReplace1to2(self):
        """Replace $a with $a : $x"""
        record = self.getRecord()
        tasks = Job.generate_replace_tasks(Concept('650', OrderedDict((('a', 'Mønstre'), ('x', None), ('2', 'noubomn')))),
                                           Concept('650', OrderedDict((('a', 'Mønstre'), ('x', 'Test'), ('2', 'noubomn')))))

        assert len(tasks) == 1
        for task in tasks:
            self.assertTrue(self.match_record(task, record))
            task.run(record)
            self.assertFalse(self.match_record(task, record))
            assert strip_colors(task) == 'Replace `650 $a Mønstre $2 noubomn` → `650 $a Mønstre $x Test $2 noubomn`'

        fields = list(record.search(Concept('650', {'a': 'Mønstre', 'x': 'Test', '2': 'noubomn'}), ignore_extra_subfields=True))
        assert len(fields) == 1
        assert text_type(fields[0]) == '650 #7 $a Mønstre $x Test $2 noubomn'  # this really is a tests for the order of arguments

    def testReplace2to1(self):
        """Replace $a : $x with $a"""
        record = self.getRecord()
        tasks = Job.generate_replace_tasks(Concept('650', OrderedDict((('a', 'Mønstre'), ('x', 'Atferd'), ('2', 'noubomn')))),
                                           Concept('650', OrderedDict((('a', 'Ost'), ('x', None), ('2', 'noubomn')))))

        assert len(tasks) == 1
        for task in tasks:
            self.assertTrue(self.match_record(task, record))
            task.run(record)
            self.assertFalse(self.match_record(task, record))
            assert strip_colors(task) == 'Replace `650 $a Mønstre $x Atferd $2 noubomn` → `650 $a Ost $2 noubomn`'

        assert record_search(record, '650', {'a': 'Ost', 'x': None, '2': 'noubomn'}) == 1

    def testReplace1to1(self):
        """Replace $a with $a"""
        record = self.getRecord()
        tasks = Job.generate_replace_tasks(Concept('650', OrderedDict((('a_or_x', 'Atferd'), ('2', 'noubomn')))),
                                           Concept('650', OrderedDict((('a_or_x', 'Testerstatning'), ('2', 'noubomn')))))

        assert len(tasks) == 3  # exact $a, fuzzy $a, fuzzy $x
        modified = 0
        for task in tasks:
            modified += task.run(record)

        assert modified == 3
        assert record_search(record, '650', {'a': 'Testerstatning', '2': 'noubomn'}) == 2
        assert record_search(record, '650', {'a': 'Testerstatning', 'x': 'Mennesker', '2': 'noubomn'}) == 1
        assert record_search(record, '650', {'x': 'Testerstatning', '2': 'noubomn'}) == 1
        assert record_search(record, '650', {'a': 'Mønstre', 'x': 'Testerstatning', '2': 'noubomn'}) == 1

    def testReplace648(self):
        """Replace 648 field"""
        record = self.getRecord()
        tasks = Job.generate_replace_tasks(Concept('648', OrderedDict((('a_or_x', 'Mønstre'), ('2', 'noubomn')))),
                                           Concept('648', OrderedDict((('a_or_x', 'Testerstatning'), ('2', 'noubomn')))))

        assert len(tasks) == 3  # exact $a, fuzzy $a, fuzzy $x
        modified = 0
        for task in tasks:
            modified += task.run(record)

        assert modified == 1
        assert record_search(record, '648', {'a': 'Testerstatning', '2': 'noubomn'}) == 1

    def testAddTask(self):
        """Add field"""
        record = self.getRecord()
        task = AddTask(Concept('600', OrderedDict((('a', 'ABCDEF'), ('d', '1983'), ('2', 'test')))))
        modified = task.run(record)

        assert modified == 1
        assert record_search_exact(record, '600', {'a': 'ABCDEF', 'd': '1983', '2': 'test'}) == 1

    def testRemove(self):
        """Remove subject"""
        record = self.getRecord()
        task = DeleteTask(Concept('650', OrderedDict((('a', 'atferd'), ('2', 'noubomn')))))

        fc0 = len(record.el.findall('.//datafield[@tag="650"]'))
        modified = task.run(record)
        fc1 = len(record.el.findall('.//datafield[@tag="650"]'))

        assert modified == 1
        assert fc1 == fc0 - 1

    def testAddDoesNotAddDuplicates(self):
        """Add subject"""
        record = self.getRecord()
        task = AddTask(Concept('650', OrderedDict((('a', 'atferd'), ('2', 'noubomn')))))

        fc0 = len(record.el.findall('.//datafield[@tag="650"]'))
        modified = task.run(record)
        fc1 = len(record.el.findall('.//datafield[@tag="650"]'))

        # The subject will added, before being removed as a duplicated,
        # so the record is still marked as modified. We could perhaps
        # improve this in the future.
        assert modified == 1

        assert fc1 == fc0

    def testAdd(self):
        """Add subject"""
        record = self.getRecord()
        task = AddTask(Concept('650', OrderedDict((('a', 'something new'), ('2', 'noubomn')))))

        fc0 = len(record.el.findall('.//datafield[@tag="650"]'))
        modified = task.run(record)
        fc1 = len(record.el.findall('.//datafield[@tag="650"]'))

        assert modified == 1
        assert fc1 == fc0 + 1

    def testCaseSensitive(self):
        """Se2arch should in general be case sensitive ..."""
        record = self.getRecord()
        tasks = Job.generate_replace_tasks(Concept('650', OrderedDict((('a_or_x', 'ATFerd'), ('2', 'noubomn')))),
                                           Concept('650', OrderedDict((('a_or_x', 'Testerstatning'), ('2', 'noubomn'))))
                                           )

        assert len(tasks) == 3  # exact $a, fuzzy $a, fuzzy $x
        for task in tasks:
            self.assertFalse(self.match_record(task, record))

    def match_record(self, task, record):
        for field in record.fields:
            if field.tag.startswith('6'):
                if task.match_field(field):
                    return True
        return False

    def testCaseInsensitiveFirstCharacter(self):
        """
        Search should in general be case sensitive ... except for the first character.
        The replacement term should not be normalized.
        """
        record = self.getRecord()
        tasks = Job.generate_replace_tasks(get_concept('650 atferd', 'noubomn'),
                                           get_concept('650 testerstatning', 'noubomn')
                                           )

        for task in tasks:
            print(task)

        assert len(tasks) == 3  # exact $a, fuzzy $a, fuzzy $x
        modified = 0
        for task in tasks:
            modified += task.run(record)

        assert strip_colors(tasks[0]) == (
            'Replace `650 $a atferd $2 noubomn` → `650 $a testerstatning $2 noubomn`'
        )
        assert strip_colors(tasks[1]) == (
            'Replace `650 $a atferd $2 noubomn` → `650 $a testerstatning $2 noubomn` (ignoring any extra subfields)'
        )
        assert strip_colors(tasks[2]) == (
            'Replace `650 $x atferd $2 noubomn` → `650 $x testerstatning $2 noubomn` (ignoring any extra subfields)'
        )

        assert modified == 3
        f = record.el.xpath('.//datafield[@tag="650"]/subfield[@code="a"][text()="testerstatning"]')
        assert len(f) == 2

        f = record.el.xpath('.//datafield[@tag="650"]/subfield[@code="x"][text()="testerstatning"]')
        assert len(f) == 1

    def testDuplicatesAreRemoved(self):
        # If the new term already exists, don't duplicate it
        bib = Bib("""
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Mønstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """)

        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 2

        modified = ReplaceTask(
            Concept('650', OrderedDict((('a', 'Mønstre'), ('2', 'noubomn')))),
            Concept('650', OrderedDict((('a', 'Monstre'), ('2', 'noubomn'))))
        ).run(bib.marc_record)

        assert modified == 1
        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 1

    def testDuplicatesAreRemovedIgnoreD0(self):
        # Two fields are considered duplicates even if one doesn't have a $0 value
        bib = Bib("""
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Mønstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """)

        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 2

        modified = ReplaceTask(
            Concept('650', OrderedDict({'a': 'Mønstre', '2': 'noubomn', '0': ANY_VALUE})),
            Concept('650', OrderedDict((('a', 'Monstre'), ('2', 'noubomn'), ('0', '123'))))
        ).run(bib.marc_record)

        assert modified == 2  # change $a, add $0
        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 1

    def testDuplicatesAreRemovedUponMoveAndFirstCharacterIsCaseInsensitive(self):
        # If the new term already exists, don't duplicate it
        bib = Bib("""
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="648">
                    <subfield code="a">monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """)

        assert len(bib.doc.findall('record/datafield[@tag="648"]')) == 1
        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 2

        ReplaceTask(
            Concept('648', OrderedDict((('a', 'Monstre'), ('2', 'noubomn')))),
            Concept('650', OrderedDict((('a', 'Monstre'), ('2', 'noubomn'))))
        ).run(bib.marc_record)

        assert len(bib.doc.findall('record/datafield[@tag="648"]')) == 0
        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 1


class TestRecordModifyIdentifiers(unittest.TestCase):

    @staticmethod
    def make_bib(identifier=None):
        sf0 = ''
        if identifier is not None:
            sf0 = '<subfield code="0">%s</subfield>' % identifier
        rec = """
              <bib>
                <record>
                  <datafield tag="650" ind1=" " ind2="7">
                    <subfield code="a">Middelalder</subfield>
                    <subfield code="2">noubomn</subfield>
                    %s
                  </datafield>
                </record>
            </bib>
        """ % sf0
        bib = Bib(rec)

        return bib

    @staticmethod
    def make_tasks(src_identifier=None, dst_identifier=None):
        src = {'a': 'Middelalder', '2': 'noubomn'}
        dst = {'a': 'Middelalderen', '2': 'noubomn'}
        if src_identifier is not None:
            src['0'] = src_identifier
        if dst_identifier is not None:
            dst['0'] = dst_identifier

        src = Concept('650', src)
        dst = Concept('650', dst)
        tasks = Job.generate_replace_tasks(src, dst)

        return tasks

    @classmethod
    def run_tasks(cls, bib, src_identifier=None, dst_identifier=None):
        modifications = 0
        for task in cls.make_tasks(src_identifier, dst_identifier):
            modifications += task.run(bib.marc_record)
        return modifications

    @staticmethod
    def get_term(bib):
        f650 = bib.doc.findall('record/datafield[@tag="650"]')
        return f650[0].findtext('subfield[@code="a"]')

    @staticmethod
    def get_identifier(bib):
        f650 = bib.doc.findall('record/datafield[@tag="650"]')
        return f650[0].findtext('subfield[@code="0"]')

    def testAddIdentifierIfNotPresent(self):
        # If no $0 value is present, it should be added
        bib = self.make_bib()
        modifications = self.run_tasks(bib, src_identifier=ANY_VALUE, dst_identifier='REAL12345')

        assert modifications == 2  # (1) edit $a (2) add $0
        assert self.get_identifier(bib) == 'REAL12345'
        assert self.get_term(bib) == 'Middelalderen'

    def testUpdateIdentifierIfMatching(self):
        # If the $0 value matches the one in the query, it should be updated
        bib = self.make_bib('REAL00000')
        modifications = self.run_tasks(bib, src_identifier='REAL00000', dst_identifier='REAL12345')

        assert modifications == 2  # (1) edit $a (2) add $0
        assert self.get_identifier(bib) == 'REAL12345'
        assert self.get_term(bib) == 'Middelalderen'

    def testUpdateIdentifierIfMatchingAnyValue(self):
        # If the query contains $0 ANY_VALUE, we should replace it
        bib = self.make_bib('REAL00000')
        modifications = self.run_tasks(bib, src_identifier=ANY_VALUE, dst_identifier='REAL12345')

        assert modifications == 2  # (1) edit $a (2) add $0
        assert self.get_identifier(bib) == 'REAL12345'
        assert self.get_term(bib) == 'Middelalderen'

    def testDontUpdateIdentifierIfNotMatching(self):
        # If the $0 value doesn't match the one in the query, it should not be updated
        bib = self.make_bib('REAL00000')
        modifications = self.run_tasks(bib, src_identifier='REAL00001', dst_identifier='REAL12345')

        assert modifications == 0  # (1) edit $a (2) add $0
        assert self.get_identifier(bib) == 'REAL00000'
        assert self.get_term(bib) == 'Middelalder'

    def testUpdateTermEvenIfIdentifierNotDefinedInSourceQuery(self):
        # TODO: Clarify
        bib = self.make_bib('REAL00000')
        modifications = self.run_tasks(bib, src_identifier=ANY_VALUE, dst_identifier='REAL00000')

        assert modifications == 1  # (1) edit $a
        assert self.get_identifier(bib) == 'REAL00000'
        assert self.get_term(bib) == 'Middelalderen'


class TestSruSearch(unittest.TestCase):

    @responses.activate
    def testSimpleSearch(self):
        url = 'http://test/'

        body = get_sample('sru_sample_response_1.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')

        records = list(SruClient(url).search('alma.subjects=="test"'))

        assert len(responses.calls) == 1
        assert len(records) == 18

    @responses.activate
    def testIteration(self):
        url = 'http://test/'

        def request_callback(request):
            if request.url.find('startRecord=2') != -1:
                body = get_sample('sru_sample_response_3.xml')
            else:
                body = get_sample('sru_sample_response_2.xml')
            return (200, {}, body)

        responses.add_callback(responses.GET, url, callback=request_callback, content_type='application/xml')

        records = list(SruClient(url).search('alma.subjects=="test"'))

        assert len(responses.calls) == 2
        assert len(records) == 2

    @responses.activate
    def testErrorResponse(self):
        url = 'http://test/'

        body = get_sample('sru_error_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')

        with pytest.raises(SruErrorResponse):
            records = list(SruClient(url).search('alma.subjects=="test"'))

        assert len(responses.calls) == 1

    @responses.activate
    def testTooManyRecordsResponse(self):
        url = 'http://test/'

        body = get_sample('sru_toomanyrecords.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')

        with pytest.raises(TooManyResults):
            records = list(SruClient(url).search('alma.subjects=="Tyskland" AND alma.authority_vocabulary = "humord"'))

        assert len(responses.calls) == 1


class TestAlma(unittest.TestCase):

    @responses.activate
    def testGetRecord(self):
        id = '991416299674702204'
        alma = Alma('test', 'key')
        url = '{}/bibs/{}'.format(alma.base_url, id)
        body = get_sample('bib_991416299674702204.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')
        alma.get_record(id).marc_record

        assert len(responses.calls) == 1

    @responses.activate
    def testPutRecord(self):
        id = '991416299674702204'
        alma = Alma('test', 'key')
        url = '/bibs/{}'.format(id)
        body = get_sample('bib_991416299674702204.xml')
        bib = Bib(body)
        responses.add(responses.PUT, alma.base_url + url, body=body, content_type='application/xml')
        alma.put_record(bib)

        assert len(responses.calls) == 1
        assert responses.calls[0].request.body.read().decode('utf-8') == body


class TestAuthorizeTerm(unittest.TestCase):

    @staticmethod
    def init(results):
        url = 'http://data.ub.uio.no/skosmos/rest/v1/skosmos_vocab/search'
        responses.add(responses.GET, url, body=results, content_type='application/json')

    @responses.activate
    def testAuthorizeTermNoResults(self):
        self.init('')

        vocab = Vocabulary('skosmos_vocab',
                           'http://data.ub.uio.no/skosmos/rest/v1/skosmos_vocab/search?term={term}&tag={tag}')
        res = vocab.authorize_term('test', '650')

        assert res == {}
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeTerm(self):
        self.init('{"id": "REAL123"}')

        vocab = Vocabulary('skosmos_vocab',
                           'http://data.ub.uio.no/skosmos/rest/v1/skosmos_vocab/search?term={term}&tag={tag}')
        res = vocab.authorize_term('test', '650')

        assert res == {'id': 'REAL123'}
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeEmptyTerm(self):
        self.init('')

        vocab = Vocabulary('skosmos_vocab',
                           'http://data.ub.uio.no/skosmos/rest/v1/skosmos_vocab/search?term={test}&tag={tag}')
        res = vocab.authorize_term('', '650')

        assert res == {}
        assert len(responses.calls) == 0


class SruMock(Mock):

    def __init__(self, **kwargs):
        super(SruMock, self).__init__(**kwargs)


def patch_sru_search(xml_response_file):
    # Decorator

    @contextmanager
    def patch_fn():

        patcher = patch('almar.almar.SruClient.request')
        patcher.start()

        sru_mock = SruClient('http://example.com')
        sru_mock.request.return_value = get_sample(xml_response_file)
        yield sru_mock

        patcher.stop()

    def decorator_fn(func):
        @wraps(func)
        def wrapper_fn(*args, **kwargs):
            with patch_fn() as sru:
                args = tuple([args[0], sru] + list(args[1:]))
                func(*args, **kwargs)
        return wrapper_fn
    return decorator_fn


class TestJob(unittest.TestCase):

    def setUp(self):
        MockAlma = MagicMock(spec=Alma, spec_set=True)
        self.alma = MockAlma('eu', 'dummy')

    def runJob(self, sru_response, vocabulary, args):

        patched_sru = SruClient('http://example.com')
        patched_sru.request = MagicMock(name='request')
        patched_sru.request.return_value = get_sample(sru_response)

        conf = {
            'vocabularies': [{
                'marc_code': vocabulary,
                'skosmos_code': 'skosmos_vocab',
            }],
            'default_vocabulary': vocabulary,
        }
        self.job = Job(sru=patched_sru, ils=self.alma, **job_args(conf, parse_args(args)))
        # self.job.dry_run = True
        self.job.interactivity = INTERACTIVITY_NONE

        # Job(self.sru, self.alma, voc, tag, term, new_term, new_tag)
        return self.job.start()

    def tearDown(self):
        self.alma = None
        self.job = None

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    def testRenameFromSimpleToSimpleJob(self, authorize_term):
        authorize_term.return_value = {}
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['replace', 'Statistiske modeller', 'Test æøå'])

        assert len(results) == 14
        assert authorize_term.called

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    def testRenameFromSimpleToStringJob(self, authorize_term):
        authorize_term.return_value = {}
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['replace', 'Statistiske modeller', 'Test : æøå'])

        assert len(results) == 14
        assert authorize_term.called

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    def testRenameFromStringToSimpleJob(self, authorize_term):
        authorize_term.return_value = {}
        results = self.runJob('sru_sample_response_1.xml', 'tekord',
                              ['replace', 'Økologi : Statistiske modeller', 'Test'])

        assert len(results) == 1
        assert authorize_term.called

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    def testRemoveStringJob(self, authorize_term):
        authorize_term.return_value = {}
        results = self.runJob('sru_sample_response_1.xml', 'tekord',
                              ['remove', 'Økologi : Statistiske modeller'])

        assert len(results) == 1
        assert not authorize_term.called

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    def testMoveJob(self, authorize_term):
        authorize_term.return_value = {}
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['replace', 'Statistiske modeller', '655'])

        assert len(results) == 14
        assert authorize_term.called

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    def testSplitJob(self, authorize_term):
        authorize_term.return_value = {'id': 'REAL030697'}
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['replace', 'Statistiske modeller', 'Statistikk', 'Modeller'])

        assert len(results) == 14
        assert authorize_term.called

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    def testIdentifierShouldNotBeAddedForComponentMatches(self, authorize_term):

        def side_effect(*args):
            print(args)
            if args[1] == 'Geologi':
                return {}
            else:
                return {'id': 'identifier_13245'}

        authorize_term.side_effect = side_effect

        def get_record(record_id):
            bib = Bib({
                '990715687274702201': get_sample('bib_990715687274702201.xml'),
                '990100089184702201': get_sample('bib_990100089184702201.xml'),
            }[record_id])

            return bib

        self.alma.get_record.side_effect = get_record

        def put_record(record, **kwargs):
            if '990715687274702201' == record.id:
                assert 'identifier_13245' not in record.xml()
                return get_sample('bib_990715687274702201.xml',)
            if '990100089184702201' == record.id:
                assert 'identifier_13245' not in record.xml()
                return get_sample('bib_990100089184702201.xml',)

        self.alma.put_record.side_effect = put_record

        results = self.runJob('sru_sample_response_1.xml', 'tekord',
                              ['replace', 'Geologi', 'TestReplace'])

        assert len(results) == 2

        self.alma.get_record.assert_called()
        # self.alma.put.assert_called()

        # assert_has_calls([
        #     call(ANY, 'Geologi', '650'),
        #     call(ANY, 'TestReplace', '650'),
        # ])

        # bib = Bib(rec)

        # vocabularies = {'noubomn': Vocabulary('noubomn')}
        # src = Concept({'a': 'Middelalder', '2': 'noubomn'}, vocabularies)
        # dst = Concept({'a': 'Middelalderen', '2': 'noubomn', '0': 'REAL12345'}, vocabularies)

        # tasks = Job.generate_replace_tasks(src, dst)

        # for task in tasks:
        #     task.run(bib.marc_record)

        # f650 = bib.doc.findall('record/datafield[@tag="650"]')
        # assert len(f650) == 1
        # assert 'Middelalderen' == f650[0].findtext('subfield[@code="a"]')
        # assert 'Kjemi' == f650[0].findtext('subfield[@code="x"]')
        # assert f650[0].find('subfield[@code="0"]') is None


class TestAlmar(unittest.TestCase):

    @staticmethod
    def conf():
        return BytesIO(dedent('''
        vocabularies:
          - marc_code: noubomn
            skosmos_vocab: skosmos_vocab

        default_vocabulary: noubomn
        default_env: test_env

        env:
          - name: test_env
            api_key: secret1
            api_region: eu
            sru_url: https://sandbox-eu.alma.exlibrisgroup.com/view/sru/DUMMY_SITE

        logging:
          version: 1
        ''').encode('utf-8'))

    @classmethod
    def conf_obj(cls):
        return yaml.load(cls.conf())

    @staticmethod
    def sru_search_mock(*args, **kwargs):
        recs = get_sample('sru_sample_response_1.xml', True).findall('srw:records/srw:record/srw:recordData/record', NSMAP)
        for n, rec in enumerate(recs):
            yield rec

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    @patch('almar.almar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testMain(self, sru, MockAlma, mock_authorize_term):
        term = 'Statistiske modeller'
        new_term = 'Test æøå'
        alma = MockAlma.return_value
        mock_authorize_term.return_value = {'id': 'REAL030697'}
        run(self.conf_obj(), ['-e test_env', '-n', 'replace', term, new_term])

        sru.request.assert_called_once_with('alma.subjects = "%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'), 1)

        assert alma.get_record.call_count == 14

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    @patch('almar.almar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testMainNoHits(self, sru, MockAlma, mock_authorize_term):
        term = 'Something else'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'id': 'REAL030697'}
        alma = MockAlma.return_value
        run(self.conf_obj(), ['-e test_env', '-n', 'replace', term, new_term])
        sru.request.assert_called_once_with('alma.subjects = "%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'), 1)
        assert alma.get_record.call_count == 0

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    @patch('almar.almar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testRemoveTerm(self, sru, MockAlma, mock_authorize_term):
        term = 'Statistiske modeller'
        mock_authorize_term.return_value = {'id': 'REAL030697'}
        alma = MockAlma.return_value
        run(self.conf_obj(), ['-e test_env', '-n', 'remove', term])
        sru.request.assert_called_once_with('alma.subjects = "%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'), 1)
        assert alma.get_record.call_count == 14

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    @patch('almar.almar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testDiffs(self, sru, MockAlma, mock_authorize_term):
        term = 'Matematisk biologi'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'id': 'REAL030697'}
        alma = MockAlma.return_value

        doc = get_sample('bib_990705558424702201.xml')
        bib = Bib(doc)
        alma.get_record.return_value = bib

        run(self.conf_obj(), ['--diffs', '-e test_env', '-n', 'replace', term, new_term])
        sru.request.assert_called_once_with('alma.subjects = "%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'), 1)
        assert alma.get_record.call_count == 1
        assert alma.put_record.call_count == 1

    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    @patch('almar.almar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testListCommand(self, sru, MockAlma, mock_authorize_term):
        term = 'Matematisk biologi'
        mock_authorize_term.return_value = {'id': 'REAL030697'}
        alma = MockAlma.return_value

        doc = get_sample('bib_990705558424702201.xml')
        bib = Bib(doc)
        alma.get_record.return_value = bib

        run(self.conf_obj(), ['-e test_env', '-n', 'list', term])
        sru.request.assert_called_once_with(
            'alma.subjects = "%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'), 1)
        assert alma.get_record.call_count == 1
        assert alma.put_record.call_count == 0

    @responses.activate
    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    @patch.object(Alma, 'get_record', autospec=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testDryRun(self, sru, get_record, mock_authorize_term):
        term = 'Matematisk biologi'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'id': 'REAL030697'}

        doc = get_sample('bib_990705558424702201.xml')
        get_record.return_value = Bib(doc)

        run(self.conf_obj(), ['--dry_run', '-e test_env', '-n', 'replace', term, new_term])
        sru.request.assert_called_once_with('alma.subjects = "%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'), 1)
        assert get_record.call_count == 1
        assert len(responses.calls) == 0

    @responses.activate
    @patch.object(Alma, 'get_record', autospec=True)
    @patch.object(Vocabulary, 'authorize_term', autospec=True)
    @patch_sru_search('sru_response_dm.xml')
    def testCzRecord(self, sru, mock_authorize_term, get_record):
        term = 'Dynamisk meteorologi'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'id': 'REAL030697'}

        doc = get_sample('bib_linked_cz.xml')
        bib = Bib(doc)
        get_record.return_value = bib

        run(self.conf_obj(), ['-e test_env', '-n', 'replace', term, new_term])

        sru.request.assert_called_once_with('alma.subjects = "%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'), 1)

        assert bib.cz_link is not None
        assert get_record.call_count == 2  # It did match, but...
        assert len(responses.calls) == 0  # We can't update CZ records

    @patch('almar.almar.open', autospec=True)
    @patch('almar.almar.os.path.exists', autospec=True)
    def testConfigMissing(self, exists, mock_open):
        exists.return_value = True
        mock_open.side_effect = IOError('File not found')

        with pytest.raises(SystemExit):
            get_config()

        mock_open.assert_called_once_with('./almar.yml')

    def testNormalizeTerm(self):
        term1 = normalize_term('byer : økologi')
        term2 = normalize_term('administrativ historie')

        assert term1 == 'Byer : Økologi'
        assert term2 == 'Administrativ historie'


class TestArgumentParsing(unittest.TestCase):

    def test_missing_arguments(self):
        with pytest.raises(SystemExit):
            parse_args([], None)

    def test_defaults(self):
        args = parse_args(['replace', 'Sekvensering', 'Sekvenseringsmetoder'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert args.env == 'test_env'
        assert args.dry_run is False
        assert args.action == 'replace'
        assert args.term == 'Sekvensering'
        assert args.new_terms == ['Sekvenseringsmetoder']

        assert jargs['source_concept'].tag == '650'
        assert jargs['source_concept'].term == 'Sekvensering'

    def test_unicode_input(self):
        args = parse_args(['replace', 'Byer : Økologi', 'Byøkologi'], default_env='test_env')

        assert args.action == 'replace'
        assert args.term == 'Byer : Økologi'
        assert args.new_terms == ['Byøkologi']
        assert type(args.term) == text_type
        assert type(args.new_terms[0]) == text_type

    def test_tag_move(self):
        args = parse_args(['replace', '651 Sekvensering', '655 Sekvenseringsmetoder'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '651'
        assert jargs['source_concept'].sf == {'a': 'Sekvensering', '2': 'noubomn', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 1
        assert jargs['target_concepts'][0].tag == '655'
        assert jargs['target_concepts'][0].sf == {'a': 'Sekvenseringsmetoder', '2': 'noubomn'}

    def test_tag_move_abbr(self):
        args = parse_args(['replace', '650 100 tallet f.Kr.', '648'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '650'
        assert jargs['source_concept'].sf == {'a': '100 tallet f.Kr.', '2': 'noubomn', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 1
        assert jargs['target_concepts'][0].tag == '648'
        assert jargs['target_concepts'][0].sf == {'a': '100 tallet f.Kr.', '2': 'noubomn'}

    def test_simple_to_string(self):
        args = parse_args(['replace', 'Sekvenseringsmetoder', 'Sekvensering : Metoder'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '650'
        # Does not have to be ordered
        assert jargs['source_concept'].sf == dict((
            ('a', 'Sekvenseringsmetoder'),
            ('x', None),
            ('2', 'noubomn'),
            ('0', ANY_VALUE),
        ))

        assert len(jargs['target_concepts']) == 1
        assert jargs['target_concepts'][0].tag == '650'
        # Must be ordered
        assert jargs['target_concepts'][0].sf == OrderedDict((
            ('a', 'Sekvensering'),
            ('x', 'Metoder'),
            ('2', 'noubomn'),
        ))

    def test_string_to_simple(self):
        args = parse_args(['replace', 'Sekvensering : Metoder', 'Sekvenseringsmetoder'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '650'
        assert jargs['source_concept'].sf == {'a': 'Sekvensering', 'x': 'Metoder', '2': 'noubomn', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 1
        assert jargs['target_concepts'][0].tag == '650'
        assert jargs['target_concepts'][0].sf == {'a': 'Sekvenseringsmetoder', 'x': None, '2': 'noubomn'}

    def test_string_to_string(self):
        args = parse_args(['replace', 'Sekvensering : Metoder', 'Metoder : Sekvensiering'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '650'
        assert jargs['source_concept'].sf == {'a': 'Sekvensering', 'x': 'Metoder', '2': 'noubomn', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 1
        assert jargs['target_concepts'][0].tag == '650'
        assert jargs['target_concepts'][0].sf == {'a': 'Metoder', 'x': 'Sekvensiering', '2': 'noubomn'}

    def test_destination_tag_should_default_to_source_tag(self):
        args = parse_args(['replace', '651 Sekvensering', 'Sekvenseringsmetoder'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '651'
        assert jargs['source_concept'].sf == {'a_or_x': 'Sekvensering', '2': 'noubomn', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 1
        assert jargs['target_concepts'][0].tag == '651'
        assert jargs['target_concepts'][0].sf == {'a_or_x': 'Sekvenseringsmetoder', '2': 'noubomn'}

    def test_multiple_target_args(self):
        args = parse_args(['replace', '651 Sekvenseringsmetoder', 'Sekvensering', 'Metoder'], default_env='test_env')
        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '651'
        assert jargs['source_concept'].sf == {'a_or_x': 'Sekvenseringsmetoder', '2': 'noubomn', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 2

        assert jargs['target_concepts'][0].tag == '651'
        assert jargs['target_concepts'][0].sf == {'a_or_x': 'Sekvensering', '2': 'noubomn'}

        assert jargs['target_concepts'][1].tag == '651'
        assert jargs['target_concepts'][1].sf == {'a_or_x': 'Metoder', '2': 'noubomn'}

    def test_advanced_syntax1(self):
        args = parse_args(['replace',
                           '650 #7 $$a Osloavtalen $$2 humord',
                           '630 2# $$a Osloavtalen $$d 1993 $$0 90918232 $$2 bare'
                           ], default_env='test_env')

        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '650'
        assert jargs['source_concept'].sf == {'a': 'Osloavtalen', 'd': None, '2': 'humord', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 1

        assert jargs['target_concepts'][0].tag == '630'
        assert jargs['target_concepts'][0].sf == {'a': 'Osloavtalen', 'd': '1993', '0': '90918232', '2': 'bare'}

    def test_advanced_syntax2(self):
        args = parse_args(['replace',
                           '650 #7 $$a Habsburg $$2 humord',
                           '600 3# $$a Habsburg $$c slekten $$0 90200245 $$2 bare'
                           ], default_env='test_env')

        jargs = job_args({'vocabularies': [{'marc_code': 'noubomn'}], 'default_vocabulary': 'noubomn'}, args)

        assert jargs['source_concept'].tag == '650'
        assert jargs['source_concept'].sf == {'a': 'Habsburg', 'c': None, '2': 'humord', '0': ANY_VALUE}

        assert len(jargs['target_concepts']) == 1

        assert jargs['target_concepts'][0].tag == '600'
        assert jargs['target_concepts'][0].sf == {'a': 'Habsburg', 'c': 'slekten', '0': '90200245', '2': 'bare'}


if __name__ == '__main__':
    unittest.run()
