# encoding=utf-8
from __future__ import unicode_literals

import json
import os
import unittest
import pytest
import responses
from mock import Mock, MagicMock, patch, ANY
from io import BytesIO
from io import open
from six import text_type
from contextlib import contextmanager
from functools import wraps
from textwrap import dedent

from lokar.bib import Bib
from lokar.lokar import main, job_args, parse_args, Vocabulary, Mailer
from lokar.sru import SruClient, SruErrorResponse, TooManyResults, nsmap
from lokar.alma import Alma
from lokar.job import Job, Concept
from lokar.util import normalize_term, parse_xml
from lokar.skosmos import Skosmos
from lokar.marc import Record
from lokar.task import MoveTask, DeleteTask


def get_sample(filename, as_xml=False):
    with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data/%s' % filename), encoding='utf-8') as fp:
        body = fp.read()
    if as_xml:
        return parse_xml(body)
    return body


class TestRecord(unittest.TestCase):

    @staticmethod
    def getRecord():
        return Record(parse_xml('''
              <record>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="2">humord</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Atferd</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="x">Atferd</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Atferd</subfield>
                  <subfield code="x">Mennesker</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="x">Dagbøker</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="648" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="655" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="653" ind1=" " ind2=" ">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="a">Algoritmer</subfield>
                </datafield>
              </record>
        '''.encode('utf-8')))

    def testFind650a(self):
        """
        1st field should not match because of $2
        2nd field should match
        4th and 6th value should match because we didn't restrict to $x: None
        The rest should not match because of $a or tag != 650
        """
        record = self.getRecord()
        fields = list(record.fields('650', {'2': 'noubomn', 'a': 'Monstre'}))

        assert len(fields) == 3
        assert fields[0].node.findtext('subfield[@code="a"]') == 'Monstre'

    def testFind650x(self):
        """
        4th field should match because of $x
        The rest should not match because of $a or tag != 650
        """
        record = self.getRecord()

        fields = list(record.fields('650', {'2': 'noubomn', 'x': 'Atferd'}))

        assert len(fields) == 1
        assert fields[0].node.findtext('subfield[@code="a"]') == 'Monstre'
        assert fields[0].node.findtext('subfield[@code="x"]') == 'Atferd'

    def testMove(self):
        """
        Test that only the 3rd field is moved. Specifically, the 4th and 5th
        fields should not be moved!
        """
        record = self.getRecord()
        assert len(record.fields('655', {'2': 'noubomn'})) == 1

        task = MoveTask('650', 'noubomn', {'a': 'Atferd'}, '655')
        self.assertTrue(task.match(record))

        task.run(record)
        self.assertFalse(task.match(record))
        assert len(record.fields('655', {'2': 'noubomn'})) == 2

    def testReplace2to2(self):
        """Replace $a : $x with $a : $x"""
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('Monstre : Dagbøker', voc),
                                           Concept('Test to : Atlas', voc))

        assert len(tasks) == 1
        for task in tasks:
            self.assertTrue(task.match(record))
            task.run(record)
            self.assertFalse(task.match(record))
            assert text_type(task) == 'Replace $a Monstre $x Dagbøker with $a Test to $x Atlas in 650 $2 noubomn'

        assert len(record.fields('650', {'a': 'Monstre', 'x': 'Dagbøker', '2': 'noubomn'})) == 0
        assert len(record.fields('650', {'a': 'Test to', 'x': 'Atlas', '2': 'noubomn'})) == 1

    def testReplace1to2(self):
        """Replace $a with $a : $x"""
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('Monstre', voc),
                                           Concept('Monstre : Test', voc))

        assert len(tasks) == 1
        for task in tasks:
            self.assertTrue(task.match(record))
            task.run(record)
            self.assertFalse(task.match(record))
            assert text_type(task) == 'Replace $a Monstre with $a Monstre $x Test in 650 $2 noubomn'

        assert len(record.fields('650', {'a': 'Monstre', 'x': 'Test', '2': 'noubomn'})) == 1

    def testReplace2to1(self):
        """Replace $a : $x with $a"""
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('Monstre : Atferd', voc),
                                           Concept('Ost', voc))

        assert len(tasks) == 1
        for task in tasks:
            self.assertTrue(task.match(record))
            task.run(record)
            self.assertFalse(task.match(record))
            assert text_type(task) == 'Replace $a Monstre $x Atferd with $a Ost in 650 $2 noubomn'

        assert len(record.fields('650', {'a': 'Ost', '2': 'noubomn'})) == 1

    def testReplace1to1(self):
        """Replace $a with $a"""
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('Atferd', voc),
                                           Concept('Testerstatning', voc))

        assert len(tasks) == 2  # one for $a, one for $x
        modified = 0
        for task in tasks:
            self.assertTrue(task.match(record))
            modified += task.run(record)
            self.assertFalse(task.match(record))

        assert modified == 3
        assert len(record.fields('650', {'a': 'Testerstatning', '2': 'noubomn'})) == 2
        assert len(record.fields('650', {'a': 'Testerstatning', 'x': 'Mennesker', '2': 'noubomn'})) == 1
        assert len(record.fields('650', {'x': 'Testerstatning', '2': 'noubomn'})) == 1
        assert len(record.fields('650', {'a': 'Monstre', 'x': 'Testerstatning', '2': 'noubomn'})) == 1

    def testReplace651(self):
        """Replace 651 field"""
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('Monstre', voc, '648'),
                                           Concept('Testerstatning', voc, '648'))

        assert len(tasks) == 2  # one for $a, one for $x
        modified = 0
        for task in tasks:
            modified += task.run(record)

        assert modified == 1
        assert len(record.fields('648', {'a': 'Testerstatning', '2': 'noubomn'})) == 1

    def testRemove(self):
        """Remove subject"""
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        task = DeleteTask(Concept('atferd', voc, '650'))

        fc0 = len(record.el.findall('.//datafield[@tag="650"]'))
        modified = task.run(record)
        fc1 = len(record.el.findall('.//datafield[@tag="650"]'))

        assert modified == 1
        assert fc1 == fc0 - 1

    def testCaseSensitive(self):
        """Se2arch should in general be case sensitive ..."""
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('ATFerd', voc),
                                           Concept('Testerstatning', voc))

        assert len(tasks) == 2  # one for $a, one for $x
        for task in tasks:
            self.assertFalse(task.match(record))

    def testCaseInsensitiveFirstCharacter(self):
        """
        Search should in general be case sensitive ... except for the first character.
        The replacement term should not be normalized.
        """
        record = self.getRecord()
        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('atferd', voc),
                                           Concept('testerstatning', voc))

        assert len(tasks) == 2  # one for $a, one for $x
        modified = 0
        for task in tasks:
            self.assertTrue(task.match(record))
            modified += task.run(record)
            self.assertFalse(task.match(record))

        assert text_type(tasks[0]) == 'Replace $a atferd with $a testerstatning in 650 $2 noubomn'
        assert text_type(tasks[1]) == 'Replace $x atferd with $x testerstatning in 650 $2 noubomn'

        assert modified == 3
        f = record.el.xpath('.//datafield[@tag="650"]/subfield[@code="a"][text()="testerstatning"]')
        assert len(f) == 2

        f = record.el.xpath('.//datafield[@tag="650"]/subfield[@code="x"][text()="testerstatning"]')
        assert len(f) == 1

    def testDuplicatesAreRemoved(self):
        # If the new term already exists, don't duplicate it
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Mønstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)

        voc = Vocabulary('noubomn')
        tasks = Job.generate_replace_tasks(Concept('Monstre', voc),
                                           Concept('Mønstre', voc))

        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 2

        modified = 0
        for task in tasks:
            modified += task.run(bib.marc_record)

        assert modified == 1
        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 1

    def testDuplicatesAreRemovedUponMoveAndFirstCharacterIsCaseInsensitive(self):
        # If the new term already exists, don't duplicate it
        rec = """
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
        """
        bib = Bib(Mock(), rec)
        assert len(bib.doc.findall('record/datafield[@tag="648"]')) == 1
        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 2

        task = MoveTask('648', 'noubomn', {'a': 'Monstre'}, '650')
        task.run(bib.marc_record)

        assert len(bib.doc.findall('record/datafield[@tag="648"]')) == 0
        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 1

    def testAddIdentifier(self):
        rec = """
            <bib>
                <record>
                  <datafield tag="650" ind1=" " ind2="7">
                    <subfield code="a">Middelalder</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)

        voc = Vocabulary('noubomn')
        src = Concept('Middelalder', voc)
        dst = Concept('Middelalderen', voc)
        dst.sf['0'] = 'REAL12345'
        tasks = Job.generate_replace_tasks(src, dst)

        for task in tasks:
            task.run(bib.marc_record)

        f650 = bib.doc.findall('record/datafield[@tag="650"]')
        assert len(f650) == 1
        assert 'Middelalderen' == f650[0].findtext('subfield[@code="a"]')
        assert 'REAL12345' == f650[0].findtext('subfield[@code="0"]')

    def testModifyIdentifier(self):
        rec = """
            <bib>
                <record>
                  <datafield tag="650" ind1=" " ind2="7">
                    <subfield code="a">Middelalder</subfield>
                    <subfield code="2">noubomn</subfield>
                    <subfield code="0">REAL00000</subfield>
                  </datafield>
                  <datafield tag="650" ind1=" " ind2="7">
                    <subfield code="a">Middelalderen</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)

        voc = Vocabulary('noubomn')
        src = Concept('Middelalder', voc)
        dst = Concept('Yngre middelalder', voc)
        dst.sf['0'] = 'REAL12345'
        tasks = Job.generate_replace_tasks(src, dst)

        for task in tasks:
            task.run(bib.marc_record)

        f650 = bib.doc.findall('record/datafield[@tag="650"]')
        assert len(f650) == 2
        assert 'Yngre middelalder' == f650[0].findtext('subfield[@code="a"]')
        assert 'REAL12345' == f650[0].findtext('subfield[@code="0"]')


class TestBib(unittest.TestCase):

    def testSave(self):
        alma = Mock()
        alma.put.return_value = '<bib><mms_id>991416299674702204</mms_id><record></record></bib>'
        doc = get_sample('bib_response.xml')
        bib = Bib(alma, doc)
        task = MoveTask('650', 'noubomn', {'a': 'Kryptozoologi'}, '651')
        task.run(bib.marc_record)
        bib.save()

        alma.put.assert_called_once_with('/bibs/991416299674702204', data=ANY,
                                         headers={'Content-Type': 'application/xml'})


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
    def testBibs(self):
        mms_id = '991416299674702204'
        alma = Alma('test', 'key')
        url = '{}/bibs/{}'.format(alma.base_url, mms_id)
        body = get_sample('bib_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')
        alma.bibs(mms_id).marc_record

        assert len(responses.calls) == 1

    @responses.activate
    def testPut(self):
        mms_id = '991416299674702204'
        alma = Alma('test', 'key')
        url = '/bibs/{}'.format(mms_id)
        body = get_sample('bib_response.xml')
        responses.add(responses.PUT, alma.base_url + url, body=body, content_type='application/xml')
        alma.put(url, data=body, headers={'Content-Type': 'application/xml'})

        assert len(responses.calls) == 1
        assert responses.calls[0].request.body == body


class TestAuthorizeTerm(unittest.TestCase):

    @staticmethod
    def init(results):
        url = 'http://data.ub.uio.no/skosmos/rest/v1/skosmos_vocab/search'
        body = {'results': results}
        responses.add(responses.GET, url, body=json.dumps(body), content_type='application/json')

    @responses.activate
    def testAuthorizeTermNoResults(self):
        self.init([])

        skosmos = Skosmos('skosmos_vocab')
        res = skosmos.authorize_term('test', '650')

        assert res is None
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeTerm(self):
        self.init([{'localName': 'c123', 'type': 'http://data.ub.uio.no/onto#Topic'}])

        skosmos = Skosmos('skosmos_vocab')
        res = skosmos.authorize_term('test', '650')

        assert res['localName'] == 'c123'
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeEmptyTerm(self):
        url = 'http://data.ub.uio.no/skosmos/rest/v1/skosmos_vocab/search'
        body = {'results': []}
        responses.add(responses.GET, url, body=json.dumps(body), content_type='application/json')

        skosmos = Skosmos('skosmos_vocab')
        res = skosmos.authorize_term('', '650')

        assert res is None
        assert len(responses.calls) == 0


class SruMock(Mock):

    def __init__(self, **kwargs):
        super(SruMock, self).__init__(**kwargs)


def setup_sru_mock(xml_response_file, mock=None):
    mock = mock or Mock(spec=SruClient)
    recs = get_sample(xml_response_file, True).findall('srw:records/srw:record/srw:recordData/record', nsmap)
    recs = [Record(rec) for rec in recs]

    def search(arg):
        for rec in recs:
            yield rec

    mock = mock.return_value
    mock.num_records = len(recs)
    mock.search.side_effect = search
    return mock


def patch_sru_search(xml_response_file):
    # Decorator

    def setup_mock(mock_class):
        return setup_sru_mock(xml_response_file, mock_class)

    @contextmanager
    def patch_fn():
        patcher = patch('lokar.lokar.SruClient', autospec=True)
        mock_sru_class = patcher.start()
        mock_sru = setup_mock(mock_sru_class)
        yield mock_sru
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

    def runJob(self, sru_response, vocabulary, args):
        self.sru = setup_sru_mock(sru_response)
        MockAlma = MagicMock(spec=Alma, spec_set=True)
        MockMailer = MagicMock(spec=Mailer, spec_set=True)
        self.alma = MockAlma('eu', 'dummy')
        mailer = MockMailer({})
        conf = {
            'vocabulary': {
                'marc_code': vocabulary,
                'skosmos_code': 'skosmos_vocab',
            }
        }
        self.job = Job(sru=self.sru, alma=self.alma, mailer=mailer, **job_args(conf, parse_args(args)))
        self.job.dry_run = True
        self.job.interactive = False

        # Job(self.sru, self.alma, voc, mailer, tag, term, new_term, new_tag)
        return self.job.start()

    def tearDown(self):
        self.alma = None
        self.sru = None
        self.job = None

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRenameFromSimpleToSimpleJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['rename', 'Statistiske modeller', 'Test æøå'])

        assert len(results) == 14
        assert authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRenameFromSimpleToStringJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['rename', 'Statistiske modeller', 'Test : æøå'])

        assert len(results) == 14
        assert authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRenameFromStringToSimpleJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'tekord',
                              ['rename', 'Økologi : Statistiske modeller', 'Test'])

        assert len(results) == 1
        assert authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRemoveStringJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'tekord',
                              ['delete', 'Økologi : Statistiske modeller'])

        assert len(results) == 1
        assert not authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testMoveJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['rename', 'Statistiske modeller', '655'])

        assert len(results) == 14
        assert authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testSplitJob(self, authorize_term):
        authorize_term.return_value = {'localname': 'c030697'}
        results = self.runJob('sru_sample_response_1.xml', 'noubomn',
                              ['rename', 'Statistiske modeller', 'Statistikk', 'Modeller'])

        assert len(results) == 14
        assert authorize_term.called


class TestLokar(unittest.TestCase):

    @staticmethod
    def conf():
        return BytesIO(dedent('''
        vocabulary:
          marc_code: noubomn
          skosmos_vocab: skosmos_vocab

        mail:
          domain: example.com
          api_key: key
          sender: sender@example.com
          recipient: recipient@example.com

        default_env: test_env

        env:
          test_env:
            api_key: secret1
            api_region: eu
            sru_url: https://sandbox-eu.alma.exlibrisgroup.com/view/sru/DUMMY_SITE
        ''').encode('utf-8'))

    @staticmethod
    def sru_search_mock(*args, **kwargs):
        recs = get_sample('sru_sample_response_1.xml', True).findall('srw:records/srw:record/srw:recordData/record', nsmap)
        for n, rec in enumerate(recs):
            yield rec

    @patch('lokar.lokar.Mailer', autospec=True)
    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    @patch('lokar.lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testMain(self, sru, MockAlma, mock_authorize_term, Mailer):
        term = 'Statistiske modeller'
        new_term = 'Test æøå'
        alma = MockAlma.return_value
        mock_authorize_term.return_value = {'localname': 'c030697'}
        main(self.conf(), ['-e test_env', '-n', 'rename', term, new_term])

        sru.search.assert_called_once_with('alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'))

        assert alma.bibs.call_count == 14

    @patch('lokar.lokar.Mailer', autospec=True)
    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    @patch('lokar.lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testMainNoHits(self, sru, MockAlma, mock_authorize_term, Mailer):
        term = 'Something else'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'localname': 'c030697'}
        alma = MockAlma.return_value
        main(self.conf(), ['-e test_env', '-n', 'rename', term, new_term])
        sru.search.assert_called_once_with('alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'))
        assert alma.bibs.call_count == 0

    @patch('lokar.lokar.Mailer', autospec=True)
    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    @patch('lokar.lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testRemoveTerm(self, sru, MockAlma, mock_authorize_term, mock_Mailer):
        term = 'Statistiske modeller'
        mock_authorize_term.return_value = {'localname': 'c030697'}
        alma = MockAlma.return_value
        main(self.conf(), ['-e test_env', '-n', 'delete', term])
        sru.search.assert_called_once_with('alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'))
        assert alma.bibs.call_count == 14

    @patch('lokar.lokar.Mailer', autospec=True)
    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    @patch('lokar.lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testDiffs(self, sru, MockAlma, mock_authorize_term, Mailer):
        term = 'Matematisk biologi'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'localname': 'c030697'}
        alma = MockAlma.return_value

        doc = get_sample('bib_response2.xml')
        bib = Bib(alma, doc)
        alma.bibs.return_value = bib

        main(self.conf(), ['--diffs', '-e test_env', '-n', 'rename', term, new_term])
        sru.search.assert_called_once_with('alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'))
        assert alma.bibs.call_count == 1
        assert alma.put.call_count == 1

    @patch('lokar.lokar.Mailer', autospec=True)
    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    @patch('lokar.lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testDryRun(self, sru, MockAlma, mock_authorize_term, Mailer):
        term = 'Matematisk biologi'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'localname': 'c030697'}
        alma = MockAlma.return_value

        doc = get_sample('bib_response2.xml')
        bib = Bib(alma, doc)
        alma.bibs.return_value = bib

        main(self.conf(), ['--dry_run', '-e test_env', '-n', 'rename', term, new_term])
        sru.search.assert_called_once_with('alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'))
        assert alma.bibs.call_count == 1
        assert alma.put.call_count == 0

    @patch('lokar.lokar.Mailer', autospec=True)
    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    @patch('lokar.lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_response_dm.xml')
    def testCzRecord(self, sru, MockAlma, mock_authorize_term, Mailer):
        term = 'Dynamisk meteorologi'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'localname': 'c030697'}
        alma = MockAlma.return_value

        doc = get_sample('bib_linked_cz.xml')
        bib = Bib(alma, doc)

        alma.bibs.return_value = bib

        main(self.conf(), ['-e test_env', '-n', 'rename', term, new_term])
        sru.search.assert_called_once_with('alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (term, 'noubomn'))

        assert bib.cz_link is not None
        assert alma.bibs.call_count == 2  # It did match, but...
        assert alma.put.call_count == 0  # We're not allowed to update CZ records

    @patch('lokar.lokar.open', autospec=True)
    def testConfigMissing(self, mock_open):
        mock_open.side_effect = IOError('File not found')
        main(args=['rename', 'old', 'new'])
        mock_open.assert_called_once_with('lokar.yml')

    def testNormalizeTerm(self):
        term1 = normalize_term('byer : økologi')
        term2 = normalize_term('administrativ historie')

        assert term1 == 'Byer : Økologi'
        assert term2 == 'Administrativ historie'


class TestParseArgs(unittest.TestCase):

    def test_missing_arguments(self):
        with pytest.raises(SystemExit):
            parse_args([], {})

    def test_defaults(self):
        args = parse_args(['rename', 'Sekvensering', 'Sekvenseringsmetoder'], default_env='test_env')
        jargs = job_args({'vocabulary': {'marc_code': 'noubomn'}}, args)

        assert args.env == 'test_env'
        assert args.dry_run is False
        assert args.action == 'rename'
        assert args.term == 'Sekvensering'
        assert args.new_term == 'Sekvenseringsmetoder'

        assert jargs['source_concept'].tag == '650'
        assert jargs['source_concept'].term == 'Sekvensering'

    def test_unicode_input(self):
        args = parse_args(['rename', 'Byer : Økologi', 'Byøkologi'], default_env='test_env')

        assert args.action == 'rename'
        assert args.term == 'Byer : Økologi'
        assert args.new_term == 'Byøkologi'
        assert type(args.term) == text_type
        assert type(args.new_term) == text_type

    def test_concept_parsing(self):
        args = parse_args(['rename', '651 Sekvensering', '655 Sekvenseringsmetoder'], default_env='test_env')
        jargs = job_args({'vocabulary': {'marc_code': 'noubomn'}}, args)

        assert jargs['source_concept'].tag == '651'
        assert jargs['source_concept'].term == 'Sekvensering'

        assert jargs['target_concept'].tag == '655'
        assert jargs['target_concept'].term == 'Sekvenseringsmetoder'


if __name__ == '__main__':
    unittest.main()
