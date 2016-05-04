# encoding=utf-8
import os
import unittest
import pytest
import xml.etree.ElementTree as etree
import responses
from unittest.mock import Mock
from lokar import subject_fields, sru_search, nsmap, SruErrorResponse, Alma, Bib


def get_sample(filename):
    with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data/%s' % filename)) as fp:
        body = fp.read()
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
        ''')

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
        ''')

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
        assert len(records) == 40

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


class TestUpdateMarcRecord(unittest.TestCase):

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
        bib = Bib(Mock(), '123', rec)
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
        bib = Bib(Mock(), '123', rec)
        bib.edit_subject('noubomn', 'Atferd', 'Dagbøker')

        assert 'Monstre' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="a"]')  # $a should not change!
        assert 'Dagbøker' == rec.findtext('record/datafield[@tag="650"]/subfield[@code="x"]')


class TestAlmaEdit(unittest.TestCase):

    @responses.activate
    def test1(self):
        mms_id = '123'
        alma = Alma('test', 'key')
        url = '{}/bibs/{}'.format(alma.base_url, mms_id)
        body = get_sample('bib_response.xml')
        responses.add(responses.GET, url, body=body, content_type='application/xml')
        responses.add(responses.PUT, url, body=body, content_type='application/xml')

        alma.bibs(mms_id).edit_subject('humord', 'abc', 'def')


if __name__ == '__main__':
    unittest.main()
