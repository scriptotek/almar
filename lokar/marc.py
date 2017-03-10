
# coding=utf-8
from __future__ import unicode_literals
import logging
from copy import deepcopy
from .util import normalize_term, term_match, parse_xml
from colorama import Fore, Back, Style

log = logging.getLogger(__name__)


class Subjects(object):

    def __init__(self, marc_record):
        self.marc_record = marc_record

    @staticmethod
    def make_query(vocabulary, term=None, replacement_term=None):
        if term is None:
            term = []
        else:
            term = term.split(' : ')

        if replacement_term is not None:
            replacement_term = replacement_term.split(' : ')

        if len(term) > 2:
            raise RuntimeError('Strings with more than two components are not yet supported' +
                               'Got string with %d components.' % (len(term)))

        if len(term) == 2:
            if replacement_term is None:
                yield {
                    '2': {'search': vocabulary},
                    'a': {'search': term[0]},
                    'x': {'search': term[1]},
                }
            elif len(replacement_term) == 2:
                # Replace `$a : $x` by `$a : $x`
                yield {
                    '2': {'search': vocabulary},
                    'a': {'search': term[0], 'replace': replacement_term[0]},
                    'x': {'search': term[1], 'replace': replacement_term[1]},
                }
            elif len(replacement_term) == 1:
                # Replace `$a : $x` by `$a`
                yield {
                    '2': {'search': vocabulary},
                    'a': {'search': term[0], 'replace': replacement_term[0]},
                    'x': {'search': term[1], 'replace': None},
                }

        elif len(term) == 1:
            if replacement_term is None:
                for code in ['a', 'x']:
                    yield {
                        '2': {'search': vocabulary},
                        code: {'search': term[0]},
                    }
            elif len(replacement_term) == 1:
                # Replace `$a` by `$a` or `$x` by `$x`
                for code in ['a', 'x']:
                    yield {
                        '2': {'search': vocabulary},
                        code: {'search': term[0], 'replace': replacement_term[0]},
                    }
            elif len(replacement_term) == 2:
                # Replace `$a` by `$a : $x`
                yield {
                    '2': {'search': vocabulary},
                    'a': {'search': term[0], 'replace': replacement_term[0]},
                    'x': {'search': None, 'replace': replacement_term[1]}
                }
        elif len(term) == 0:
            yield {
                '2': {'search': vocabulary},
            }

    def query(self, vocabulary, search_term, replacement_term=None, tags=None):
        tags = tags or '650'
        for query in self.make_query(vocabulary, search_term, replacement_term):
            for field in self.marc_record.fields(tags, query):
                yield field

    def find(self, vocabulary, term=None, tags=None):
        for field in self.query(vocabulary, term, tags=tags):
            yield field

    def rename(self, vocabulary, old_term, new_term=None, tags=None):
        tags = tags or '650'
        for query in self.make_query(vocabulary, old_term, new_term):
            for field in self.marc_record.fields(tags, query):
                field.update(query)

        self.remove_duplicates(vocabulary, new_term, tags)

    def remove(self, vocabulary, term, tags=None):
        tags = tags or '650'
        term = term.split(' : ')

        query = {
            '2': {'search': vocabulary},
            'a': {'search': term[0]},
            'b': {'search': None},
            'x': {'search': None},
            'y': {'search': None},
            'z': {'search': None},
        }
        if len(term) == 2:
            query['x']['search'] = term[1]

        for field in self.marc_record.fields(tags, query):
            self.marc_record.remove_field(field)

    def move(self, vocabulary, term, source_tag, dest_tag):
        if len(term.split(' : ')) > 1:
            raise RuntimeError('Moving of strings is not yet supported')

        query = {
            '2': {'search': vocabulary},
            'a': {'search': term},
            'b': {'search': None},
            'x': {'search': None},
            'y': {'search': None},
            'z': {'search': None},
        }

        for field in self.marc_record.fields(source_tag, query):
            print('Setting', query, term, source_tag, dest_tag)
            field.set_tag(dest_tag)

        self.remove_duplicates(vocabulary, term, dest_tag)

    @staticmethod
    def get_simple_subject_repr(field, subfields='abxyz'):
        subfields = list(subfields)
        key = [field.node.get('tag')]
        for subfield in field.node.findall('subfield'):
            if subfield.get('code') in subfields:
                key.append('$%s %s' % (subfield.get('code'), subfield.text))
        return ' '.join(key)

    def remove_duplicates(self, vocabulary, term, tags=None):
        keys = []

        for field in self.find(vocabulary, term, tags):
            key = self.get_simple_subject_repr(field)
            if key in keys:
                log.info('Posten hadde allerede termen: %s', key)
                self.marc_record.remove_field(field)
                continue
            keys.append(key)


class Field(object):
    """ A Marc21 field """

    def __init__(self, node):
        self.node = node

    def __str__(self):
        return self.__unicode__().encode('utf-8')

    def __unicode__(self):
        txt = [tag, self.node.attrib['ind1'].replace(' ', '#') + self.node.attrib['ind2'].replace(' ', '#')]
        for sf in self.node:
            txt.append('$%s %s' % (sf.attrib['code'], sf.text))
        txt = '  %s' % ' '.join(txt)
        return txt

    def match(self, subfield_query):
        """
        Return True if all the subfields in the subfield_query match
        the values in the current field.
        """
        for code, value in subfield_query.items():
            if not term_match(self.node.findtext('subfield[@code="{}"]'.format(code)), value['search']):
                return False
        return True

    def update(self, subfield_query):
        """
        Update subfield values based on subfield_query

        Example:

        >>> update({'a': {'search': 'Hello', 'World'}})
        """
        subfield_query = deepcopy(subfield_query)

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
                    else:
                        # Subfield value should be updated
                        log.debug('Changing $%s from "%s" tot "%s"', code, ch.text, x['replace'])
                        ch.text = x['replace']
            for code, value in subfield_query.items():
                if value.get('replace') is not None:
                    print('APPEND', code, value['replace'])
                    self.node.append(parse_xml('<subfield code="%s">%s</subfield>' % (code, value['replace'])))

    def set_tag(self, new_tag):
        self.node.set('tag', new_tag)


class Record(object):
    """ A Marc21 record """

    def __init__(self, el):
        # el: xml.etree.ElementTree.Element
        self.el = el

    def id(self):
        return self.el.findtext('./controlfield[@tag="001"]')

    # TODO: Rename find
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
