# coding=utf-8
from requests.exceptions import HTTPError

from .marc import Record
from .util import etree, parse_xml


class BibSaveError(RuntimeError):
    pass


class Bib(object):
    """ An Alma Bib record """

    def __init__(self, alma, doc):
        self.alma = alma
        self.init_from_doc(doc)

    def init_from_doc(self, doc):
        self.doc = doc
        self.mms_id = self.doc.findtext('mms_id')
        self.marc_record = Record(self.doc.find('record'))
        self.linked_to_cz = self.doc.findtext('linked_record_id[@type="CZ"]') or None

    def save(self):
        # Save record back to Alma
        try:
            response = self.alma.put('/bibs/{}'.format(self.mms_id),
                                     data=etree.tostring(self.doc),
                                     headers={'Content-Type': 'application/xml'})
        except HTTPError as error:
            raise BibSaveError('Failed to save record. Status: %s. Response: %s'
                               % (error.response.status_code, error.response.text))

        self.init_from_doc(parse_xml(response))

    def dump(self, filename):
        # Dump record to file
        with open(filename, 'wb') as f:
            f.write(etree.tostring(self.doc, pretty_print=True))
