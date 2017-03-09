# encoding=utf-8
from __future__ import unicode_literals

import json
import os
import unittest
import pytest
import responses
from mock import Mock, patch
from mock import ANY
from io import StringIO
from io import open
from six import text_type, binary_type
from contextlib import contextmanager
from functools import wraps

from lokar import SruClient, nsmap, SruErrorResponse, Alma, Bib, read_config, main, authorize_term, \
    parse_args, normalize_term, MarcRecord, parse_xml
from textwrap import dedent


def get_sample(filename, as_xml=False):
    with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data/%s' % filename), encoding='utf-8') as fp:
        body = fp.read()
    if as_xml:
        return parse_xml(body)
    return body


class TestMarcRecord(unittest.TestCase):

    def test650a(self):
        record = MarcRecord(parse_xml('''
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
                  <subfield code="a">Mønstre</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="653" ind1=" " ind2=" ">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="a">Algoritmer</subfield>
                </datafield>
              </record>
        '''.encode('utf-8')))

        fields = record.subjects(vocabulary='noubomn', term='Monstre', tags=['650'])

        assert len(fields) == 1
        assert fields[0].findtext('subfield[@code="a"]') == 'Monstre'

    def test650x(self):
        record = MarcRecord(parse_xml('''
              <record>
                <datafield tag="650" ind1=" " ind2="7">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="2">humord</subfield>
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
                  <subfield code="a">Monstre</subfield>
                  <subfield code="x">Dagbøker</subfield>
                  <subfield code="2">noubomn</subfield>
                </datafield>
                <datafield tag="653" ind1=" " ind2=" ">
                  <subfield code="a">Monstre</subfield>
                  <subfield code="a">Algoritmer</subfield>
                </datafield>
              </record>
        '''.encode('utf-8')))

        fields = record.subjects(vocabulary='noubomn', term='Atferd', tags=['650'])

        assert len(fields) == 2
        assert fields[1].findtext('subfield[@code="a"]') == 'Monstre'
        assert fields[1].findtext('subfield[@code="x"]') == 'Atferd'


class TestSruSearch(unittest.TestCase):

    @responses.activate
    def testSimpleSearch(self):
        url = 'http://test/'

        body = get_sample('sru_sample_response_1.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')

        records = list(SruClient(url).search('alma.subjects="test"'))

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

        records = list(SruClient(url).search('alma.subjects="test"'))

        assert len(responses.calls) == 2
        assert len(records) == 2

    @responses.activate
    def testErrorResponse(self):
        url = 'http://test/'

        body = get_sample('sru_error_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')

        with pytest.raises(SruErrorResponse):
            records = list(SruClient(url).search('alma.subjects="test"'))

        assert len(responses.calls) == 1


class TestAlma(unittest.TestCase):

    @responses.activate
    def testBibs(self):
        mms_id = '991416299674702204'
        alma = Alma('test', 'key')
        url = '{}/bibs/{}'.format(alma.base_url, mms_id)
        body = get_sample('bib_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')
        alma.bibs(mms_id).marc_record.edit_subject('humord', 'abc', 'def', tags=['650'])

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
        rec = parse_xml("""
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>
        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.edit_subject('noubomn', 'Monstre', 'Mønstre', tags=['650'])

        assert 'Mønstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'Atferd' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')  # $x should not change!

    def testModify650x(self):
        rec = parse_xml("""
                        <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>

        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.edit_subject('noubomn', 'Atferd', 'Dagbøker', tags=['650'])

        assert 'Monstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')  # $a should not change!
        assert 'Dagbøker' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testModify650ax(self):
        rec = parse_xml("""
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>

        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.edit_subject('noubomn', 'Monstre : Atferd', 'Mønstre : Dagbøker', tags=['650'])

        assert 'Mønstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'Dagbøker' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testModify650_ax_to_a(self):
        rec = parse_xml("""
            <bib>
                <record>
                  <datafield ind1=" " ind2="7" tag="650">
                    <subfield code="a">Monstre</subfield>
                    <subfield code="x">Atferd</subfield>
                    <subfield code="2">noubomn</subfield>
                  </datafield>
                </record>
            </bib>

        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.edit_subject('noubomn', 'Monstre : Atferd', 'Monsteratferd', tags=['650'])

        assert 'Monsteratferd' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert rec.find('record/datafield[@tag="650"]/subfield[@code="x"]') is None

    def testModify651(self):
        rec = parse_xml("""
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
        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.edit_subject('noubomn', 'Oslo', 'Bergen', tags=['651'])

        assert 'Bergen' == rec.findtext('record/datafield[@tag="651"]/subfield[@code="a"]')
        assert 'Oslo' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')   # 650 should not change!

    def testModify648(self):
        rec = parse_xml("""
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
        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.edit_subject('noubomn', 'Middelalder', 'Middelalderen', tags=['648', '650'])

        assert 'Middelalderen' == rec.findtext('record/datafield[@tag="648"]/subfield[@code="a"]')
        assert 'Middelalderen' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')

    def testDontCreateDuplicates(self):
        # If the new term already exists, don't duplicate it
        rec = parse_xml("""
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
        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.edit_subject('noubomn', 'Monstre', 'Mønstre', tags=['650'])

        assert len(rec.findall('record/datafield[@tag="650"]')) == 1

    def testRemoveTerm(self):
        rec = parse_xml("""
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
        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.remove_subject('noubomn', 'Monstre', tags=['650'])
        fields = rec.findall('record/datafield[@tag="650"]')

        assert len(fields) == 1
        assert 'Monstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'atferd' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testRemoveSubjectString(self):
        rec = parse_xml("""
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
        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.remove_subject('noubomn', 'Monstre : Atferd', tags=['650'])
        fields = rec.findall('record/datafield[@tag="650"]')

        assert len(fields) == 1
        assert 'Monstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert rec.find('record/datafield[@tag="650"]/subfield[@code="x"]') is None

    def testRemoveGeoTerm(self):
        rec = parse_xml("""
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
        """)
        bib = Bib(Mock(), rec)
        bib.marc_record.remove_subject('noubomn', 'Oslo', tags=['651'])
        f650 = rec.findall('record/datafield[@tag="650"]')
        f651 = rec.findall('record/datafield[@tag="651"]')

        assert len(f650) == 1
        assert len(f651) == 0

    def testSave(self):
        alma = Mock()
        alma.put.return_value = '<bib><mms_id>991416299674702204</mms_id><record></record></bib>'
        doc = get_sample('bib_response.xml', True)
        bib = Bib(alma, doc)
        bib.marc_record.edit_subject('noubomn', 'Kryptozoologi', 'KryptoÆØÅ', tags=['650'])
        bib.save()

        alma.put.assert_called_once_with('/bibs/991416299674702204', data=ANY, headers={'Content-Type': 'application/xml'})

    def testDups(self):
        marc_record = parse_xml('''
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
        '''.encode('utf-8'))

        bib = Bib(Mock(), marc_record)

        assert len(marc_record.findall('record/datafield[@tag="650"]')) == 2

        bib.marc_record.remove_duplicate_fields('noubomn', 'Monstre', tags=['650'])

        assert len(marc_record.findall('record/datafield[@tag="650"]')) == 1


class TestAuthorizeTerm(unittest.TestCase):

    @staticmethod
    def init(results):
        url = 'http://data.ub.uio.no/skosmos/rest/v1/realfagstermer/search'
        body = {'results': results}
        responses.add(responses.GET, url, body=json.dumps(body), content_type='application/json')

    @responses.activate
    def testAuthorizeTermNoResults(self):
        self.init([])

        res = authorize_term('test', 'some type', 'realfagstermer')

        assert res is None
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeTerm(self):
        self.init([{'localName': 'c123', 'type': 'some type'}])

        res = authorize_term('test', 'some type', 'realfagstermer')

        assert res['localName'] == 'c123'
        assert len(responses.calls) == 1

    @responses.activate
    def testAuthorizeEmptyTerm(self):
        url = 'http://data.ub.uio.no/skosmos/rest/v1/realfagstermer/search'
        body = {'results': []}
        responses.add(responses.GET, url, body=json.dumps(body), content_type='application/json')

        res = authorize_term('', 'some type', 'realfagstermer')

        assert res is None
        assert len(responses.calls) == 0


class SruMock(Mock):

    def __init__(self, **kwargs):
        super(SruMock, self).__init__(**kwargs)


def patch_sru_search(xml_response_file):
    # Decorator

    def setup_mock(mock_class):
        recs = get_sample(xml_response_file, True).findall('srw:records/srw:record/srw:recordData/record', nsmap)
        recs = [MarcRecord(rec) for rec in recs]

        def search(arg):
            for rec in recs:
                yield rec

        mock = mock_class.return_value
        mock.num_records = len(recs)
        mock.search.side_effect = search
        return mock

    @contextmanager
    def patch_fn():
        patcher = patch('lokar.SruClient', autospec=True)
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


class TestLokar(unittest.TestCase):

    @staticmethod
    def conf():
        return StringIO(dedent('''
        [general]
        vocabulary=noubomn
        user=someuser
        skosmos_vocab=realfagstermer

        [mailgun]
        domain=example.com
        api_key=key
        sender=sender@example.com
        recipient=recipient@example.com

        [test_env]
        api_key=secret1
        api_region=eu
        sru_url=https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK
        '''))

    def testConfig(self):
        config = read_config(self.conf(), 'test_env')

        assert config['api_key'] == 'secret1'
        assert config['vocabulary'] == 'noubomn'

    @staticmethod
    def sru_search_mock(*args, **kwargs):
        recs = get_sample('sru_sample_response_1.xml', True).findall('srw:records/srw:record/srw:recordData/record', nsmap)
        for n, rec in enumerate(recs):
            yield rec

    @patch('lokar.email', autospec=True)
    @patch('lokar.authorize_term', autospec=True)
    @patch('lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testMain(self, sru, MockAlma, mock_authorize_term, email):
        print(type(sru))
        print(type(MockAlma))
        old_term = 'Statistiske modeller'
        new_term = 'Test æøå'
        alma = MockAlma.return_value
        mock_authorize_term.return_value = {'localname': 'c030697'}
        valid_records = main(self.conf(), [old_term, new_term, '-e test_env'])

        assert len(valid_records) == 14
        sru.search.assert_called_once_with('alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (old_term, 'noubomn'))

        assert alma.bibs.call_count == 14

    @patch('lokar.email', autospec=True)
    @patch('lokar.authorize_term', autospec=True)
    @patch('lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testMainNoHits(self, sru, MockAlma, mock_authorize_term, email):
        old_term = 'Something else'
        new_term = 'Test æøå'
        mock_authorize_term.return_value = {'localname': 'c030697'}
        alma = MockAlma.return_value
        valid_records = main(self.conf(), [old_term, new_term, '-e test_env'])
        assert valid_records is None
        sru.search.assert_called_once_with('alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (old_term, 'noubomn'))
        assert alma.bibs.call_count == 0

    @patch('lokar.email', autospec=True)
    @patch('lokar.authorize_term', autospec=True)
    @patch('lokar.Alma', autospec=True, spec_set=True)
    @patch_sru_search('sru_sample_response_1.xml')
    def testRemoveTerm(self, sru, MockAlma, mock_authorize_term, mock_email):
        old_term = 'Statistiske modeller'
        mock_authorize_term.return_value = {'localname': 'c030697'}
        alma = MockAlma.return_value
        valid_records = main(self.conf(), [old_term, '', '-e test_env'])
        assert len(valid_records) == 14
        sru.search.assert_called_once_with('alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (old_term, 'noubomn'))
        assert alma.bibs.call_count == 14

    @patch('lokar.open', autospec=True)
    def testConfigMissing(self, mock_open):
        mock_open.side_effect = IOError('File not found')
        main(args=['old', 'new'])
        mock_open.assert_called_once_with('lokar.cfg')

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
        parser = parse_args(['Sekvensering', 'Sekvenseringsmetoder'])

        assert parser.dry_run is False
        assert parser.tag == '650'
        assert parser.old_term == 'Sekvensering'
        assert parser.new_term == 'Sekvenseringsmetoder'

    def test_unicode_input(self):
        parser = parse_args(['Byer : Økologi', 'Byøkologi'])

        assert parser.old_term == 'Byer : Økologi'
        assert parser.new_term == 'Byøkologi'
        assert type(parser.old_term) == text_type
        assert type(parser.new_term) == text_type

if __name__ == '__main__':
    unittest.main()
