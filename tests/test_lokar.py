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

from lokar import subject_fields, sru_search, nsmap, SruErrorResponse, Alma, Bib, read_config, main, authorize_term, \
    parse_args
from textwrap import dedent

try:
    # Use lxml if installed, since it's faster ...
    from lxml import etree
except ImportError:
    # ... but also support standard ElementTree, since installation of lxml can be cumbersome
    import xml.etree.ElementTree as etree


def get_sample(filename, as_xml=False):
    with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data/%s' % filename), encoding='utf-8') as fp:
        body = fp.read()
    if as_xml:
        return etree.fromstring(body.encode('utf-8'))
    return body


class TestFindSubjectFields(unittest.TestCase):

    def test650a(self):
        marc_record = etree.fromstring('''
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
        '''.encode('utf-8'))

        fields = subject_fields(marc_record, vocabulary='noubomn', term='Monstre')

        assert len(fields) == 1
        assert fields[0].findtext('subfield[@code="a"]') == 'Monstre'

    def test650x(self):
        marc_record = etree.fromstring('''
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
        '''.encode('utf-8'))

        fields = subject_fields(marc_record, vocabulary='noubomn', term='Atferd')

        assert len(fields) == 2
        assert fields[1].findtext('subfield[@code="a"]') == 'Monstre'
        assert fields[1].findtext('subfield[@code="x"]') == 'Atferd'


class TestSruSearch(unittest.TestCase):

    @responses.activate
    def testSimpleSearch(self):
        url = 'http://test/'

        body = get_sample('sru_sample_response_1.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')

        records = list(sru_search('alma.subjects="test"', url))

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

        records = list(sru_search('alma.subjects="test"', url))

        assert len(responses.calls) == 2
        assert len(records) == 2

    @responses.activate
    def testErrorResponse(self):
        url = 'http://test/'

        body = get_sample('sru_error_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')

        with pytest.raises(SruErrorResponse):
            records = list(sru_search('alma.subjects="test"', url))

        assert len(responses.calls) == 1


class TestAlma(unittest.TestCase):

    @responses.activate
    def testBibs(self):
        mms_id = '991416299674702204'
        alma = Alma('test', 'key')
        url = '{}/bibs/{}'.format(alma.base_url, mms_id)
        body = get_sample('bib_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')
        alma.bibs(mms_id).edit_subject('humord', 'abc', 'def')

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
        rec = etree.fromstring("""
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
        bib.edit_subject('noubomn', 'Monstre', 'Mønstre')

        assert 'Mønstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'Atferd' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')  # $x should not change!

    def testModify650x(self):
        rec = etree.fromstring("""
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
        bib.edit_subject('noubomn', 'Atferd', 'Dagbøker')

        assert 'Monstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')  # $a should not change!
        assert 'Dagbøker' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testModify650ax(self):
        rec = etree.fromstring("""
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
        bib.edit_subject('noubomn', 'Monstre : Atferd', 'Mønstre : Dagbøker')

        assert 'Mønstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'Dagbøker' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testModify650_ax_to_a(self):
        rec = etree.fromstring("""
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
        bib.edit_subject('noubomn', 'Monstre : Atferd', 'Monsteratferd')

        assert 'Monsteratferd' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert rec.find('record/datafield[@tag="650"]/subfield[@code="x"]') is None

    def testModify651(self):
        rec = etree.fromstring("""
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
        bib.edit_subject('noubomn', 'Oslo', 'Bergen', tag='651')

        assert 'Bergen' == rec.findtext('record/datafield[@tag="651"]/subfield[@code="a"]')
        assert 'Oslo' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')   # 650 should not change!

    def testRemoveTerm(self):
        rec = etree.fromstring("""
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
        bib.remove_subject('noubomn', 'Monstre')
        fields = rec.findall('record/datafield[@tag="650"]')

        assert len(fields) == 1
        assert 'Monstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert 'atferd' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')

    def testRemoveSubjectString(self):
        rec = etree.fromstring("""
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
        bib.remove_subject('noubomn', 'Monstre : Atferd')
        fields = rec.findall('record/datafield[@tag="650"]')

        assert len(fields) == 1
        assert 'Monstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')
        assert rec.find('record/datafield[@tag="650"]/subfield[@code="x"]') is None

    def testRemoveGeoTerm(self):
        rec = etree.fromstring("""
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
        bib.remove_subject('noubomn', 'Oslo', tag='651')
        f650 = rec.findall('record/datafield[@tag="650"]')
        f651 = rec.findall('record/datafield[@tag="651"]')

        assert len(f650) == 1
        assert len(f651) == 0

    def testSave(self):
        alma = Mock()
        doc = get_sample('bib_response.xml', True)
        bib = Bib(alma, doc)
        bib.edit_subject('noubomn', 'Kryptozoologi', 'KryptoÆØÅ')
        bib.save()

        alma.put.assert_called_once_with('/bibs/991416299674702204', data=ANY, headers={'Content-Type': 'application/xml'})

    def testDups(self):
        marc_record = etree.fromstring('''
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

        bib.remove_duplicate_fields('noubomn', 'Monstre')

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


class TestLokar(unittest.TestCase):

    @staticmethod
    def conf():
        return StringIO(dedent('''
        [general]
        vocabulary=noubomn
        user=someuser
        skosmos_vocab=realfagstermer

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
            yield n, len(recs), rec

    @patch('lokar.authorize_term', autospec=True)
    @patch('lokar.sru_search', autospec=True)
    @patch('lokar.Alma', autospec=True, spec_set=True)
    def testMain(self, MockAlma, mock_sru, mock_authorize_term):
        old_term = 'Statistiske modeller'
        new_term = 'Test æøå'
        mock_sru.side_effect = TestLokar.sru_search_mock
        mock_authorize_term.return_value = {'localname': 'c030697'}

        valid_records = main(self.conf(), [old_term, new_term, '-e test_env'])

        alma = MockAlma.return_value

        assert len(valid_records) == 14
        mock_sru.assert_called_once_with('alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (old_term, 'noubomn'),
                                         'https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK')

        assert alma.bibs.call_count == 14

    @patch('lokar.authorize_term', autospec=True)
    @patch('lokar.sru_search', autospec=True)
    @patch('lokar.Alma', autospec=True, spec_set=True)
    def testMainNoHits(self, MockAlma, mock_sru, mock_authorize_term):
        old_term = 'Something else'
        new_term = 'Test æøå'
        mock_sru.side_effect = TestLokar.sru_search_mock
        mock_authorize_term.return_value = {'localname': 'c030697'}

        valid_records = main(self.conf(), [old_term, new_term, '-e test_env'])

        alma = MockAlma.return_value

        assert valid_records is None
        mock_sru.assert_called_once_with('alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (old_term, 'noubomn'),
                                         'https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK')

        assert alma.bibs.call_count == 0

    @patch('lokar.authorize_term', autospec=True)
    @patch('lokar.sru_search', autospec=True)
    @patch('lokar.Alma', autospec=True, spec_set=True)
    def testRemoveTerm(self, MockAlma, mock_sru, mock_authorize_term):
        old_term = 'Statistiske modeller'
        mock_sru.side_effect = TestLokar.sru_search_mock
        mock_authorize_term.return_value = {'localname': 'c030697'}

        valid_records = main(self.conf(), [old_term, '', '-e test_env'])

        alma = MockAlma.return_value

        assert len(valid_records) == 14
        mock_sru.assert_called_once_with('alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (old_term, 'noubomn'),
                                         'https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK')

        assert alma.bibs.call_count == 14

    @patch('lokar.open', autospec=True)
    def testConfigMissing(self, mock_open):
        mock_open.side_effect = IOError('File not found')
        main(args=['old', 'new'])
        mock_open.assert_called_once_with('lokar.cfg')


class TestParseArgs(unittest.TestCase):

    def test_parser_missing_arguments(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parser(self):
        parser = parse_args(['Sekvensering', 'Sekvenseringsmetoder'])

        assert parser.dry_run is False
        assert parser.tag == '650'
        assert parser.old_term == 'Sekvensering'
        assert parser.new_term == 'Sekvenseringsmetoder'


if __name__ == '__main__':
    unittest.main()
