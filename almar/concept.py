# coding=utf-8
from __future__ import unicode_literals
import logging
from copy import copy, deepcopy
from six import python_2_unicode_compatible
from colorama import Fore, Back, Style

log = logging.getLogger(__name__)


@python_2_unicode_compatible
class Concept(object):
    def __init__(self, term, vocabulary, tag='650'):
        self.vocabulary = vocabulary
        self.tag = tag
        # self.term = term
        components = term.split(' : ')
        self.sf = {
            'a': components[0],
            'b': None,
            'x': None,
            'y': None,
            'z': None,
            '0': None,
            '2': vocabulary.marc_code,
        }
        if len(components) > 1:
            self.sf['x'] = components[1]
        if len(components) > 2:
            raise RuntimeError('Strings with more than two components are not supported')

    def __copy__(self):
        concept = Concept(self.term, self.vocabulary, self.tag)
        concept.sf = copy(self.sf)  # to include $0 and any other subfields not part of the term
        return concept

    def __deepcopy__(self, memodict):
        concept = Concept(self.term, deepcopy(self.vocabulary), self.tag)
        concept.sf = copy(self.sf)  # to include $0 and any other subfields not part of the term
        return concept

    @property
    def components(self):
        return [value for key, value in self.sf.items() if key in ['a', 'b', 'x', 'y', 'z'] and value is not None]

    @property
    def term(self):
        return ' : '.join(self.components)

    def __str__(self):
        return ' '.join(['${} {}'.format(key, self.sf[key]) for key in ['a', 'x', '0'] if self.sf[key] is not None])

    def authorize(self):
        concept_id = self.vocabulary.authorize_term(self.term, self.tag)
        if concept_id is not None:
            self.sf['0'] = self.vocabulary.marc_prefix + concept_id
            log.info(Fore.GREEN + '✔' + Style.RESET_ALL + ' Authorized:     %s %s', self.tag, self)
        else:
            log.info(Fore.RED + '✘' + Style.RESET_ALL   + ' Not authorized: %s %s', self.tag, self)

    def field(self):
        return {'tag': self.tag, 'sf': self.sf}
