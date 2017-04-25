# coding=utf-8
from __future__ import unicode_literals
from future.utils import python_2_unicode_compatible
from collections import OrderedDict
import logging
import six
from lxml import etree

from .util import parse_xml, ANY_VALUE, normalize_term

log = logging.getLogger(__name__)


class Task(object):
    """
    Task class from which the other task classes inherit.
    """

    @staticmethod
    def get_simple_subject_repr(field, subfields='abxyz'):
        subfields = list(subfields)
        key = [field.node.get('tag')]
        for subfield in field.node.findall('subfield'):
            if subfield.get('code') in subfields:
                key.append('$%s %s' % (subfield.get('code'), normalize_term(subfield.text)))

        return ' '.join(key)

    def remove_duplicates(self, marc_record, tag, query):
        dups = 0
        keys = []

        query2 = {}
        for k, v in query.items():
            if v is None:
                query2[k] = None
            elif six.text_type(v) == v:
                query2[k] = v
            elif 'replace' in v:
                query2[k] = v['replace']
            else:
                query2[k] = v['search']

        for field in marc_record.fields(tag, query2):
            key = self.get_simple_subject_repr(field)
            if key in keys:
                marc_record.remove_field(field)
                log.info('Term was already present on the record: %s', key)
                dups += 1
                continue
            keys.append(key)

        return dups


@python_2_unicode_compatible
class ReplaceTask(Task):
    """
    Replace a subject access or classification number field with another one in
    any given MARC record.
    """

    def __init__(self, tag, sf_2, sfs, identifier=None):
        self.tag = tag
        self.sf_2 = sf_2
        self.base_query = sfs
        self.identifier = identifier

    def make_query(self, exact):
        query = OrderedDict([
            ('2', {'search': self.sf_2})
        ])
        if exact:
            query.update({
                'a': {'search': None},
                'b': {'search': None},
                'x': {'search': None},
                'y': {'search': None},
                'z': {'search': None},
            })

        query.update(self.base_query)

        if exact and self.identifier is not None:
            query['0'] = {'search': ANY_VALUE, 'replace': self.identifier}
        return query

    def __str__(self):
        s = []
        t = []
        for k, v in self.base_query.items():
            if v['search'] is not None:
                s.append('${} {}'.format(k, v['search']))
            if v['replace'] is not None:
                t.append('${} {}'.format(k, v['replace']))

        return 'Replace {} with {} in {} $2 {}'.format(' '.join(s),
                                                       ' '.join(t),
                                                       self.tag,
                                                       self.sf_2)

    def match(self, marc_record):
        # If the inexact query matches, we don't need to check the exact one
        return len(marc_record.fields(self.tag, self.make_query(False))) != 0

    def run(self, marc_record):
        modified = 0
        for query in [self.make_query(True), self.make_query(False)]:
            for field in marc_record.fields(self.tag, query):
                modified += field.update(query)

        self.remove_duplicates(marc_record, self.tag, self.make_query(False))

        return modified


@python_2_unicode_compatible
class DeleteTask(Task):
    """
    Delete a subject access or classification number field from any given MARC record.
    """

    def __init__(self, concept):
        self.concept = concept
        self.query = OrderedDict([
            ('2', {'search': self.concept.sf['2']}),
            ('a', {'search': self.concept.sf['a']}),
            ('b', {'search': None}),
            ('x', {'search': self.concept.sf['x']}),
            ('y', {'search': None}),
            ('z', {'search': None}),
        ])

    def __str__(self):
        return 'Delete {} {} $2 {}'.format(self.concept.tag, self.concept, self.concept.sf['2'])

    def match(self, marc_record):
        return len(marc_record.fields(self.concept.tag, self.query)) != 0

    def run(self, marc_record):
        removed = 0
        for field in marc_record.fields(self.concept.tag, self.query):
            marc_record.remove_field(field)
            removed += 1

        return removed
        # Open question: should we also remove strings where sf['a'] is a component???


@python_2_unicode_compatible
class AddTask(Task):
    """
    Add a new subject access or classification number field to any given MARC record.
    """

    def __init__(self, concept):
        self.concept = concept

    def __str__(self):
        return 'Add {} {} $2 {}'.format(self.concept.tag, self.concept, self.concept.sf['2'])

    def match(self, marc_record):
        return False  # This task will only be run if some other task matches the record.

    def run(self, marc_record):
        new_field = parse_xml("""
            <datafield tag="{tag}" ind1=" " ind2="7">
                <subfield code="a">{term}</subfield>
                <subfield code="2">{vocabulary}</subfield>
            </datafield>
        """.format(term=self.concept.sf['a'], tag=self.concept.tag, vocabulary=self.concept.sf['2']))

        if self.concept.sf.get('0') is not None:
            el = etree.Element('subfield', code="0")
            el.text = self.concept.sf['0']
            new_field.append(el)

        if self.concept.sf.get('x') is not None:
            el = etree.Element('subfield', code="x")
            el.text = self.concept.sf['x']
            new_field.append(el)

        existing_subjects = marc_record.fields(self.concept.tag, {
            '2': {'search': self.concept.sf['2']},
        })
        if len(existing_subjects) > 0:
            idx = marc_record.el.index(existing_subjects[-1].node)
            marc_record.el.insert(idx + 1, new_field)
        else:
            marc_record.el.append(new_field)

        self.remove_duplicates(marc_record, self.concept.tag, {
            '2': self.concept.sf.get('2'),
            'a': self.concept.sf.get('a'),
            'x': self.concept.sf.get('x'),
        })

        return 1


@python_2_unicode_compatible
class MoveTask(Task):
    """
    Move a subject access or classification number field to another MARC tag
    (e.g. from 650 to 648) in any given MARC record.
    """

    def __init__(self, tag, sf_2, sfs, dest_tag):
        self.tag = tag
        self.sf_2 = sf_2
        self.sfs = sfs
        self.dest_tag = dest_tag
        self.query = OrderedDict([
            ('2', {'search': self.sf_2}),
            ('a', {'search': self.sfs.get('a')}),
            ('b', {'search': None}),
            ('x', {'search': self.sfs.get('x')}),
            ('y', {'search': None}),
            ('z', {'search': None}),
        ])

    def __str__(self):
        term = '$a {}'.format(self.sfs.get('a'))
        if self.sfs.get('x') is not None:
            term += ' $x {}'.format(self.sfs.get('x'))
        return 'Move {} {} $2 {} to {}'.format(self.tag, term, self.sf_2, self.dest_tag)

    def match(self, marc_record):
        return len(marc_record.fields(self.tag, self.query)) != 0

    def run(self, marc_record):
        moved = 0
        for field in marc_record.fields(self.tag, self.query):
            field.set_tag(self.dest_tag)
            moved += 1

        self.remove_duplicates(marc_record, self.dest_tag, self.query)

        return moved
