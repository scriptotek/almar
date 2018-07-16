# coding=utf-8

from __future__ import unicode_literals

from .marc import Record
from .util import etree, parse_xml


class Bib(object):
    """ An Alma Bib record """

    def __init__(self, xml):
        self.orig_xml = xml
        self.init(xml)

    def init(self, xml):
        self.doc = parse_xml(xml)
        self.id = self.doc.findtext('mms_id')
        self.marc_record = Record(self.doc.find('record'))
        self.cz_link = self.doc.findtext('linked_record_id[@type="CZ"]') or None

    def xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n%s' %
            etree.tounicode(self.doc)
        )

    def dump(self, filename):
        # Dump record to file
        with open(filename, 'wb') as file:
            file.write(etree.tostring(self.doc, pretty_print=True))
