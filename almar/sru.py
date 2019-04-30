# coding=utf-8
from __future__ import unicode_literals

import logging

import requests

from .marc import Record
from .util import parse_xml

log = logging.getLogger(__name__)

NSMAP = {
    'e20': 'http://explain.z3950.org/dtd/2.0/',
    'e21': 'http://explain.z3950.org/dtd/2.1/',
    'srw': 'http://www.loc.gov/zing/srw/',
    'diag': 'http://www.loc.gov/zing/srw/diagnostic/',
}


class SruErrorResponse(RuntimeError):
    pass


class TooManyResults(RuntimeError):
    pass


class SruClient(object):

    def __init__(self, endpoint_url, cache, name=None, cache_time=300):
        self.endpoint_url = endpoint_url
        self.cache = cache
        self.cache_time = cache_time
        self.name = name
        self.record_no = 0  # from last response
        self.num_records = 0  # from last response

    def request_and_cache(self, query, start_record, cache_key):
        response = requests.get(self.endpoint_url, params={
            'version': '1.2',
            'operation': 'searchRetrieve',
            'startRecord': start_record,
            'maximumRecords': '50',
            'query': query,
        })
        response.raise_for_status()
        self.cache.set(cache_key, response.text, expire=self.cache_time)
        return response.text

    def request(self, query, start_record):
        cache_key = 'sru:{}:{}'.format(query, start_record)

        return self.cache.get(cache_key) or self.request_and_cache(query, start_record, cache_key)

    def search(self, query):
        log.debug('SRU search: %s', query)
        # A searchRetrieve generator that yields MarcRecord objects
        start_record = 1
        while True:
            response = self.request(query, start_record)

            # Fix for the sudden addition of namespaces to the SRU response.
            # The problem is that the Bibs API still don't use namespaces,
            # so by removing the namespace the XML is compatible with the Bibs API.
            txt = response.replace('xmlns="http://www.loc.gov/MARC21/slim"', 'xmlns=""')

            root = parse_xml(txt)  # Takes ~ 4 seconds for 50 records!

            for diagnostic in root.findall('srw:diagnostics/diag:diagnostic', namespaces=NSMAP):
                raise SruErrorResponse(diagnostic.findtext('diag:message', namespaces=NSMAP))

            self.num_records = int(root.findtext('srw:numberOfRecords', namespaces=NSMAP))
            if self.num_records > 10000:
                raise TooManyResults()

            for record in root.iterfind('srw:records/srw:record', namespaces=NSMAP):
                self.record_no = int(record.findtext('srw:recordPosition', namespaces=NSMAP))

                yield Record(record.find('srw:recordData/record', namespaces=NSMAP))

            nrp = root.find('srw:nextRecordPosition', namespaces=NSMAP)
            if nrp is not None:
                start_record = nrp.text
            else:
                break  # Enden er nær, den er faktisk her!
