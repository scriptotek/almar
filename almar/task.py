# coding=utf-8
from __future__ import unicode_literals, print_function
import logging
from collections import OrderedDict

import six
from colorama import Fore, Back, Style
from future.utils import python_2_unicode_compatible
from lxml import etree

from .concept import Concept
from .util import parse_xml, ANY_VALUE, normalize_term

log = logging.getLogger(__name__)


def pick(options, alpha_options=None):
    valid = OrderedDict()
    for i, option in enumerate(options):
        valid[str(i + 1)] = option
    for option in alpha_options or []:
        valid[option[0].upper()] = option

    print()
    print('Options:')
    for k, v in valid.items():
        print('  [{}] {}'.format(k, v))

    while True:
        print()
        answer = six.moves.input('Choice: ').upper()
        if answer in valid:
            break
        print('Please choose from the following: {}'.format(', '.join(valid)))
        print('To exit, press Ctrl-C')

    return valid[answer]


class Task(object):
    """
    Task class from which the other task classes inherit.
    """

    def __init__(self, source, targets=None):
        targets = targets or []
        assert isinstance(source, Concept)
        assert isinstance(targets, list)
        for target in targets:
            assert isinstance(target, Concept)
        self.source = source
        self.targets = targets

    def make_query(self, target=None):
        query = OrderedDict([
            ('2', {'search': self.source.sf['2']})
        ])
        for code in ['a', 'b', 'x', 'y', 'z']:
            query[code] = {'search': self.source.sf.get(code)}
            if target is not None:
                query[code]['replace'] = target.sf.get(code)

        if target is not None and target.sf.get('0') is not None:
            query['0'] = {'search': ANY_VALUE, 'replace': target.sf.get('0')}

        return query

    def match(self, marc_record):
        query = self.make_query()

        return len(marc_record.fields(self.source.tag, query)) != 0

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
        for key, value in query.items():
            if value is None:
                query2[key] = None
            elif six.text_type(value) == value:
                query2[key] = value
            elif 'replace' in value:
                query2[key] = value['replace']
            else:
                query2[key] = value['search']

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

    def __init__(self, source, target, ignore_extra_components=False):
        super(ReplaceTask, self).__init__(source, [target])
        self.ignore_extra_components = ignore_extra_components

    def make_component_query(self, target=None):
        """
        Match the defined subfields of the source concept (like $a), while
        ignoring any additional subfields (like $x).
        """
        query = OrderedDict([
            ('2', {'search': self.source.sf.get('2')})
        ])
        for code in ['a', 'b', 'x', 'y', 'z']:
            if self.source.sf.get(code) is not None:
                query[code] = {'search': self.source.sf.get(code)}
                if target is not None:
                    query[code]['replace'] = target.sf.get(code)

        return query

    def __str__(self):
        sources = []
        targets = []
        for key, value in self.make_query(self.targets[0]).items():
            if key != '2':
                if value.get('search') is not None:
                    sources.append('${} {}'.format(key, value['search']))
                if value.get('replace') is not None:
                    targets.append('${} {}'.format(key, value['replace']))

        return 'Replace {} with {} in {} $2 {}'.format(' '.join(sources),
                                                       ' '.join(targets),
                                                       self.source.tag,
                                                       self.source.sf.get('2'))

    def match(self, marc_record):
        # If the inexact query matches, we don't need to check the exact one
        if self.ignore_extra_components:
            query = self.make_component_query()
        else:
            query = self.make_query()

        return len(marc_record.fields(self.source.tag, query)) != 0

    def run(self, marc_record):
        modified = 0
        queries = [self.make_query(self.targets[0])]
        if self.ignore_extra_components:
            queries.append(self.make_component_query(self.targets[0]))
        for query in queries:
            for field in marc_record.fields(self.source.tag, query):
                modified += field.update(query)

        self.remove_duplicates(marc_record, self.source.tag, self.make_query(self.targets[0]))

        return modified


@python_2_unicode_compatible
class InteractiveReplaceTask(Task):
    """
    Replace a subject access or classification number field with another one
    (from a selection) in any given MARC record.

    Note: Exact matching only – will not replace fields having any additional
          subfields $b, $x, $y or $z. A search for "Fish" will not match the
          field "$a Fish $x Behaviour".
    """

    def run(self, marc_record):
        modified = 0

        print()
        print('{}{}: {}{}'.format(Fore.WHITE, marc_record.id, marc_record.title(), Style.RESET_ALL))
        for field in marc_record.fields(self.source.tag, {}):
            if field.subfield_text('2') == self.source.sf['2']:
                if field.match(self.make_query()):
                    print('  {}{}{}'.format(Back.YELLOW + Fore.BLACK, field, Style.RESET_ALL))
                else:
                    print('  {}{}{}'.format(Fore.YELLOW, field, Style.RESET_ALL))
            else:
                print('  {}{}{}'.format(Fore.CYAN, field, Style.RESET_ALL))

        target = pick(self.targets, ['Remove subject', 'Skip (leave as-is)'])

        if target == 'Skip (leave as-is)':
            log.info('Skipping this record')
            return 0

        if target == 'Remove subject':
            log.info('Removing term from record')
            task = DeleteTask(self.source)
            return task.run(marc_record)

        if self.source.tag != target.tag:
            raise RuntimeError('Sorry, interactive mode does not support moving to a different tag.')

        for query in [self.make_query(target)]:
            for field in marc_record.fields(self.source.tag, query):
                log.info('Setting new value: %s', target)
                modified += field.update(query)

        self.remove_duplicates(marc_record, self.source.tag,
                               self.make_query(target))

        return modified


@python_2_unicode_compatible
class ListTask(Task):
    """
    Do nothing except test if the MARC record contains the requested
    subject access or classification number field.

    Note: Exact matching only – will not replace fields having any additional
          subfields $b, $x, $y or $z. A search for "Fish" will not match the
          field "$a Fish $x Behaviour".
    """

    def __init__(self, source, show_titles=False, show_subjects=False):
        super(ListTask, self).__init__(source)
        self.show_titles = show_titles
        self.show_subjects = show_subjects

    def __str__(self):
        return 'List titles having {} {} $2 {}'.format(self.source.tag, self.source, self.source.sf['2'])

    def run(self, marc_record):
        if self.show_titles:
            print('%s\t%s' % (marc_record.id, marc_record.title()))
        else:
            print(marc_record.id)

        if self.show_subjects:
            for field in marc_record.fields(self.source.tag, {}):
                print(field)
            print()

        return 0


@python_2_unicode_compatible
class DeleteTask(Task):
    """
    Delete a subject access or classification number field from any given MARC record.
    """

    def __str__(self):
        return 'Delete {} {} $2 {}'.format(self.source.tag, self.source, self.source.sf['2'])

    def run(self, marc_record):
        query = self.make_query()
        removed = 0
        for field in marc_record.fields(self.source.tag, query):
            marc_record.remove_field(field)
            removed += 1

        return removed
        # Open question: should we also remove strings where sf['a'] is a component???


@python_2_unicode_compatible
class AddTask(Task):
    """
    Add a new subject access or classification number field to any given MARC record.
    """

    def __str__(self):
        return 'Add {} {} $2 {}'.format(self.source.tag, self.source, self.source.sf['2'])

    def match(self, marc_record):
        return False  # This task will only be run if some other task matches the record.

    def run(self, marc_record):
        new_field = parse_xml("""
            <datafield tag="{tag}" ind1=" " ind2="7">
                <subfield code="a">{term}</subfield>
                <subfield code="2">{vocabulary}</subfield>
            </datafield>
        """.format(term=self.source.sf['a'], tag=self.source.tag, vocabulary=self.source.sf['2']))

        if self.source.sf.get('0') is not None:
            el = etree.Element('subfield', code="0")
            el.text = self.source.sf['0']
            new_field.append(el)

        if self.source.sf.get('x') is not None:
            el = etree.Element('subfield', code="x")
            el.text = self.source.sf['x']
            new_field.append(el)

        existing_subjects = marc_record.fields(self.source.tag, {
            '2': {'search': self.source.sf['2']},
        })
        if len(existing_subjects) > 0:
            idx = marc_record.el.index(existing_subjects[-1].node)
            marc_record.el.insert(idx + 1, new_field)
        else:
            marc_record.el.append(new_field)

        self.remove_duplicates(marc_record, self.source.tag, {
            '2': self.source.sf.get('2'),
            'a': self.source.sf.get('a'),
            'x': self.source.sf.get('x'),
        })

        return 1


@python_2_unicode_compatible
class MoveTask(Task):
    """
    Move a subject access or classification number field to another MARC tag
    (e.g. from 650 to 648) in any given MARC record.
    """

    def __init__(self, source, dest_tag):
        super(MoveTask, self).__init__(source)
        self.dest_tag = dest_tag

    def __str__(self):
        term = '$a {}'.format(self.source.sf.get('a'))
        if self.source.sf.get('x') is not None:
            term += ' $x {}'.format(self.source.sf.get('x'))
        return 'Move {} {} $2 {} to {}'.format(self.source.tag, term, self.source.sf.get('2'), self.dest_tag)

    def run(self, marc_record):
        query = self.make_query()

        moved = 0
        for field in marc_record.fields(self.source.tag, query):
            field.set_tag(self.dest_tag)
            moved += 1

        self.remove_duplicates(marc_record, self.dest_tag, query)

        return moved
