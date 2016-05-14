# coding=utf-8
from __future__ import print_function
from __future__ import unicode_literals
import argparse
import logging.handlers
from io import open
import io

import requests
import sys
import os
from six import text_type, binary_type
from datetime import datetime
from requests import Session
from requests.exceptions import HTTPError
from six.moves import configparser
from tqdm import tqdm
from prompter import yesno

try:
    # Use lxml if installed, since it's faster ...
    from lxml import etree
except ImportError:
    # ... but also support standard ElementTree, since installation of lxml can be cumbersome
    import xml.etree.ElementTree as etree

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logging.getLogger('requests').setLevel(logging.WARNING)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S')

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

log_capture_string = io.StringIO()
capture_handler = logging.StreamHandler(log_capture_string)
capture_handler.setLevel(logging.DEBUG)
capture_handler.setFormatter(formatter)
logger.addHandler(capture_handler)

nsmap = {
    'e20': 'http://explain.z3950.org/dtd/2.0/',
    'e21': 'http://explain.z3950.org/dtd/2.1/',
    'srw': 'http://www.loc.gov/zing/srw/',
    'diag': 'http://www.loc.gov/zing/srw/diagnostic/',
}


def normalize_term(term):
    # Normalize term so it starts with a capital letter. If the term is a subject string
    # fused by " : ", normalize all components.
    if term is None or len(term) == 0:
        return term

    return ' : '.join([component[0].upper() + component[1:] for component in term.strip().split(' : ')])


class SruErrorResponse(RuntimeError):
    pass


class SruClient(object):

    def __init__(self, endpoint_url):
        self.endpoint_url = endpoint_url
        self.record_no = 0  # from last response
        self.num_records = 0  # from last response

    def search(self, query):
        # A searchRetrieve generator that yields MarcRecord objects
        start_record = 1
        while True:
            response = requests.get(self.endpoint_url, params={
                'version': '1.2',
                'operation': 'searchRetrieve',
                'startRecord': start_record,
                'maximumRecords': '50',
                'query': query,
            })
            root = etree.fromstring(response.text.encode('utf-8'))  # Takes ~ 4 seconds for 50 records!

            for diagnostic in root.findall('srw:diagnostics/diag:diagnostic', namespaces=nsmap):
                raise SruErrorResponse(diagnostic.findtext('diag:message', namespaces=nsmap))

            self.num_records = int(root.findtext('srw:numberOfRecords', namespaces=nsmap))
            for record in root.iterfind('srw:records/srw:record', namespaces=nsmap):
                self.record_no = int(record.findtext('srw:recordPosition', namespaces=nsmap))

                yield MarcRecord(record.find('srw:recordData/record', namespaces=nsmap))

            nrp = root.find('srw:nextRecordPosition', namespaces=nsmap)
            if nrp is not None:
                start_record = nrp.text
            else:
                break  # Enden er nær, den er faktisk her!


class MarcRecord(object):
    """ A Marc21 record """

    def __init__(self, el):
        # el: xml.etree.ElementTree.Element
        self.el = el

    def id(self):
        return self.el.findtext('./controlfield[@tag="001"]')

    def subjects(self, term, vocabulary, tags, exact_only=False):
        """
        For a given MARC record, return subject fields matching the vocabulary and term.
        :param term:
        :param vocabulary:
        :param tags:
        :param exact_only: True to only return fields with the term in $a and with no $x
                           False to return fields with the term in either $a or $x
        :return:
        """

        fields = []
        for tag in tags:
            for field in self.el.findall('./datafield[@tag="{}"]'.format(tag)):
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

    def remove_duplicate_fields(self, vocabulary, term, tags):
        strenger = []
        for field in self.subjects(vocabulary=vocabulary, term=term, tags=tags):
            streng = [field.get('tag')]
            for subfield in field.findall('subfield'):
                if subfield.get('code') in ['a', 'x']:
                    streng.append(subfield.text)
                elif subfield.get('code') not in ['2', '0']:
                    logger.info('Emnefeltet inneholdt uventede delfelt: %s', etree.tostring(subfield))
            if streng in strenger:
                logger.info('Fjerner duplikat emnefelt: "%s" ', ' : '.join(streng))
                self.el.remove(field)
                continue
            strenger.append(streng)

    def edit_subject(self, vocabulary, old_term, new_term, tags):

        old_term_comp = old_term.split(' : ')
        new_term_comp = new_term.split(' : ')

        for field in self.subjects(vocabulary=vocabulary, term=old_term, tags=tags):
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

        self.remove_duplicate_fields(vocabulary, new_term, tags)
        return self  # for chaining

    def remove_subject(self, vocabulary, term, tags):
        for field in self.subjects(vocabulary=vocabulary, term=term, tags=tags, exact_only=True):
            self.el.remove(field)
        return self  # for chaining


class Bib(object):
    """ An Alma Bib record """

    def __init__(self, alma, doc):
        self.alma = alma
        self.init_from_doc(doc)

    def init_from_doc(self, doc):
        self.doc = doc
        self.mms_id = self.doc.findtext('mms_id')
        self.marc_record = MarcRecord(self.doc.find('record'))
        self.linked_to_cz = self.doc.findtext('linked_record_id[@type="CZ"]') or None

    def save(self):
        # Save record back to Alma
        if self.linked_to_cz:
            logger.info(' -> OBS! Posten er koblet til CZ! Koblingen blir brutt hvis du oppdaterer posten!')
            if yesno('Vil du fortsette allikevel?', default='no'):
                logger.info(' -> Hopper over denne posten')
                return
            logger.info(' -> Oppdaterer posten. Koblingen til CZ blir brutt.')

        try:
            response = self.alma.put('/bibs/{}'.format(self.mms_id),
                                     data=etree.tostring(self.doc),
                                     headers={'Content-Type': 'application/xml'})
        except HTTPError as error:
            raise RuntimeError('Failed to save record. Status: %s. Response: %s'
                               % (error.response.status_code, error.response.text))

        self.init_from_doc(etree.fromstring(response.encode('utf-8')))

    def dump(self, filename):
        # Dump record to file
        with open(filename, 'wb') as f:
            f.write(etree.tostring(self.doc, pretty_print=True))


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
        if doc.findtext('mms_id') != mms_id:
            raise RuntimeError('Response does not contain the requested MMS ID. %s != %s'
                               % (doc.findtext('mms_id'), mms_id))
        return Bib(self, doc)

    def get(self, url, *args, **kwargs):
        response = self.session.get(self.base_url + url, *args, **kwargs)
        response.raise_for_status()
        return response

    def put(self, url, *args, **kwargs):
        response = self.session.put(self.base_url + url, *args, **kwargs)
        response.raise_for_status()
        return response.text


def read_config(f, section):
    # raises NoSectionError, NoOptionError
    parser = configparser.ConfigParser()
    parser.readfp(f)

    config = {}
    for key in ['sru_url', 'api_key', 'api_region']:
        config[key] = parser.get(section, key)

    for key in ['user', 'vocabulary', 'skosmos_vocab']:
        config[key] = parser.get('general', key)

    for key in ['domain', 'api_key', 'sender', 'recipient']:
        config['mailgun.' + key] = parser.get('mailgun', key)

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


def skosmos_check(vocab, tag, old_term, new_term):
    concept_types = {
        '648': 'http://data.ub.uio.no/onto#Time',
        '650': 'http://data.ub.uio.no/onto#Topic',
        '651': 'http://data.ub.uio.no/onto#Place',
        '655': 'http://data.ub.uio.no/onto#GenreForm',
    }
    concept_type = concept_types[tag]
    old_concept = authorize_term(old_term, concept_type, vocab)
    new_concept = authorize_term(new_term, concept_type, vocab)
    if old_concept is not None:
        local_id = old_concept['localname'].strip('c')
        logger.info('Termen "%s" ble autorisert med ID %s', old_term, local_id)
    if new_concept is not None:
        local_id = new_concept['localname'].strip('c')
        logger.info('Termen "%s" ble autorisert med ID %s', new_term, local_id)
    if old_concept is None and new_concept is None:
        terms = [old_term]
        if len(new_term) != 0:
            terms.append(new_term)
        logger.error('Fant ikke %s som <%s> i <%s>',
                     ' eller '.join(['"%s"' % term for term in terms]), concept_type, vocab)
        return False
    return True


def parse_args(args):
    parser = argparse.ArgumentParser(description='LOKAR')
    parser.add_argument('old_term', nargs=1, help='Old term')
    parser.add_argument('new_term', nargs='?', default='', help='New term')

    parser.add_argument('-t', '--tag', dest='tag', nargs='?',
                        help='MARC tag (648/650/651/655). Default: 650',
                        default='650', choices=['648', '650', '651', '655'])

    parser.add_argument('-e', '--env', dest='env', nargs='?',
                        help='Environment from config file. Default: nz_sandbox',
                        default='nz_sandbox')

    parser.add_argument('-d', '--dry_run', dest='dry_run', action='store_true',
                        help='Dry run without doing any edits.')

    # parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='More verbose output')

    args = parser.parse_args(args)
    args.env = args.env.strip()
    args.old_term = args.old_term[0]
    args.new_term = args.new_term

    if type(args.old_term) == binary_type:
        args.old_term = args.old_term.decode('utf-8')
    if type(args.new_term) == binary_type:
        args.new_term = args.new_term.decode('utf-8')
    if type(args.env) == binary_type:
        args.env = args.env.decode('utf-8')

    return args


def email(subject, body, config):
    request_url = 'https://api.mailgun.net/v2/{0}/messages'.format(config['mailgun.domain'])
    request = requests.post(request_url, auth=('api', config['mailgun.api_key']), data={
        'from': config['mailgun.sender'],
        'to': config['mailgun.recipient'],
        'subject': subject,
        'text': body
    })
    request.raise_for_status()


def main(config=None, args=None):

    args = parse_args(args or sys.argv[1:])

    try:
        with config or open('lokar.cfg') as f:
            config = read_config(f, args.env)
    except IOError:
        logger.error('Fant ikke lokar.cfg. Se README.md for mer info.')
        return

    if not args.dry_run:
        file_handler = logging.FileHandler('lokar.log')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

    old_term = normalize_term(args.old_term)
    new_term = normalize_term(args.new_term)

    logger.info('{:=^70}'.format(' Starter jobb '))
    logger.info('[ Miljø: %s ] [ Vokabular: %s ] [ Bruker: %s] [ Tørrkjøring? %s ]'
                % (args.env, config['vocabulary'], config['user'], 'JA' if args.dry_run else 'NEI'))

    if not skosmos_check(config['skosmos_vocab'], args.tag, old_term, new_term):
        if yesno('Vil du fortsette allikevel?', default='no'):
            return

    job_name = datetime.now().isoformat()

    tags = [args.tag]
    if args.tag == '648':
        tags.append('650')
        logger.info('MERK: For 648 gjør vi også erstatning i duplikaten i 650')

    oc = old_term.split(' : ')
    nc = new_term.split(' : ')

    reporting_info = {'t': ','.join(tags), 'v': config['vocabulary'], 'o': oc[0], 'n': nc[0]}
    if len(oc) == 2 and len(nc) == 2:
        reporting_info['o2'] = oc[1]
        reporting_info['n2'] = nc[1]
        logger.info('Erstatter "$a %(o)s $x %(o2)s" med "$a %(n)s $x %(n2)s" i %(t)s-felt som har $2 %(v)s',
                    reporting_info)
    elif len(oc) == 2 and len(nc) == 1:
        reporting_info['o2'] = oc[1]
        if new_term == '':
            logger.info('Fjerner %(t)s-felt som har "$a %(o)s $x %(o2)s $2 %(v)s"', reporting_info)
        else:
            logger.info('Erstatter "$a %(o)s $x %(o2)s" med "$a %(n)s" i %(t)s-felt som har $2 %(v)s"', reporting_info)
    elif len(oc) == 1 and len(nc) == 1:
        if new_term == '':
            logger.info('Fjerner %(t)s-felt som har "$a %(o)s $2 %(v)s"', reporting_info)
        else:
            logger.info('Erstatter "%(o)s" med "%(n)s" i $a og $x i %(t)s-felt som har $2 %(v)s', reporting_info)
    else:
        logger.error('Antall strengkomponenter i gammel eller ny term er ikke støttet')
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
    sru = SruClient(config['sru_url'])
    cql_query = 'alma.subjects="%s" AND alma.authority_vocabulary = "%s"' % (old_term, config['vocabulary'])
    for marc_record in sru.search(cql_query):
        if pbar is None and sru.num_records > 50:
            pbar = tqdm(total=sru.num_records, desc='Filtrerer SRU-resultater')

        if marc_record.subjects(vocabulary=config['vocabulary'], term=old_term, tags=tags):
            valid_records.append(marc_record.id())

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

    alma = Alma(config['api_region'], config['api_key'])

    for n, mms_id in enumerate(valid_records):

        # if record['cz'] is None:
        #     print('Posten {} er lenket til CZ! Vi bør kanskje ikke redigere den!'))
        #     break

        logger.info('[{:3d}/{:3d}] {}'.format(n + 1, len(valid_records), mms_id))
        bib = alma.bibs(mms_id)
        if not args.dry_run:
            if not os.path.exists('jobs/%s' % job_name):
                os.makedirs('jobs/%s' % job_name)
            bib.dump('jobs/%s/%s.before.xml' % (job_name, mms_id))
        if new_term == '':
            bib.marc_record.remove_subject(config['vocabulary'], old_term, tags=tags)
        else:
            bib.marc_record.edit_subject(config['vocabulary'], old_term, new_term, tags=tags)
        if not args.dry_run:
            txt = bib.save()
            bib.dump('jobs/%s/%s.after.xml' % (job_name, mms_id))

    logger.info('{:=^70}'.format(' Jobb ferdig '))

    if not args.dry_run:
        subject = '[{}] "{}" → "{}" endret i {:d} post(er)'.format(args.tag, old_term, new_term, len(valid_records))
        body = log_capture_string.getvalue()
        email(subject, body, config)

    return valid_records


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.exception('Uncaught exception:')
