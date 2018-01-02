# coding=utf-8
from __future__ import unicode_literals
import requests
import logging
import json
from colorama import Fore, Style
from .util import ANY_VALUE, pick, pick_one

log = logging.getLogger(__name__)


class Authorities(object):

    def __init__(self, vocabularies):
        self.vocabularies = vocabularies

    def authorize_concept(self, concept):
        if '2' not in concept.sf:
            raise ValueError('No vocabulary code (2) given!')
        if concept.sf['2'] in self.vocabularies:
            vocab = self.vocabularies[concept.sf['2']]
        else:
            log.info(Fore.RED + '✘' + Style.RESET_ALL + ' Could not authorize: %s', concept)
            return

        response = vocab.authorize_term(concept.term, concept.tag)

        if response.get('id') is not None:
            identifier = response.get('id')
            if concept.sf.get('0'):
                if concept.sf.get('0') == ANY_VALUE:
                    pass  # ignore ANY_VALUE
                elif identifier != concept.sf['0']:
                    identifier = pick_one('The $$0 value does not match the authority record id. ' +
                                          'Please select which to use',
                                          [concept.sf['0'], identifier])
            concept.sf['0'] = identifier
            log.info(Fore.GREEN + '✔' + Style.RESET_ALL + ' Authorized: %s', concept)
        else:
            log.info(Fore.RED + '✘' + Style.RESET_ALL + ' Could not authorize: %s', concept)


class Vocabulary(object):

    marc_code = ''
    skosmos_code = ''

    def __init__(self, marc_code, id_service_url=None):
        self.marc_code = marc_code
        self.id_service_url = id_service_url

    def authorize_term(self, term, tag):
        # Lookup term with some id service to get the identifier to use in $0

        if term == '':
            return {}

        url = self.id_service_url.format(vocabulary=self.marc_code, term=term, tag=tag)
        response = requests.get(url)
        log.debug('Authority service response: %s', response.text)
        if response.status_code != 200 or response.text == '':
            return {}

        try:
            response = json.loads(response.text)
        except ValueError:
            log.error('ID lookup service returned: %s', response.text)
            return {}

        if 'error' in response and response.get('uri') != 'info:srw/diagnostic/1/61':
            log.warning('ID lookup service returned: %s', response['error'])

        return response
