import requests
import logging

log = logging.getLogger(__name__)


class Vocabulary(object):  # pylint: disable=too-few-public-methods

    marc_code = ''
    skosmos_code = ''
    marc_prefix = ''

    def __init__(self, marc_code, id_service_url=None, marc_prefix=None):
        self.marc_code = marc_code
        self.id_service_url = id_service_url
        self.marc_prefix = marc_prefix

    def authorize_term(self, term, tag):
        # Lookup term with some id service to get the identifier to use in $0

        if term == '':
            return None

        url = self.id_service_url.format(term=term, tag=tag)
        response = requests.get(url)
        if response.status_code != 200 or response.text == '':
            return None

        concept_id = response.text
        return concept_id
