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


def normalize_term(term):
    # Normalize term so it starts with a capital letter. If the term is a subject string
    # fused by " : ", normalize all components.
    if term is None or len(term) == 0:
        return term

    return ' : '.join([component[0].upper() + component[1:] for component in term.strip().split(' : ')])


def subject_fields(marc_record, term, vocabulary, tag='650', exact_only=False):
    """
    For a given MARC record, return subject fields matching the vocabulary and term.
    :param marc_record:
    :param term:
    :param vocabulary:
    :param tag:
    :param exact_only: True to only return fields with the term in $a and with no $x
                       False to return fields with the term in either $a or $x
    :return:
    """

    fields = []
    for field in marc_record.findall('./datafield[@tag="{}"]'.format(tag)):
        if field.findtext('subfield[@code="2"]') != vocabulary:
            # Wrong vocabulary
            continue

        sfa = normalize_term(field.findtext('subfield[@code="a"]'))
        sfx = normalize_term(field.findtext('subfield[@code="x"]'))

        components = term.split(' : ')
        if len(components) == 2:
            if sfa == components[0] and sfx == components[1]:
                fields.append(field)
        elif exact_only:
            if sfa == term and sfx is None:
                fields.append(field)
        else:
            if sfa == term or sfx == term:
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

    def remove_duplicate_fields(self, vocabulary, term, tag='650'):
        strenger = []
        for field in subject_fields(self.marc_record, vocabulary=vocabulary, term=term, tag=tag):
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

    def edit_subject(self, vocabulary, old_term, new_term, tag='650'):
        self.remove_duplicate_fields(vocabulary, old_term, tag)

        old_term_comp = old_term.split(' : ')
        new_term_comp = new_term.split(' : ')

        for field in subject_fields(self.marc_record, vocabulary=vocabulary, term=old_term, tag=tag):
            sfa = field.find('subfield[@code="a"]')
            sfx = field.find('subfield[@code="x"]')
            sfa_m0 = sfa is not None and normalize_term(sfa.text) == old_term_comp[0]
            sfx_m0 = sfx is not None and normalize_term(sfx.text) == old_term_comp[0]
            if len(old_term_comp) == 2:
                sfx_m1 = sfx is not None and normalize_term(sfx.text) == old_term_comp[1]
                if sfa_m0 and sfx_m1:
                    if len(new_term_comp) == 2:
                        sfa.text = new_term_comp[0]
                        sfx.text = new_term_comp[1]
                    else:
                        sfa.text = new_term_comp[0]
                        field.remove(sfx)
            else:
                if sfa_m0:
                    sfa.text = new_term_comp[0]
                elif sfx_m0:
                    sfx.text = new_term_comp[0]

        return self  # for chaining

    def remove_subject(self, vocabulary, term, tag='650'):
        for field in subject_fields(self.marc_record, vocabulary=vocabulary, term=term, tag=tag, exact_only=True):
            self.marc_record.remove(field)
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

    for key in ['user', 'vocabulary', 'skosmos_vocab']:
        config[key] = parser.get('general', key)

    return config


def authorize_term(term, concept_type, vocabulary):
    # Lookup term in Skosmos to get identifier, etc.
    if term == '':
        return None

    response = requests.get('http://data.ub.uio.no/skosmos/rest/v1/%s/search' % vocabulary, params={
        'lang': 'nb',
        'query': term
    }).json()

    results = [res for res in response['results'] if concept_type in res['type']]

    if len(results) == 0:
        return None
    return results[0]


def main(config=None, env='nz_sandbox'):

    try:
        with config or open('lokar.cfg') as f:
            config = read_config(f, env)
    except IOError:
        logger.error('Fant ikke lokar.cfg. Se README.md for mer info.')
        return

    print('{:_<80}'.format(''))
    print('{:^80}'.format('LOKAR'))
    print(' Miljø: %s' % env)
    print(' Vokabular: %s' % config['vocabulary'])
    print()
    print(' Kan gjøre streng-erstatninger av typen "A : B" → "C : D" og "A : B" → "C",')
    print(' men pass på at du har med mellomrom før og etter kolon.')
    print()
    print('{:_<80}'.format(''))
    print()

    tag = input(' MARC-felt [650]: ').strip() or '650'
    if tag not in ['648', '650', '651', '655']:
        logger.error('Ugyldig felt. Støtter kun 648, 650, 651 og 655')
        return
    gammelord = normalize_term(input(' Det gamle emneordet: '))
    nyord = normalize_term(input(' Det nye emneordet: '))

    if len(gammelord) == 0:
        logger.error('Old term cannot be blank')
        return

    oc = gammelord.split(' : ')
    nc = nyord.split(' : ')
    if len(oc) == 2 and len(nc) == 2:
        logger.info('Erstatter "%(p)s $a %(o1)s $x %(o2)s" med "%(p)s $a %(n1)s $x %(n2)s"',
                    {'p': tag + ' $2 noubomn', 'o1': oc[0], 'o2': oc[1], 'n1': nc[0], 'n2': nc[1]})
    elif len(oc) == 2 and len(nc) == 1:
        logger.info('Erstatter "%(p)s $a %(o1)s $x %(o2)s" med "%(p)s $a %(n1)s"',
                    {'p': tag + ' $2 noubomn', 'o1': oc[0], 'o2': oc[1], 'n1': nc[0]})
    elif len(oc) == 1 and len(nc) == 1:
        if nyord == '':
            logger.info('Fjerner "%(p)s $a %(o)s"',
                        {'p': tag + ' $2 noubomn', 'o': oc[0]})
        else:
            logger.info('Erstatter "%(o)s" med "%(n)s" i %(p)s $a og $x',
                        {'p': tag + ' $2 noubomn', 'o': oc[0], 'n': nc[0]})
    else:
        logger.error('Unsupported number of components in old or new term')
        return

    concept_types = {
        '648': 'http://data.ub.uio.no/onto#Temporal',
        '650': 'http://data.ub.uio.no/onto#Topic',
        '651': 'http://data.ub.uio.no/onto#Place',
        '655': 'http://data.ub.uio.no/onto#GenreForm',
    }
    concept_type = concept_types[tag]
    old_concept = authorize_term(gammelord, concept_type, config['skosmos_vocab'])
    new_concept = authorize_term(nyord, concept_type, config['skosmos_vocab'])
    if old_concept is not None:
        local_id = old_concept['localname'].strip('c')
        logger.info('Termen "%s" ble autorisert med ID %s', gammelord, local_id)
    if new_concept is not None:
        local_id = new_concept['localname'].strip('c')
        logger.info('Termen "%s" ble autorisert med ID %s', nyord, local_id)
    if old_concept is None and new_concept is None:
        logger.error('Fant verken "%s" eller "%s" som <%s> i <%s>',
                     gammelord, nyord, concept_type, config['vocabulary'])
        return

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
    cql_query = 'alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (gammelord, config['vocabulary'])
    for n, m, marc_record in sru_search(cql_query, config['sru_url']):
        if pbar is None and m != 0:
            pbar = tqdm(total=m, desc='Filtrerer SRU-resultater')

        if subject_fields(marc_record, vocabulary=config['vocabulary'], term=gammelord, tag=tag):
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

    if nyord == '':
        logger.info('Fjerner "%s" fra %d poster', gammelord, len(valid_records))
    else:
        logger.info('Endrer fra "%s" til "%s" på %d poster', gammelord, nyord, len(valid_records))

    alma = Alma(config['api_region'], config['api_key'])

    for n, mms_id in enumerate(valid_records):

        # if record['cz'] is None:
        #     print('Posten {} er lenket til CZ! Vi bør kanskje ikke redigere den!'))
        #     break

        logger.info('[{:3d}/{:3d}] {}'.format(n + 1, len(valid_records), mms_id))
        if nyord == '':
            alma.bibs(mms_id).remove_subject(config['vocabulary'], gammelord, nyord, tag=tag)
        else:
            alma.bibs(mms_id).edit_subject(config['vocabulary'], gammelord, nyord, tag=tag)

    return valid_records


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.exception('Uncaught exception:')
