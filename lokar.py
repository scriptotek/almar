# coding=utf-8
from __future__ import print_function
from __future__ import unicode_literals
from six.moves import input
from six.moves import configparser
from six.moves import urllib
from six import BytesIO
import requests
import sys
import time
from requests import Session
from tqdm import tqdm

try:
    # Use lxml if installed, since it's faster ...
    from lxml import etree
except ImportError:
    # ... but also support standard ElementTree, since installation of lxml can be cumbersome
    import xml.etree.ElementTree as etree

nsmap = {
    'e20': 'http://explain.z3950.org/dtd/2.0/',
    'e21': 'http://explain.z3950.org/dtd/2.1/',
    'srw': 'http://www.loc.gov/zing/srw/',
    'diag': 'http://www.loc.gov/zing/srw/diagnostic/',
}


class SruErrorResponse(RuntimeError):
    pass


def subject_fields(marc_record, term, vocabulary):
    # For a given MARC record, return subject fields matching the vocabulary and term
    fields = []
    for field in marc_record.findall('./datafield[@tag="650"]'):  # @TODO: 648, 651, 655
        if field.findtext('subfield[@code="2"]') != vocabulary:
            continue
        if field.findtext('subfield[@code="a"]') == term:
            fields.append(field)
        elif field.findtext('subfield[@code="x"]') == term:
            fields.append(field)
    return fields


def sru_search(query, url):
    # A SRU search generator that returns MARC records
    start_record = 1
    while True:
        response = requests.get(url, params={
            'version': '1.2',
            'operation': 'searchRetrieve',
            'startRecord': start_record,
            'maximumRecords': '50',
            'query': query,
        })
        root = etree.fromstring(response.text.encode('utf-8'))  # Takes ~ 4 seconds for 50 records!

        for diagnostic in root.findall('srw:diagnostics/diag:diagnostic', namespaces=nsmap):
            raise SruErrorResponse(diagnostic.findtext('diag:message', namespaces=nsmap))

        num_records = root.findtext('srw:numberOfRecords', namespaces=nsmap)
        for record in root.iterfind('srw:records/srw:record', namespaces=nsmap):
            record_no = record.findtext('srw:recordPosition', namespaces=nsmap)
            yield int(record_no), int(num_records), record.find('srw:recordData/record', namespaces=nsmap)

        nrp = root.find('srw:nextRecordPosition', namespaces=nsmap)
        if nrp is not None:
            start_record = nrp.text
        else:
            break  # Enden er nær, den er faktisk her!


class Bib(object):

    def __init__(self, alma, mms_id, doc):
        self.alma = alma
        self.mms_id = mms_id
        self.doc = doc
        self.marc_record = self.doc.find('record')
        if self.marc_record is None:
            raise RuntimeError('marc record not found')

    def remove_duplicate_fields(self, vocabulary, term):
        strenger = []
        for field in subject_fields(self.marc_record, vocabulary=vocabulary, term=term):
            streng = []
            for subfield in field.findall('subfield'):
                if subfield.get('code') in ['a', 'x']:
                    streng.append(subfield.text)
                elif subfield.get('code') not in ['2', '0']:
                    print('ERROR: Emnefeltet inneholdt uventede delfelt: ' + etree.tostring(subfield))
                    return False
            if streng in strenger:
                print('INFO: Fjerner duplikat emnefelt: ', streng.join(' : '))
                self.marc_record.remove(field)
                continue
            strenger.append(streng)

    def edit_subject(self, vocabulary, old_term, new_term):
        self.remove_duplicate_fields(vocabulary, old_term)

        for field in subject_fields(self.marc_record, vocabulary=vocabulary, term=old_term):
            for code in ['a', 'x']:
                subfield = field.find('subfield[@code="{}"]'.format(code))
                if subfield is not None and subfield.text == old_term:
                    subfield.text = new_term
                    break
        return self  # for chaining

    def save(self):
        response = self.alma.put('/bibs/{}'.format(self.mms_id), data=etree.tostring(self.doc),
                                 headers={'Content-Type': 'application/xml'})
        if response.status_code != response.codes.ok:
            raise RuntimeError('Failed to save record. Status: {}. ' +
                               'Response: {}'.format(response.status_code, response.text))


class Alma(object):

    def __init__(self, api_region, api_key):
        self.api_region = api_region
        self.api_key = api_key
        self.session = Session()
        self.session.headers.update({'Authorization': 'apikey %s' % api_key})
        self.base_url = 'https://api-{region}.hosted.exlibrisgroup.com/almaws/v1'.format(region=self.api_region)

    def bibs(self, mms_id):
        response = self.get('/bibs/{}'.format(mms_id))
        doc = etree.fromstring(response.text.encode('utf-8'))

        return Bib(self, mms_id, doc)

    def get(self, url, *args, **kwargs):
        response = self.session.get(self.base_url + url, *args, **kwargs)
        response.raise_for_status()
        return response

    def put(self, url, *args, **kwargs):
        response = self.session.put(self.base_url + url, *args, **kwargs)
        response.raise_for_status()
        return response


def main(args=None):

    config = configparser.ConfigParser()
    config.read(['lokar.cfg'])
    vocabulary = 'noubomn'

    sru_url = 'https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK'
    # sru_url='https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK'
    api_region = 'eu'
    api_key_index = 'apikey_nz_sandbox'
    api_key = config.get('alma', api_key_index)

    print('{:_<80}'.format(''))
    print('{:^80}'.format('LOKAR'))
    print('{:^80}'.format('OBS: Kun oppdatering av 650-feltet støttes foreløpig'))
    print('{:^80}'.format('Vokabular: %s' % vocabulary))
    print('{:^80}'.format('API-nøkkel: %s' % api_key_index))
    print('{:_<80}'.format(''))
    print()

    gammelord = input(' Det gamle emneordet: ').strip()
    nyord = input(' Det nye emneordet: ').strip()
    print()

    # ------------------------------------------------------------------------------------
    # Del 1: Søk mot SRU for å finne over alle bibliografiske poster med emneordet.
    # Vi må filtrere resultatlista i etterkant fordi
    #  - vi mangler en egen indeks for Realfagstermer, så vi må søke mot `alma.subjects`
    #  - søket er ikke presist, så f.eks. "Monstre" vil gi treff i "Mønstre"
    #
    # I fremtiden, når vi får $0 på alle poster, kan vi bruke indeksen `alma.authority_id`
    # i stedet.

    valid_records = []
    pbar = None
    for n, m, marc_record in sru_search('alma.subjects="%s"' % gammelord, sru_url):
        # @TODO: Vis diag: feilmelding fra respons
        if pbar is None and m != 0:
            pbar = tqdm(total=m, desc='Filtrerer SRU-resultater')

        if subject_fields(marc_record, vocabulary=vocabulary, term=gammelord):
            valid_records.append(marc_record.findtext('./controlfield[@tag="001"]'))

        if pbar is not None:
            pbar.update()
    if pbar is not None:
        pbar.close()

    if len(valid_records) == 0:
        print(' Fant ingen poster, avslutter')
        print()
        return

    print()
    print(' Antall poster som vil bli endret: {:d}'.format(len(valid_records)))
    print(' Trykk Ctrl-C innen 3 sekunder for å avbryte.')
    print()
    time.sleep(3)

    # ------------------------------------------------------------------------------------
    # Del 2: Nå har vi en liste over MMS-IDer for bibliografiske poster vi vil endre.
    # Vi går gjennom dem én for én, henter ut posten med Bib-apiet, endrer og poster tilbake.

    print('Oppdaterer poster')
    for n, mms_id in enumerate(valid_records):

        # if record['cz'] is None:
        #     print('Posten {} er lenket til CZ! Vi bør kanskje ikke redigere den!'))
        #     break

        print('[{:3d}/{:3d}] {}'.format(n + 1, len(valid_records), mms_id))
        # alma_edit(alma_session, api_region, mms_id, vocabulary, gammelord, nyord)
    print(' Finito')


if __name__ == '__main__':
    main()
