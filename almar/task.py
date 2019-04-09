# coding=utf-8
from __future__ import unicode_literals
import logging
from collections import OrderedDict
import os
import time
from colorama import Fore, Style
import six
from six import python_2_unicode_compatible
from copy import deepcopy
from .util import pick, utf8print

log = logging.getLogger(__name__)


@python_2_unicode_compatible
class Task(object):
    """
    Task class from which the other task classes inherit.
    """
    def __init__(self):
        self.progress = 0

    def _run(self, marc_record):
        return 0

    def run(self, marc_record, progress=None):
        # log.debug('Run task: %s', self)
        self.progress = progress
        modified = self._run(marc_record)
        return modified


@python_2_unicode_compatible
class SingleSourceConceptTask(Task):

    def __init__(self, source, ignore_extra_subfields):
        super().__init__()
        self.source = deepcopy(source)
        self.ignore_extra_subfields = ignore_extra_subfields

    def match(self, marc_record):
        for field in marc_record.fields:
            if field.tag.startswith('6') and field.match(self.source, self.ignore_extra_subfields):
                return True
        return False


@python_2_unicode_compatible
class MultipleSourceConceptTask(Task):

    def __init__(self, concepts, ignore_extra_subfields):
        super().__init__()
        self.concepts = [deepcopy(concept) for concept in concepts]
        for concept in self.concepts:
            concept.set_a_or_x_to('a')
        self.ignore_extra_subfields = ignore_extra_subfields

    def match_concept(self, marc_record, concept):
        for field in marc_record.fields:
            if field.tag.startswith('6') and field.match(concept, self.ignore_extra_subfields):
                return True
        return False

    def match(self, marc_record):
        for concept in self.concepts:
            if not self.match_concept(marc_record, concept):
                return False
        return True


@python_2_unicode_compatible
class ReplaceTask(SingleSourceConceptTask):
    """
    Replace a subject access or classification number field with another one in
    any given MARC record.
    """

    def __init__(self, source, target, ignore_extra_subfields=False):
        super().__init__(source, ignore_extra_subfields)
        self.target = deepcopy(target)
        self.source.set_a_or_x_to('a')
        self.target.set_a_or_x_to('a')

        """
        Caveat 1:
        If extra subfields are ignored in the matching, we cannot add/update $0,
        since the identifier is connected to the exact subject heading
        (For instance, "$a TermA $b TermB" has a differen $0 than just "$a TermA")
        """
        if self.ignore_extra_subfields:
            if '0' in self.target.sf:
                del self.target.sf['0']

    def __str__(self):
        ign = ' (ignoring any extra subfields)' if self.ignore_extra_subfields else ''

        args = (Fore.WHITE + six.text_type(self.source) + Style.RESET_ALL,
                Fore.WHITE + six.text_type(self.target) + Style.RESET_ALL,
                ign)
        return 'Replace `{}` → `{}`{}'.format(*args)

    def _run(self, marc_record):
        modified = 0

        for field in marc_record.search(self.source, self.ignore_extra_subfields):
            modified += field.replace(self.source, self.target)

        marc_record.remove_duplicates(self.target)

        return modified


@python_2_unicode_compatible
class InteractiveReplaceTask(SingleSourceConceptTask):
    """
    Replace a subject access or classification number field with another one
    (from a selection) in any given MARC record.

    Note: Exact matching only – will not replace fields having any additional
          subfields $b, $x, $y or $z. A search for "Fish" will not match the
          field "$a Fish $x Behaviour".
    """

    def __init__(self, source, targets, ignore_extra_subfields=False):
        super().__init__(source, ignore_extra_subfields)
        self.source.set_a_or_x_to('a')
        self.targets = deepcopy(targets)
        for target in self.targets:
            target.set_a_or_x_to('a')

    def _run(self, marc_record):
        utf8print()
        time.sleep(1)
        os.system('clear')
        if self.progress is not None:
            utf8print('{}[Record {:d} of {:d}]{}'.format(
                Fore.WHITE, self.progress['current'], self.progress['total'], Style.RESET_ALL
            ))
        utf8print('{}{} {}{}'.format(
            Fore.WHITE, marc_record.id, marc_record.title(), Style.RESET_ALL
        ))
        for field in marc_record.fields:
            if field.tag.startswith('6'):
                if field.sf('2') == self.source.sf['2']:
                    if field.match(self.source):
                        utf8print('  > {}{}{}'.format(Fore.YELLOW, field, Style.RESET_ALL))
                    else:
                        utf8print('    {}{}{}'.format(Fore.YELLOW, field, Style.RESET_ALL))
                else:
                    utf8print('    {}'.format(field))

        while True:
            targets = pick('Make a selection (or press Ctrl-C to abort)', self.targets, OrderedDict((
                ('REMOVE', 'None of them (remove the field)'),
            )))
            if 'REMOVE' in targets and len(targets) > 1:
                log.warning('Invalid selection. Please try again or press Ctrl-C to abort.')
            else:
                break

        if len(targets) == 0:
            log.info('Skipping this record')
            return 0

        tasks = []
        if 'REMOVE' in targets:
            tasks.append(DeleteTask([self.source], ignore_extra_subfields=self.ignore_extra_subfields))
        else:
            tasks.append(DeleteTask([self.source], ignore_extra_subfields=self.ignore_extra_subfields))
            for target in targets:
                tasks.append(AddTask(target))

        modified = 0
        for task in tasks:
            modified += task.run(marc_record)

        return modified

    def __str__(self):
        return 'Interactive replace'


@python_2_unicode_compatible
class ListTask(MultipleSourceConceptTask):
    """
    Do nothing except test if the MARC record contains the requested
    subject access or classification number field.

    Note: Exact matching only – will not replace fields having any additional
          subfields $b, $x, $y or $z. A search for "Fish" will not match the
          field "$a Fish $x Behaviour".
    """

    def __init__(self, concepts, show_titles=False, show_subjects=False, ignore_extra_subfields=True):
        super().__init__(concepts, ignore_extra_subfields)

        self.show_titles = show_titles
        self.show_subjects = show_subjects

    def __str__(self):
        return 'List titles having `{}`'.format(
            Fore.WHITE + '` and `'.join([six.text_type(x) for x in self.concepts]) + Style.RESET_ALL
        )

    def _run(self, marc_record):
        # if self.show_titles:
        #     utf8print('{}\t{}'.format(marc_record.id, marc_record.title()))
        # else:
        #     utf8print(marc_record.id)

        if self.show_subjects:
            for field in marc_record.fields:
                if field.tag.startswith('6'):
                    for concept in self.concepts:
                        if field.sf('2') == concept.sf['2']:
                            utf8print('  {}{}{}'.format(Fore.YELLOW, field, Style.RESET_ALL))
                        else:
                            utf8print('  {}{}{}'.format(Fore.CYAN, field, Style.RESET_ALL))

        return 0  # No, we didn't modify anything


@python_2_unicode_compatible
class DeleteTask(MultipleSourceConceptTask):
    """
    Delete one or more subject heading or classification number fields from any given MARC record.
    """

    def __init__(self, concepts, ignore_extra_subfields=False):
        super().__init__(concepts, ignore_extra_subfields)

    def __str__(self):
        return 'Delete ' + ' AND '.join([
            '`{}`'.format(Fore.WHITE + six.text_type(concept) + Style.RESET_ALL) for concept in self.concepts
        ])

    def _run(self, marc_record):
        removed = 0
        for concept in self.concepts:
            for field in marc_record.search(concept, self.ignore_extra_subfields):
                log.debug('Removing field: %s' % field)
                marc_record.remove_field(field)
                removed += 1

        return removed
        # Open question: should we also remove strings where sf['a'] is a component???


@python_2_unicode_compatible
class AddTask(Task):
    """
    Add a new subject access or classification number field to any given MARC record.
    """

    def __init__(self, target, match=False):
        self.target = deepcopy(target)
        self.target.set_a_or_x_to('a')

        # This task will either always match (if run alone)
        # or never match (if appending to another task)
        self._match = match

    def __str__(self):
        return 'Add `{}`'.format(Fore.WHITE + six.text_type(self.target) + Style.RESET_ALL)

    def match(self, marc_record):
        return self._match  # This task will only be run if some other task matches the record.

    def _run(self, marc_record):
        new_field = self.target.as_xml()

        idx = 0
        for field in marc_record.fields:
            try:
                node_tag = int(field.tag)
            except ValueError:  # Alma includes non-numeric tags like 'AVA'
                continue

            if node_tag > int(self.target.tag):
                break
            idx = marc_record.el.index(field.node)

        marc_record.el.insert(idx + 1, new_field)
        log.debug('Inserting field: %s' % self.target)

        marc_record.remove_duplicates(self.target)

        return 1
