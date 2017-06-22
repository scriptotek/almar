# coding=utf-8
from __future__ import unicode_literals
from future.utils import python_2_unicode_compatible

import logging
from copy import deepcopy
from .util import term_match, parse_xml
from colorama import Fore, Back, Style

log = logging.getLogger(__name__)


@python_2_unicode_compatible
class Field(object):
    """ A Marc21 field """

    def __init__(self, node):
        self.node = node

    def __str__(self):
        txt = [self.node.get('tag'),
               self.node.attrib['ind1'].replace(' ', '#') + self.node.attrib['ind2'].replace(' ', '#')]
        for sf in self.node:
            txt.append('$%s %s' % (sf.attrib['code'], sf.text))
        txt = '  %s' % ' '.join(txt)
        return txt

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
            for ch in self.node.findall('subfield'):
                code = ch.attrib.get('code')
                if code in subfield_query.keys() and term_match(subfield_query[code]['search'], ch.text):
                    x = subfield_query[code]
                    del subfield_query[code]
                    if 'replace' not in x:
                        # Just used for search, value should not be updated
                        continue
                    elif x['replace'] is None:
                        # Subfield should be removed
                        log.debug('Removing component $%s %s', code, ch.text)
                        self.node.remove(ch)
                        modified += 1
                    else:
                        # Subfield value should be updated
                        log.debug('Changing $%s from "%s" tot "%s"', code, ch.text, x['replace'])
                        ch.text = x['replace']
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

    def id(self):
        return self.el.findtext('./controlfield[@tag="001"]')

    def fields(self, tags, subfield_query):
        if type(tags) != list:
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
