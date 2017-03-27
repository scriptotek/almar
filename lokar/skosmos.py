import logging
import requests

log = logging.getLogger(__name__)

concept_types = {
    '648': 'http://data.ub.uio.no/onto#Time',
    '650': 'http://data.ub.uio.no/onto#Topic',
    '651': 'http://data.ub.uio.no/onto#Place',
    '655': 'http://data.ub.uio.no/onto#GenreForm',
}


class Skosmos(object):

    def __init__(self, vocabulary_code):
        self.vocabulary_code = vocabulary_code

    def authorize_term(self, term, tag):
        # Lookup term in Skosmos to get identifier, etc.

        concept_type = concept_types[tag]

        if term == '':
            return None

        response = requests.get('http://data.ub.uio.no/skosmos/rest/v1/%s/search' % self.vocabulary_code, params={
            'lang': 'nb',
            'query': term
        }).json()

        results = [res for res in response['results'] if concept_type in res['type']]

        if len(results) == 0:
            return None
        return results[0]
