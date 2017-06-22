from copy import copy, deepcopy
from future.utils import python_2_unicode_compatible
import logging

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
        c = Concept(self.term, self.vocabulary, self.tag)
        c.sf = copy(self.sf)  # to include $0 and any other subfields not part of the term
        return c

    def __deepcopy__(self, memodict):
        c = Concept(self.term, deepcopy(self.vocabulary), self.tag)
        c.sf = copy(self.sf)  # to include $0 and any other subfields not part of the term
        return c

    @property
    def components(self):
        return [v for k, v in self.sf.items() if k in ['a', 'b', 'x', 'y', 'z'] and v is not None]

    @property
    def term(self):
        return ' : '.join(self.components)

    def __str__(self):
        c = ['${} {}'.format(x, self.sf[x]) for x in ['a', 'x', '0'] if self.sf[x] is not None]
        return ' '.join(c)

    def authorize(self, skosmos):
        c = skosmos.authorize_term(self.term, self.tag)
        if c is not None:
            cid = c['localname'].strip('c')
            self.sf['0'] = self.vocabulary.marc_prefix + cid
            log.info('Authorized %s %s', self.tag, self)

    def field(self):
        return {'tag': self.tag, 'sf': self.sf}