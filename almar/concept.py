# coding=utf-8
from __future__ import unicode_literals
import logging
from collections import OrderedDict
from copy import deepcopy
from six import python_2_unicode_compatible
from .util import etree, ANY_VALUE
log = logging.getLogger(__name__)


@python_2_unicode_compatible
class Concept(object):
    def __init__(self, tag, sf, ind1=None, ind2=None):
        if tag is None:
            raise ValueError('No tag given')
        if 'a_or_x' in sf and 'a' in sf:
            raise ValueError('Both a_or_x and a given')
        if 'a_or_x' in sf and 'x' in sf:
            raise ValueError('Both a_or_x and x given')
        self.tag = tag
        self.sf = deepcopy(sf)
        self.ind1 = ind1 or '?'
        self.ind2 = ind2 or '?'

        if self.sf.get('2') is None:
            raise RuntimeError('No vocabulary given')

    def __deepcopy__(self, memodict):
        return Concept(tag=self.tag, sf=self.sf, ind1=self.ind1, ind2=self.ind2)

    def has_subfield(self, code):
        if code in self.sf:
            return True
        if code in ['a', 'x'] and 'a_or_x' in self.sf:
            return True
        if code == 'a_or_x' and ('a' in self.sf or 'x' in self.sf):
            return True
        return False

    @property
    def components(self):
        return [
            value for key, value in self.sf.items()
            if key in ['a_or_x', 'a', 'b', 'x', 'y', 'z'] and value is not None
        ]

    @property
    def term(self):
        return ' : '.join([x for x in self.components if x != ANY_VALUE])

    def __str__(self):
        return self.tag + ' ' + ' '.join([
            '${} {}'.format(key[0], val)
            for key, val in self.sf.items() if val is not None
        ])

    def field(self):
        return {'tag': self.tag, 'sf': self.sf}

    def set_a_or_x_to(self, code):
        def get_key(key):
            if key == 'a_or_x':
                return code
            return key
        self.sf = OrderedDict([
            (get_key(key), val)
            for key, val in self.sf.items()
        ])

    @staticmethod
    def get_default_ind1(tag):
        # TODO: Vary on tag
        return ' '

    @staticmethod
    def get_default_ind2(tag):
        # TODO: Vary on tag
        return '7'

    def as_xml(self):

        if self.ind1 is not None and self.ind1 != '?':
            ind1 = self.ind1
        else:
            ind1 = self.get_default_ind1(self.tag)

        if self.ind2 is not None and self.ind2 != '?':
            ind2 = self.ind2
        else:
            ind2 = self.get_default_ind2(self.tag)

        new_field = etree.Element('datafield', {
            'tag': self.tag,
            'ind1': ind1,
            'ind2': ind2
        })
        for code, value in self.sf.items():
            subel = etree.SubElement(new_field, 'subfield', {'code': code})
            subel.text = value

        return new_field
