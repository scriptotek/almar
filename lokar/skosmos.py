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

    def authorize_term(self, term, concept_type):
        # Lookup term in Skosmos to get identifier, etc.

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

    def check(self, tag, old_term, new_term, new_tag=None):
        concept_id = None
        old_concept = self.authorize_term(old_term, concept_types[tag])
        new_concept = self.authorize_term(new_term, concept_types[new_tag or tag])
        if old_concept is not None:
            concept_id = old_concept['localname'].strip('c')
            log.info('Source term "%s" (%s) authorized as %s in Skosmos', old_term, tag, concept_id)
        if new_concept is not None:
            concept_id = new_concept['localname'].strip('c')
            log.info('Target term "%s" (%s) authorized as %s in Skosmos', new_term, tag, concept_id)
        if old_concept is None and new_concept is None:
            terms = ['"%s" (as %s)' % (old_term, tag)]
            if len(new_term) != 0:
                terms.append('"%s" (as %s)' % (new_term, new_tag or tag))
            log.warning('Failed to authorize both %s in Skosmos.',
                        ' and '.join(terms))
        return concept_id
