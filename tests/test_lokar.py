# encoding=utf-8
from __future__ import unicode_literals

import json
import yaml
import os
import unittest
import pytest
import responses
from mock import Mock, MagicMock, patch
from mock import ANY
from io import BytesIO
from io import open
from six import text_type, binary_type
from contextlib import contextmanager
from functools import wraps
from textwrap import dedent

from lokar.lokar import main, parse_args, Vocabulary, Mailer
from lokar.sru import SruClient, SruErrorResponse, nsmap
from lokar.alma import Alma
from lokar.bib import Bib
from lokar.job import Job
from lokar.util import normalize_term, parse_xml
from lokar.skosmos import Skosmos
from lokar.marc import Record, Subjects


def get_sample(filename, as_xml=False):
    with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data/%s' % filename), encoding='utf-8') as fp:
        body = fp.read()
    if as_xml:
        return parse_xml(body)
    return body


class TestSubjects(unittest.TestCase):

    def getRecord(self):
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
        subjects = Subjects(record)
        fields = list(subjects.find(vocabulary='noubomn', term='Monstre'))

        assert len(fields) == 3
        assert fields[0].node.findtext('subfield[@code="a"]') == 'Monstre'

    def testFind650x(self):
        """
        3rd and 5th field should match because of $a
        4th field should match because of $x
        The rest should not match because of $a or tag != 650
        """
        record = self.getRecord()

        subjects = Subjects(record)
        fields = list(subjects.find(vocabulary='noubomn', term='Atferd'))

        assert len(fields) == 3
        assert fields[2].node.findtext('subfield[@code="a"]') == 'Monstre'
        assert fields[2].node.findtext('subfield[@code="x"]') == 'Atferd'

    def testMove(self):
        """
        Test that only the 3rd field is moved. Specifically, the 4th and 5th
        fields should not be moved!
        """
        record = self.getRecord()

        subjects = Subjects(record)
        assert len(list(subjects.find(vocabulary='noubomn', tags='655'))) == 1

        subjects.move('noubomn', 'Atferd', '650', '655')
        assert len(list(subjects.find(vocabulary='noubomn', tags='655'))) == 2

    def testRenameToString(self):
        record = self.getRecord()

        subjects = Subjects(record)
        subjects.rename('noubomn', 'Monstre', 'Monstre : Test')
        assert len(list(subjects.find(vocabulary='noubomn', term='Monstre : Test'))) == 1

    def testRenameFromString(self):
        record = self.getRecord()

        subjects = Subjects(record)
        subjects.rename('noubomn', 'Monstre : Atferd', 'Ost')
        assert len(list(subjects.find(vocabulary='noubomn', term='Ost'))) == 1


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


class TestAlma(unittest.TestCase):

    @responses.activate
    def testBibs(self):
        mms_id = '991416299674702204'
        alma = Alma('test', 'key')
        url = '{}/bibs/{}'.format(alma.base_url, mms_id)
        body = get_sample('bib_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')
        Subjects(alma.bibs(mms_id).marc_record).rename('humord', 'abc', 'def', tags=['650'])

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


class TestBib(unittest.TestCase):

    def testModify650a(self):
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).rename('noubomn', 'Monstre', 'Mønstre', tags=['650'])

        assert 'Mønstre' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'Atferd' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')  # $x should not change!

    def testModify650x(self):
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>

        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).rename('noubomn', 'Atferd', 'Dagbøker', tags=['650'])

        assert 'Monstre' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')  # $a should not change!
        assert 'Dagbøker' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testModify650ax(self):
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>

        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).rename('noubomn', 'Monstre : Atferd', 'Mønstre : Dagbøker', tags=['650'])

        assert 'Mønstre' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'Dagbøker' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testModify650_ax_to_a(self):
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>

        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).rename('noubomn', 'Monstre : Atferd', 'Monsteratferd', tags=['650'])

        assert 'Monsteratferd' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert bib.doc.find('record/datafield[@tag="650"]/subfield[@code="x"]') is None

    def testModify651(self):
        rec = """
            <bib>
                <record>
                  <datafield tag="650" ind1=" " ind2="7">
                    <subfield code="a">Oslo</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield tag="651" ind1=" " ind2="7">
                    <subfield code="a">Oslo</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).rename('noubomn', 'Oslo', 'Bergen', tags=['651'])

        assert 'Bergen' == bib.doc.findtext('record/datafield[@tag="651"]/subfield[@code="a"]')
        assert 'Oslo' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')   # 650 should not change!

    def testModify648(self):
        rec = """
            <bib>
                <record>
                  <datafield tag="648" ind1=" " ind2="7">
                    <subfield code="a">Middelalder</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield tag="650" ind1=" " ind2="7">
                    <subfield code="a">Middelalder</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).rename('noubomn', 'Middelalder', 'Middelalderen', tags=['648', '650'])

        assert 'Middelalderen' == bib.doc.findtext('record/datafield[@tag="648"]/subfield[@code="a"]')
        assert 'Middelalderen' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')

    def testDontCreateDuplicates(self):
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
        Subjects(bib.marc_record).rename('noubomn', 'Monstre', 'Mønstre', tags=['650'])

        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 1

    def testRemoveTerm(self):
        """
        Removing a term should also remove occurances where the term is a string component
        """
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).remove('noubomn', 'Monstre', tags=['650'])
        fields = bib.doc.findall('record/datafield[@tag="650"]')

        assert len(fields) == 1
        assert 'Monstre' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'atferd' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testRemoveTerm2(self):
        """
        Removing a term should also remove occurances where the term is a string component
        """
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).remove('noubomn', 'Atferd', tags=['650'])
        fields = bib.doc.findall('record/datafield[@tag="650"]')

        assert len(fields) == 2
        # assert 'Monstre' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        # assert 'atferd' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testRemoveSubjectString(self):
        rec = """
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).remove('noubomn', 'Monstre : Atferd', tags=['650'])
        fields = bib.doc.findall('record/datafield[@tag="650"]')

        assert len(fields) == 1
        assert 'Monstre' == bib.doc.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert bib.doc.find('record/datafield[@tag="650"]/subfield[@code="x"]') is None

    def testRemoveGeoTerm(self):
        rec = """
            <bib>
                <record>
                  <datafield tag="650" ind1=" " ind2="7">
                    <subfield code="a">Oslo</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                  <datafield tag="651" ind1=" " ind2="7">
                    <subfield code="a">Oslo</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """
        bib = Bib(Mock(), rec)
        Subjects(bib.marc_record).remove('noubomn', 'Oslo', tags=['651'])
        f650 = bib.doc.findall('record/datafield[@tag="650"]')
        f651 = bib.doc.findall('record/datafield[@tag="651"]')

        assert len(f650) == 1
        assert len(f651) == 0

    def testSave(self):
        alma = Mock()
        alma.put.return_value = '<bib><mms_id>991416299674702204</mms_id><record></record></bib>'
        doc = get_sample('bib_response.xml')
        bib = Bib(alma, doc)
        Subjects(bib.marc_record).rename('noubomn', 'Kryptozoologi', 'KryptoÆØÅ', tags=['650'])
        bib.save()

        alma.put.assert_called_once_with('/bibs/991416299674702204', data=ANY, headers={'Content-Type': 'application/xml'})

    def testRemoveDuplicates(self):
        rec = '''
             <bib> <record>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="x">Atferd</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="x">Atferd</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
              </record></bib>
        '''

        bib = Bib(Mock(), rec)

        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 2

        sub = Subjects(bib.marc_record)
        sub.remove_duplicates('noubomn', 'Monstre')

        assert len(bib.doc.findall('record/datafield[@tag="650"]')) == 1


class TestAuthorizeTerm(unittest.TestCase):

    @staticmethod
    def init(results):
        url = 'http://data.ub.uio.no/skosmos/rest/v1/realfagstermer/search'
        body = {'results': results}
        responses.add(responses.GET, url, body=json.dumps(body), content_type='application/json')

    @responses.activate
    def testAuthorizeTermNoResults(self):
        self.init([])

        skosmos = Skosmos('realfagstermer')
        res = skosmos.authorize_term('test', 'some type')

        assert res is None
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeTerm(self):
        self.init([{'localName': 'c123', 'type': 'some type'}])

        skosmos = Skosmos('realfagstermer')
        res = skosmos.authorize_term('test', 'some type')

        assert res['localName'] == 'c123'
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeEmptyTerm(self):
        url = 'http://data.ub.uio.no/skosmos/rest/v1/realfagstermer/search'
        body = {'results': []}
        responses.add(responses.GET, url, body=json.dumps(body), content_type='application/json')

        skosmos = Skosmos('realfagstermer')
        res = skosmos.authorize_term('', 'some type')

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

    def runJob(self, sru_response, vocabulary, tag, term, new_term='', new_tag=None):
        self.sru = setup_sru_mock(sru_response)
        MockAlma = MagicMock(spec=Alma, spec_set=True)
        MockMailer = MagicMock(spec=Mailer, spec_set=True)
        self.alma = MockAlma('eu', 'dummy')
        mailer = MockMailer({})
        voc = Vocabulary(vocabulary, 'realfagstermer')
        self.job = Job(self.sru, self.alma, voc, mailer, tag, term, new_term, new_tag)
        return self.job.start(False, True)

    def tearDown(self):
        self.alma = None
        self.sru = None
        self.job = None

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRenameFromSimpleToSimpleJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'noubomn', '650', 'Statistiske modeller', 'Test æøå')

        assert len(results) == 14
        assert authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRenameFromSimpleToStringJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'noubomn', '650', 'Statistiske modeller', 'Test : æøå')

        assert len(results) == 14
        assert authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRenameFromStringToSimpleJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'Tekord', '650', 'Økologi : Statistiske modeller', 'Test')

        assert len(results) == 1
        assert authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testRemoveStringJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'Tekord', '650', 'Økologi : Statistiske modeller', '')

        assert len(results) == 1
        assert not authorize_term.called

    @patch('lokar.job.Skosmos.authorize_term', autospec=True)
    def testMoveJob(self, authorize_term):
        results = self.runJob('sru_sample_response_1.xml', 'noubomn', '650', 'Statistiske modeller', new_tag='655')

        assert len(results) == 14
        assert authorize_term.called


class TestLokar(unittest.TestCase):

    @staticmethod
    def conf():
        return BytesIO(dedent('''
        vocabulary:
          marc_code: noubomn
          skosmos_vocab: realfagstermer

        mail:
          domain: example.com
          api_key: key
          sender: sender@example.com
          recipient: recipient@example.com

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
        main(self.conf(), ['-e test_env', '-n', 'move', term, new_term])

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
        main(self.conf(), ['-e test_env', '-n', 'move', term, new_term])
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

    @patch('lokar.lokar.open', autospec=True)
    def testConfigMissing(self, mock_open):
        mock_open.side_effect = IOError('File not found')
        main(args=['move', 'old', 'new'])
        mock_open.assert_called_once_with('lokar.yml')

    def testNormalizeTerm(self):
        term1 = normalize_term('byer : økologi')
        term2 = normalize_term('administrativ historie')

        assert term1 == 'Byer : Økologi'
        assert term2 == 'Administrativ historie'


class TestParseArgs(unittest.TestCase):

    def test_missing_arguments(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_defaults(self):
        parser = parse_args(['move', 'Sekvensering', 'Sekvenseringsmetoder'])

        assert parser.dry_run is False
        assert parser.action == 'move'
        assert parser.tag == '650'
        assert parser.term == 'Sekvensering'
        assert parser.new_term == 'Sekvenseringsmetoder'

    def test_unicode_input(self):
        parser = parse_args(['move', 'Byer : Økologi', 'Byøkologi'])

        assert parser.action == 'move'
        assert parser.term == 'Byer : Økologi'
        assert parser.new_term == 'Byøkologi'
        assert type(parser.term) == text_type
        assert type(parser.new_term) == text_type

if __name__ == '__main__':
    unittest.main()
