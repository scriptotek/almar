# coding=utf-8
import requests
import logging

from .marc import Record
from .util import parse_xml

log = logging.getLogger(__name__)

nsmap = {
    'e20': 'http://explain.z3950.org/dtd/2.0/',
    'e21': 'http://explain.z3950.org/dtd/2.1/',
    'srw': 'http://www.loc.gov/zing/srw/',
    'diag': 'http://www.loc.gov/zing/srw/diagnostic/',
}


class SruErrorResponse(RuntimeError):
    pass


class SruClient(object):

    def __init__(self, endpoint_url, name=None):
        self.endpoint_url = endpoint_url
        self.name = name
        self.record_no = 0  # from last response
        self.num_records = 0  # from last response

    def search(self, query):
        log.info('SRU search: {}'.format(query))
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
            root = parse_xml(response.text)  # Takes ~ 4 seconds for 50 records!

            for diagnostic in root.findall('srw:diagnostics/diag:diagnostic', namespaces=nsmap):
                raise SruErrorResponse(diagnostic.findtext('diag:message', namespaces=nsmap))

            self.num_records = int(root.findtext('srw:numberOfRecords', namespaces=nsmap))
            for record in root.iterfind('srw:records/srw:record', namespaces=nsmap):
                self.record_no = int(record.findtext('srw:recordPosition', namespaces=nsmap))

                yield Record(record.find('srw:recordData/record', namespaces=nsmap))

            nrp = root.find('srw:nextRecordPosition', namespaces=nsmap)
            if nrp is not None:
                start_record = nrp.text
            else:
                break  # Enden er nær, den er faktisk her!
