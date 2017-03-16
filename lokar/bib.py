# coding=utf-8

from __future__ import unicode_literals

from requests.exceptions import HTTPError
import six

from .marc import Record
from .util import etree, parse_xml


@six.python_2_unicode_compatible
class BibSaveError(RuntimeError):

    def __init__(self, response, request):
        self.msg = 'Failed to save record'
        self.response = response
        self.request = request

    def __str__(self):
        args = (self.response.status_code, self.response.text, self.request)
        return 'Failed to save record, status: %s\n\n%s\n\n%s' % args


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
            raise BibSaveError(error.response, etree.tostring(self.doc))

        self.init_from_doc(parse_xml(response))

    def dump(self, filename):
        # Dump record to file
        with open(filename, 'wb') as f:
            f.write(etree.tostring(self.doc, pretty_print=True))
