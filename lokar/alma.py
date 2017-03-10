# coding=utf-8
from requests import Session

from .util import parse_xml
from .bib import Bib


class Alma(object):

    name = None

    def __init__(self, api_region, api_key, name=None):
        self.api_region = api_region
        self.api_key = api_key
        self.name = name
        self.session = Session()
        self.session.headers.update({'Authorization': 'apikey %s' % api_key})
        self.base_url = 'https://api-{region}.hosted.exlibrisgroup.com/almaws/v1'.format(region=self.api_region)

    def bibs(self, mms_id):
        response = self.get('/bibs/{}'.format(mms_id))
        doc = parse_xml(response.text)
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