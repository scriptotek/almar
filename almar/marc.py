# coding=utf-8
from __future__ import unicode_literals

import warnings
import logging
from collections import OrderedDict
from copy import deepcopy

from six import python_2_unicode_compatible

from .util import term_match, parse_xml, ANY_VALUE

log = logging.getLogger(__name__)


def deprecated(func):
    '''This is a decorator which can be used to mark functions
    as deprecated. It will result in a warning being emitted
    when the function is used.'''
    def new_func(*args, **kwargs):
        warnings.warn("Call to deprecated function {}.".format(func.__name__),
                      category=DeprecationWarning)
        return func(*args, **kwargs)
    new_func.__name__ = func.__name__
    new_func.__doc__ = func.__doc__
    new_func.__dict__.update(func.__dict__)

    return new_func


@python_2_unicode_compatible
class Subfield(object):
    """ A Marc21 subfield """
    def __init__(self, node):
        self.node = node

    @property
    def code(self):
        return self.node.get('code')

    @property
    def text(self):
        return self.node.text

    @text.setter
    def text(self, value):
        self.node.text = value

    def __str__(self):
        return self.text

    # def __cmp__(self, other):
    #     if self.code != other.code:
    #         return False

    #     if self.value == ANY_VALUE or other.value == ANY_VALUE
    #         return True

    #     and self.value == other.value


@python_2_unicode_compatible
class Field(object):
    """ A Marc21 field """

    def __init__(self, node):
        self.node = node

    @property
    def tag(self):
        return self.node.get('tag')

    @property
    def ind1(self):
        return self.node.get('ind1')

    @property
    def ind2(self):
        return self.node.get('ind2')

    def __str__(self):
        items = [self.tag, self.ind1.replace(' ', '#') + self.ind2.replace(' ', '#')]
        for subfield in self.node:
            items.append('$%s %s' % (subfield.attrib['code'], subfield.text))
        return ' '.join(items)

    @property
    def subfields(self):
        return self.get_subfields()

    def get_subfields(self, source_code=None):
        for node in self.node.findall('subfield'):
            if source_code is None or source_code == node.get('code'):
                yield Subfield(node)

    def sf(self, code=None):
        # return text of first matching subfield or None
        for node in self.get_subfields(code):
            return node.text

    @deprecated  # use sf instead
    def subfield_text(self, code):
        return self.sf(code)

    def set_tag(self, value):
        if self.node.get('tag') != value:
            log.debug('CHANGE: Set tag to %s in `%s`', value, self)
            self.node.set('tag', value)
            return 1
        return 0

    def set_ind1(self, value):
        if value is not None and value != '?' and self.node.get('ind1') != value:
            log.debug('CHANGE: Set ind1 to %s in `%s`', value, self)
            self.node.set('ind1', value)
            return 1
        return 0

    def set_ind2(self, value):
        if value is not None and value != '?' and self.node.get('ind2') != value:
            log.debug('CHANGE: Set ind2 to %s in `%s`', value, self)
            self.node.set('ind2', value)
            return 1
        return 0

    def match(self, concept, ignore_extra_subfields=False):
        """
        Return True if 'field' matches this concept
        """

        if not self.tag.startswith(concept.tag):
            return False

        if concept.ind1 != '?' and self.ind1 != concept.ind1:
            return False

        if concept.ind2 != '?' and self.ind2 != concept.ind2:
            return False

        for code, sf_value in concept.sf.items():
            if sf_value != ANY_VALUE and not term_match(sf_value, self.sf(code)):
                return False

        if not ignore_extra_subfields:
            for subfield in self.subfields:
                if subfield.code not in concept.sf and subfield.code not in ['0', '9']:
                    return False

        return True

    def replace(self, source, target):
        """
        Replace field with target
        """

        modified = 0

        modified += self.set_tag(target.tag)
        modified += self.set_ind1(target.ind1)
        modified += self.set_ind2(target.ind2)
        modified += self.update_subfields(source, target)

        return modified

    def update_subfields(self, source, target):
        modified = 0
        idx = 0

        for code, target_value in target.sf.items():
            source_value = source.sf.get(code)
            found_subfield = False

            for subfield in self.get_subfields(code):
                if term_match(source_value, subfield.text):
                    found_subfield = True
                    idx = self.node.index(subfield.node) + 1

                    if target_value is None:  # NoValue
                        # Subfield should be removed
                        log.debug('CHANGE: Removing `$%s %s` from `%s`', code, subfield.text, self)
                        self.node.remove(subfield.node)
                        modified += 1

                    elif subfield.text != target_value:
                        # Subfield value should be updated
                        log.debug('CHANGE: Changing $%s from "%s" to "%s" in `%s`',
                                  code, subfield.text, target_value, self)
                        subfield.text = target_value
                        modified += 1

            if not found_subfield and target_value is not None:
                # Add subfield
                log.debug('CHANGE: Adding `$%s %s` to `%s`', code, target_value, self)
                self.node.insert(idx,
                                 parse_xml('<subfield code="%s">%s</subfield>' % (code, target_value))
                                 )
                modified += 1

        return modified


class Record(object):
    """ A Marc21 record """

    def __init__(self, el):
        # el: xml.etree.ElementTree.Element
        self.el = el

    @property
    def id(self):
        return self.el.findtext('./controlfield[@tag="001"]')

    @property
    def fields(self):
        return self.get_fields()

    def get_fields(self):
        for node in self.el.findall('datafield'):
            yield Field(node)

    def match(self, concept, ignore_extra_subfields=False):
        matches = list(self.search(concept, ignore_extra_subfields))
        return len(matches) != 0

    def search(self, concept, ignore_extra_subfields=False):
        """
        Return fields matching the Concept
        """
        for field in self.fields:
            if field.match(concept, ignore_extra_subfields):
                yield field

    def remove_duplicates(self, concept, ignore_extra_subfields=False):
        concept = deepcopy(concept)

        concept.sf['0'] = ANY_VALUE

        dups = 0
        candidates = {}

        # query2 = {}
        # for key, value in query.items():
        #     if value is None:
        #         query2[key] = None
        #     elif six.text_type(value) == value:
        #         query2[key] = value
        #     elif 'replace' in value:
        #         query2[key] = value['replace']
        #     else:
        #         query2[key] = value['search']

        matches = list(self.search(concept, ignore_extra_subfields))
        if len(matches) > 1:
            # Sort fields with $0 first, since we prefer to keep those
            matches = sorted(matches, key=lambda x: x.sf('0') or '', reverse=True)
            for match in matches[1:]:
                log.info('Target subject already existed on the record, ignoring duplicate: %s', match)
                self.remove_field(match)
                dups += 1

        return dups

    def remove_field(self, field):
        # field: Field
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
