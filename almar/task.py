# coding=utf-8
from __future__ import unicode_literals, print_function
import logging
from collections import OrderedDict
import six
from colorama import Fore, Back, Style
from six import python_2_unicode_compatible
from copy import deepcopy
import time
from .concept import Concept
from .util import ANY_VALUE, normalize_term, pick

log = logging.getLogger(__name__)


class Task(object):
    """
    Task class from which the other task classes inherit.
    """

    def match_field(self, field):
        return field.match(self.source, self.ignore_extra_subfields)

    def match_record(self, marc_record):
        return marc_record.match(self.source, self.ignore_extra_subfields)

    def run(self, marc_record):
        log.debug('Run task: %s', self)
        modified = self._run(marc_record)
        if modified > 0:
            log.debug('Modifications made: %d', modified)
        return modified


@python_2_unicode_compatible
class ReplaceTask(Task):
    """
    Replace a subject access or classification number field with another one in
    any given MARC record.
    """

    def __init__(self, source, target, ignore_extra_subfields=False):
        self.source = deepcopy(source)
        self.target = deepcopy(target)
        self.source.set_a_or_x_to('a')
        self.target.set_a_or_x_to('a')
        self.ignore_extra_subfields = ignore_extra_subfields

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
class InteractiveReplaceTask(Task):
    """
    Replace a subject access or classification number field with another one
    (from a selection) in any given MARC record.

    Note: Exact matching only – will not replace fields having any additional
          subfields $b, $x, $y or $z. A search for "Fish" will not match the
          field "$a Fish $x Behaviour".
    """

    def __init__(self, source, targets, ignore_extra_subfields=False):
        self.source = deepcopy(source)
        self.source.set_a_or_x_to('a')
        self.targets = deepcopy(targets)
        for target in self.targets:
            target.set_a_or_x_to('a')
        self.ignore_extra_subfields = ignore_extra_subfields

    def _run(self, marc_record):
        print()
        time.sleep(1)
        print('{}{}: {}{}'.format(Fore.WHITE, marc_record.id, marc_record.title(), Style.RESET_ALL).encode('utf-8'))
        for field in marc_record.fields:
            if field.tag.startswith('6'):
                if field.sf('2') == self.source.sf['2']:
                    if field.match(self.source):
                        print('  > {}{}{}'.format(Fore.YELLOW, field, Style.RESET_ALL).encode('utf-8'))
                    else:
                        print('    {}{}{}'.format(Fore.YELLOW, field, Style.RESET_ALL).encode('utf-8'))
                else:
                    print('    {}'.format(field).encode('utf-8'))

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
            tasks.append(DeleteTask(self.source, ignore_extra_subfields=self.ignore_extra_subfields))
        else:
            tasks.append(ReplaceTask(self.source, targets[0], ignore_extra_subfields=self.ignore_extra_subfields))
            for target in targets[1:]:
                tasks.append(AddTask(target))

        modified = 0
        for task in tasks:
            modified += task.run(marc_record)

        return modified

    def __str__(self):
        return 'Interactive replace'


@python_2_unicode_compatible
class ListTask(Task):
    """
    Do nothing except test if the MARC record contains the requested
    subject access or classification number field.

    Note: Exact matching only – will not replace fields having any additional
          subfields $b, $x, $y or $z. A search for "Fish" will not match the
          field "$a Fish $x Behaviour".
    """

    def __init__(self, source, show_titles=False, show_subjects=False, ignore_extra_subfields=True):
        self.source = deepcopy(source)
        self.source.set_a_or_x_to('a')
        self.ignore_extra_subfields = ignore_extra_subfields

        self.show_titles = show_titles
        self.show_subjects = show_subjects

    def __str__(self):
        return 'List titles having `{}`'.format(Fore.WHITE + six.text_type(self.source) + Style.RESET_ALL)

    def _run(self, marc_record):
        if self.show_titles:
            print('{}\t{}'.format(marc_record.id, marc_record.title()).encode('utf-8'))
        else:
            print(marc_record.id.encode('utf-8'))

        if self.show_subjects:
            for field in marc_record.fields:
                if field.tag.startswith('6'):
                    if field.sf('2') == self.source.sf['2']:
                        print('  {}{}{}'.format(Fore.YELLOW, field, Style.RESET_ALL).encode('utf-8'))
                    else:
                        print('  {}{}{}'.format(Fore.CYAN, field, Style.RESET_ALL).encode('utf-8'))

        return 0  # No, we didn't modify anything


@python_2_unicode_compatible
class DeleteTask(Task):
    """
    Delete a subject access or classification number field from any given MARC record.
    """

    def __init__(self, source, ignore_extra_subfields=False):
        self.source = deepcopy(source)
        self.source.set_a_or_x_to('a')
        self.ignore_extra_subfields = ignore_extra_subfields

    def __str__(self):
        return 'Delete `{}`'.format(Fore.WHITE + six.text_type(self.source) + Style.RESET_ALL)

    def _run(self, marc_record):
        removed = 0
        for field in marc_record.search(self.source, self.ignore_extra_subfields):
            marc_record.remove_field(field)
            removed += 1

        return removed
        # Open question: should we also remove strings where sf['a'] is a component???


@python_2_unicode_compatible
class AddTask(Task):
    """
    Add a new subject access or classification number field to any given MARC record.
    """

    def __init__(self, target):
        self.source = None
        self.target = deepcopy(target)
        self.target.set_a_or_x_to('a')

    def __str__(self):
        return 'Add `{}`'.format(Fore.WHITE + six.text_type(self.target) + Style.RESET_ALL)

    def match_field(self, field):
        return False  # This task will only be run if some other task matches the record.

    def match_record(self, marc_record):
        return False  # This task will only be run if some other task matches the record.

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

        marc_record.remove_duplicates(self.target)

        return 1
