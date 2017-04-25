# coding=utf-8
from __future__ import unicode_literals

from future.utils import python_2_unicode_compatible
from collections import OrderedDict
import logging
import io
from textwrap import dedent
from datetime import datetime
from prompter import yesno
from tqdm import tqdm
from requests.exceptions import HTTPError

from .sru import TooManyResults
from .skosmos import Skosmos
from .task import AddTask, ReplaceTask, MoveTask, DeleteTask

log = logging.getLogger(__name__)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S')

log_capture_string = io.StringIO()
capture_handler = logging.StreamHandler(log_capture_string)
capture_handler.setLevel(logging.INFO)
capture_handler.setFormatter(formatter)
log.addHandler(capture_handler)


@python_2_unicode_compatible
class Concept(object):
    def __init__(self, term, vocabulary, tag='650'):
        self.term = term
        self.vocabulary = vocabulary
        self.tag = tag
        self.components = self.term.split(' : ')
        self.sf = {
            'a': self.components[0],
            'x': None,
            '0': None,
            '2': vocabulary.marc_code,
        }
        if len(self.components) > 1:
            self.sf['x'] = self.components[1]
        if len(self.components) > 2:
            raise RuntimeError('Strings with more than two components are not supported')

    def __str__(self):
        c = ['${} {}'.format(x, self.sf[x]) for x in ['a', 'x', '0'] if self.sf[x] is not None]
        return ' '.join(c)

    def authorize(self, skosmos):
        c = skosmos.authorize_term(self.term, self.tag)
        if c is not None:
            cid = c['localname'].strip('c')
            self.sf['0'] = self.vocabulary.marc_prefix + cid
            log.info('Authorized %s %s', self.tag, self)


class Job(object):
    def __init__(self, action, source_concept, target_concepts=None, sru=None, alma=None, mailer=None):
        self.dry_run = False
        self.interactive = True
        self.show_progress = True
        self.show_diffs = False

        self.sru = sru
        self.alma = alma
        self.mailer = mailer

        self.action = action
        self.source_concept = source_concept
        self.target_concepts = target_concepts or []
        self.vocabulary = self.source_concept.vocabulary

        self.job_name = datetime.now().isoformat()
        self.skosmos = Skosmos(self.vocabulary.skosmos_code)

        if self.source_concept.tag == '648' and self.source_concept.vocabulary.marc_code == 'noubomn':
            raise RuntimeError('Editing 648 for noubomn is disabled until we get rid of the 650 duplicates')
            # log.info('Note: For the 648 field, we will also fix the 650 duplicate')

        if self.action != 'delete':
            self.authorize()
        self.steps = []
        self.generate_steps()

    @staticmethod
    def generate_replace_tasks(src, dst):
        if len(src.components) == 2 and len(dst.components) == 2:
            return [
                ReplaceTask(src.tag, src.vocabulary.marc_code, OrderedDict([
                    ('a', {'search': src.sf['a'], 'replace': dst.sf['a']}),
                    ('x', {'search': src.sf['x'], 'replace': dst.sf['x']}),
                ]), dst.sf['0'])
            ]

        if len(src.components) == 2 and len(dst.components) == 1:
            return [
                ReplaceTask(src.tag, src.vocabulary.marc_code, OrderedDict([
                    ('a', {'search': src.sf['a'], 'replace': dst.sf['a']}),
                    ('x', {'search': src.sf['x'], 'replace': None}),
                ]), dst.sf['0'])
            ]

        if len(src.components) == 1 and len(dst.components) == 2:
            return [
                ReplaceTask(src.tag, src.vocabulary.marc_code, OrderedDict([
                    ('a', {'search': src.sf['a'], 'replace': dst.sf['a']}),
                    ('x', {'search': None, 'replace': dst.sf['x']}),
                ]), dst.sf['0'])
            ]

        return [
            ReplaceTask(src.tag, src.vocabulary.marc_code, OrderedDict([
                ('a', {'search': src.sf['a'], 'replace': dst.sf['a']}),
            ]), dst.sf['0']),
            ReplaceTask(src.tag, src.vocabulary.marc_code, OrderedDict([
                ('x', {'search': src.sf['a'], 'replace': dst.sf['a']}),
            ]))
        ]

    def generate_steps(self):

        if self.action == 'delete':
            # Delete
            self.steps.append(DeleteTask(self.source_concept))

        elif self.action == 'rename':
            src = self.source_concept
            dst = self.target_concepts[0]

            # Rename
            if src.term != dst.term:
                for step in self.generate_replace_tasks(src, dst):
                    self.steps.append(step)

            # Move
            if src.tag != dst.tag:
                # Note: we are using the *destination* $a and $x here since we might
                # already have performed a rename in the previous step!
                self.steps.append(MoveTask(src.tag, src.sf['2'], OrderedDict([
                    ('a', dst.sf['a']),
                    ('x', dst.sf['x'])
                ]), dst.tag))

            # Add
            if len(self.target_concepts) > 1:
                self.steps.append(AddTask(self.target_concepts[1]))

    def update_record(self, bib):

        for step in self.steps:
            step.run(bib.marc_record)

        if bib.cz_link is not None:
            log.warning(dedent(
                '''\
                Encountered a Community Zone record. Updating such records through the API will
                currently cause them to be de-linked from CZ, which is probably not what you want.
                Until Ex Libris fixes this, you're best off editing the record manually in Alma.
                '''))

            if not self.interactive or yesno('Do you want to update the record and break CZ linkage?', default='no'):
                log.warning(' -> Skipping this record. You should update it manually in Alma!')
                return

            log.warning(' -> Updating the record. The CZ connection will be lost!')

        try:
            bib.save(self.show_diffs, self.dry_run)
        except HTTPError:
            msg = '*** Failed to save record %s --- Please try to edit the record manually in Alma ***'
            log.error(msg, bib.mms_id)

    def authorize(self):
        if self.action == 'delete':
            return
        self.source_concept.authorize(self.skosmos)
        self.target_concepts[0].authorize(self.skosmos)
        if self.target_concepts[0].sf['0'] is None:
            # Use the source term identifier (if we just moved a concept)
            self.target_concepts[0].sf['0'] = self.source_concept.sf['0']
        if self.target_concepts[0].sf['0'] is None:
            log.warning('Neither the source term nor the (first) target term could be authorized in Skosmos.')
        for target_concept in self.target_concepts[1:]:
            target_concept.authorize(self.skosmos)
            if target_concept.sf['0'] is None:
                log.warning('The target term "%s" could not be authorized in Skosmos.', target_concept)

    def start(self):

        if self.alma.name is not None:
            log.info('Alma environment: %s', self.alma.name)

        for n, step in enumerate(self.steps):
            log.info('Step %d of %d: %s', n + 1, len(self.steps), step)

        if self.dry_run:
            log.info('Dry run: No catalog records will be touched!')

        # ------------------------------------------------------------------------------------
        # Del 1: Søk mot SRU for å finne over alle bibliografiske poster med emneordet.
        # Vi må filtrere resultatlista i etterkant fordi
        #  - vi mangler en egen indeks for Realfagstermer, så vi må søke mot `alma.subjects`
        #  - søket er ikke presist, så f.eks. "Monstre" vil gi treff i "Mønstre"
        #
        # I fremtiden, når vi får $0 på alle poster, kan vi bruke indeksen `alma.authority_id`
        # i stedet.

        valid_records = []
        pbar = None
        cql_query = 'alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (self.source_concept.term,
                                                                                  self.vocabulary.marc_code)

        try:
            for marc_record in self.sru.search(cql_query):
                if pbar is None and self.show_progress and self.sru.num_records > 50:
                    pbar = tqdm(total=self.sru.num_records, desc='Filtering SRU results')

                log.debug('Checking record %s', marc_record.id())

                for step in self.steps:
                    if step.match(marc_record):
                        valid_records.append(marc_record.id())
                        break

                if pbar is not None:
                    pbar.update()
            if pbar is not None:
                pbar.close()
        except TooManyResults:
            log.error('More than 10,000 results would have to be checked, but the Alma SRU service does ' +
                      'not allow us to retrieve more than 10,000 results. Annoying? Go vote for this:\n' +
                      'http://ideas.exlibrisgroup.com/forums/308173-alma/suggestions/' +
                      '18737083-sru-srw-increase-the-10-000-record-retrieval-limi')
            return []

        if len(valid_records) == 0:
            log.info('No matching catalog records found')
            return []
        else:
            log.info('%d catalog records will be updated', len(valid_records))

        if self.interactive and not yesno('Continue?', default='yes'):
            log.info('Bye')
            return []

        # ------------------------------------------------------------------------------------
        # Del 2: Nå har vi en liste over MMS-IDer for bibliografiske poster vi vil endre.
        # Vi går gjennom dem én for én, henter ut posten med Bib-apiet, endrer og poster tilbake.

        for n, mms_id in enumerate(valid_records):
            log.info(' %3d/%d: %s', n + 1, len(valid_records), mms_id)
            bib = self.alma.bibs(mms_id)
            self.update_record(bib)

        n_posts = '{:d} {}'.format(len(valid_records), 'record' if len(valid_records) == 1 else 'records')

        if self.action == 'delete':
            args = (self.source_concept.tag, self.source_concept.term, n_posts)
            subject = 'Deleted {} "{}" in {}'.format(*args)

        elif self.action == 'rename':
            if len(self.target_concepts) == 2:
                args = (self.source_concept.tag, self.source_concept.term,
                        self.target_concepts[0].tag, self.target_concepts[0].term,
                        self.target_concepts[1].tag, self.target_concepts[1].term,
                        n_posts)
                subject = 'Changed {} "{}" to {} "{}" + {} "{}" in {}'.format(*args)

            elif len(self.target_concepts) == 1:
                if self.source_concept.term == self.target_concepts[0].term:
                    args = (self.source_concept.tag, self.source_concept.term,
                            self.target_concepts[0].tag, n_posts)
                    subject = 'Moved {} "{}" to {} in {}'.format(*args)
                else:
                    args = (self.source_concept.tag, self.source_concept.term,
                            self.target_concepts[0].tag, self.target_concepts[0].term,
                            n_posts)
                    subject = 'Changed {} "{}" to {} "{}" in {}'.format(*args)

        body = log_capture_string.getvalue()

        log.info(subject)
        if self.mailer is not None and not self.dry_run:
            self.mailer.send(subject, body)

        return valid_records
