# coding=utf-8
from __future__ import unicode_literals

import logging
from copy import deepcopy

from colorama import Fore, Style
from future.utils import python_2_unicode_compatible

from .util import term_match, parse_xml

log = logging.getLogger(__name__)


@python_2_unicode_compatible
class Field(object):
    """ A Marc21 field """

    def __init__(self, node):
        self.node = node

    def __str__(self):
        items = [self.node.get('tag'),
                 self.node.attrib['ind1'].replace(' ', '#') + self.node.attrib['ind2'].replace(' ', '#')]
        for subfield in self.node:
            items.append('$%s %s' % (subfield.attrib['code'], subfield.text))
        return '  %s' % ' '.join(items)

    def subfield_text(self, code):
        return self.node.findtext('subfield[@code="{}"]'.format(code))

    def match(self, subfield_query):
        """
        Return True if all the subfields in the subfield_query match
        the values in the current field.
        """
        for code, value in subfield_query.items():
            node_text = self.subfield_text(code)
            if isinstance(value, dict):
                if not term_match(node_text, value['search']):
                    return False
            else:
                if not term_match(node_text, value):
                    return False
        return True

    def update(self, subfield_query):
        """
        Update subfield values based on subfield_query

        Example:

        >>> update({'a': {'search': 'Hello', 'World'}})
        """
        subfield_query = deepcopy(subfield_query)
        modified = 0

        if self.match(subfield_query):
            for node in self.node.findall('subfield'):
                code = node.attrib.get('code')
                if code in subfield_query.keys() and term_match(subfield_query[code]['search'], node.text):
                    query_sf = subfield_query[code]
                    del subfield_query[code]
                    if 'replace' not in query_sf:
                        # Just used for search, value should not be updated
                        continue
                    elif query_sf['replace'] is None:
                        # Subfield should be removed
                        log.debug('Removing component $%s %s', code, node.text)
                        self.node.remove(node)
                        modified += 1
                    else:
                        # Subfield value should be updated
                        log.debug('Changing $%s from "%s" tot "%s"', code, node.text, query_sf['replace'])
                        node.text = query_sf['replace']
                        modified += 1
            # Add new subfields
            for code, value in subfield_query.items():
                if value.get('replace') is not None:
                    self.node.append(parse_xml('<subfield code="%s">%s</subfield>' % (code, value['replace'])))
                    modified += 1

        return modified

    def set_tag(self, new_tag):
        self.node.set('tag', new_tag)


class Record(object):
    """ A Marc21 record """

    def __init__(self, el):
        # el: xml.etree.ElementTree.Element
        self.el = el

    @property
    def id(self):
        return self.el.findtext('./controlfield[@tag="001"]')

    def fields(self, tags, subfield_query):
        if isinstance(tags, list) is False:
            tags = [tags]
        fields = []
        for tag in tags:
            for field in self.el.findall('./datafield[@tag="{}"]'.format(tag)):
                field = Field(field)

                if field.match(subfield_query):
                    log.debug('%s%s%s', Fore.GREEN, field, Style.RESET_ALL)
                    fields.append(field)
                else:
                    log.debug('%s%s%s', Fore.RED, field, Style.RESET_ALL)

        return fields

    def remove_field(self, field):
        self.el.remove(field.node)

    def title(self):

        out = self.el.find('./datafield[@tag="245"]/subfield[@code="a"]').text

        node = self.el.find('./datafield[@tag="245"]/subfield[@code="b"]')
        if node is not None:
            out = out.rstrip(' :') + ' : ' + node.text

        node = self.el.find('./datafield[@tag="245"]/subfield[@code="p"]')
        if node is not None:
            out = out.rstrip(' /:.') + '. ' + node.text

        node = self.el.find('./datafield[@tag="245"]/subfield[@code="n"]')
        if node is not None:
            out = out.rstrip(' /:.') + '. ' + node.text

        node = self.el.find('./datafield[@tag="245"]/subfield[@code="c"]')
        if node is not None:
            out = out.rstrip(' /') + ' / ' + node.text

        out = out.rstrip('.') + '.'

        node = self.el.find('./datafield[@tag="264"]/subfield[@code="c"]')
        if node is None:
            node = self.el.find('./datafield[@tag="260"]/subfield[@code="c"]')
            if node is not None:
                out += ' ' + node.text

        return out
