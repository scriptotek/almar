# coding=utf-8
from __future__ import print_function
from __future__ import unicode_literals

import logging.handlers
from io import open

import requests
from requests import Session
from requests.exceptions import HTTPError
from six.moves import configparser
from six.moves import input
from tqdm import tqdm

try:
    # Use lxml if installed, since it's faster ...
    from lxml import etree
except ImportError:
    # ... but also support standard ElementTree, since installation of lxml can be cumbersome
    import xml.etree.ElementTree as etree

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s')

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler('lokar.log')
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)
logger.addHandler(file_handler)

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

    def __init__(self, alma, doc):
        self.alma = alma
        self.doc = doc
        self.mms_id = self.doc.findtext('mms_id')
        self.marc_record = self.doc.find('record')

    def remove_duplicate_fields(self, vocabulary, term):
        strenger = []
        for field in subject_fields(self.marc_record, vocabulary=vocabulary, term=term):
            streng = []
            for subfield in field.findall('subfield'):
                if subfield.get('code') in ['a', 'x']:
                    streng.append(subfield.text)
                elif subfield.get('code') not in ['2', '0']:
                    logger.info('Emnefeltet inneholdt uventede delfelt: %s', etree.tostring(subfield))
            if streng in strenger:
                logger.info('Fjerner duplikat emnefelt: "%s" ', ' : '.join(streng))
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
        try:
            self.alma.put('/bibs/{}'.format(self.mms_id),
                          data=etree.tostring(self.doc),
                          headers={'Content-Type': 'application/xml'})
        except HTTPError as error:
            raise RuntimeError('Failed to save record. Status: {}. ' +
                               'Response: {}'.format(error.response.status_code, error.response.text))


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

        return Bib(self, doc)

    def get(self, url, *args, **kwargs):
        response = self.session.get(self.base_url + url, *args, **kwargs)
        response.raise_for_status()
        return response

    def put(self, url, *args, **kwargs):
        response = self.session.put(self.base_url + url, *args, **kwargs)
        response.raise_for_status()
        return response


def read_config(f, section):
    # raises NoSectionError, NoOptionError
    parser = configparser.ConfigParser()
    parser.readfp(f)

    config = {}
    for key in ['sru_url', 'api_key', 'api_region']:
        config[key] = parser.get(section, key)

    for key in ['user', 'vocabulary']:
        config[key] = parser.get('general', key)

    return config


def main(config=None, env='nz_sandbox'):

    try:
        with config or open('lokar.cfg') as f:
            config = read_config(f, env)
    except IOError:
        logger.error('Fant ikke lokar.cfg. Se README.md for mer info.')
        return

    print('{:_<80}'.format(''))
    print('{:^80}'.format('LOKAR'))
    print('{:^80}'.format('OBS: Kun oppdatering av 650-feltet støttes foreløpig'))
    print('{:^80}'.format('Miljø: %s' % env))
    print('{:^80}'.format('Vokabular: %s' % config['vocabulary']))
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
    for n, m, marc_record in sru_search('alma.subjects="%s"' % gammelord, config['sru_url']):
        if pbar is None and m != 0:
            pbar = tqdm(total=m, desc='Filtrerer SRU-resultater')

        if subject_fields(marc_record, vocabulary=config['vocabulary'], term=gammelord):
            valid_records.append(marc_record.findtext('./controlfield[@tag="001"]'))

        if pbar is not None:
            pbar.update()
    if pbar is not None:
        pbar.close()

    if len(valid_records) == 0:
        logger.info('Fant ingen poster, avslutter')
        return

    # ------------------------------------------------------------------------------------
    # Del 2: Nå har vi en liste over MMS-IDer for bibliografiske poster vi vil endre.
    # Vi går gjennom dem én for én, henter ut posten med Bib-apiet, endrer og poster tilbake.

    logger.info('Endrer fra "%s" til "%s" på %d poster', gammelord, nyord, len(valid_records))

    alma = Alma(config['api_region'], config['api_key'])

    for n, mms_id in enumerate(valid_records):

        # if record['cz'] is None:
        #     print('Posten {} er lenket til CZ! Vi bør kanskje ikke redigere den!'))
        #     break

        logger.info('[{:3d}/{:3d}] {}'.format(n + 1, len(valid_records), mms_id))
        alma.bibs(mms_id).edit_subject(config['vocabulary'], gammelord, nyord)

    return valid_records


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.exception('Uncaught exception:')
