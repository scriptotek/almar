# coding=utf-8

from __future__ import unicode_literals

from io import BytesIO

from .marc import Record
from .util import etree, parse_xml, show_diff


class Bib(object):
    """ An Alma Bib record """

    def __init__(self, alma, xml):
        self.alma = alma
        self.orig_xml = xml
        self.init(xml)

    def init(self, xml):
        self.doc = parse_xml(xml)
        self.mms_id = self.doc.findtext('mms_id')
        self.marc_record = Record(self.doc.find('record'))
        self.cz_link = self.doc.findtext('linked_record_id[@type="CZ"]') or None

    def save(self, diff=False, dry_run=False):
        # Save record back to Alma

        post_data = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
                     etree.tounicode(self.doc))

        if diff:
            show_diff(self.orig_xml, post_data)

        if not dry_run:
            response = self.alma.put('/bibs/{}'.format(self.mms_id),
                                     data=BytesIO(post_data.encode('utf-8')),
                                     headers={'Content-Type': 'application/xml'})
            self.init(response)

    def dump(self, filename):
        # Dump record to file
        with open(filename, 'wb') as file:
            file.write(etree.tostring(self.doc, pretty_print=True))