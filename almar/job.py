# coding=utf-8
from __future__ import unicode_literals, print_function

import io
import logging
from copy import copy
from datetime import datetime
from textwrap import dedent

from prompter import yesno
from requests.exceptions import HTTPError
from tqdm import tqdm

from .sru import TooManyResults
from .task import AddTask, ReplaceTask, InteractiveReplaceTask, ListTask, MoveTask, DeleteTask

log = logging.getLogger(__name__)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S')

class Job(object):
    def __init__(self, action, source_concept, target_concepts=None, sru=None, alma=None,
                 list_options=None):
        self.dry_run = False
        self.interactive = True
        self.show_progress = True
        self.show_diffs = False
        self.list_options = list_options or {}

        self.sru = sru
        self.alma = alma

        self.action = action
        self.source_concept = source_concept
        self.target_concepts = target_concepts or []
        self.vocabulary = self.source_concept.vocabulary

        self.job_name = datetime.now().isoformat()

        if self.source_concept.tag == '648' and self.source_concept.vocabulary.marc_code == 'noubomn':
            raise RuntimeError('Editing 648 for noubomn is disabled until we get rid of the 650 duplicates')
            # log.info('Note: For the 648 field, we will also fix the 650 duplicate')

        self.authorize()
        self.steps = []
        self.generate_steps()

    @staticmethod
    def generate_replace_tasks(src, dst):

        if len(src.components) == 1 and len(dst.components) == 1:
            tasks = [ReplaceTask(src, dst, True)]

            src_copy = copy(src)
            dst_copy = copy(dst)
            src_copy.sf['x'] = src_copy.sf['a']
            del src_copy.sf['a']
            dst_copy.sf['x'] = dst_copy.sf['a']
            del dst_copy.sf['a']

            tasks.append(ReplaceTask(src_copy, dst_copy, True))
        else:
            tasks = [ReplaceTask(src, dst)]

        return tasks

    def generate_steps(self):

        if self.action == 'delete':
            # Delete
            self.steps.append(DeleteTask(self.source_concept))

        elif self.action == 'interactive':
            self.steps.append(InteractiveReplaceTask(self.source_concept, self.target_concepts))

        elif self.action == 'list':
            self.steps.append(ListTask(self.source_concept, **self.list_options))

        elif self.action == 'rename':
            src = self.source_concept
            dst = self.target_concepts[0]

            # Rename
            if src.term != dst.term:
                for step in self.generate_replace_tasks(src, dst):
                    self.steps.append(step)

                # Note: Update source concept before next step (move)
                dst_copy = copy(dst)
                dst_copy.tag = src.tag
                src = dst_copy

            # Move
            if src.tag != dst.tag:
                self.steps.append(MoveTask(src, dst.tag))

            # Add
            if len(self.target_concepts) > 1:
                self.steps.append(AddTask(self.target_concepts[1]))

    def update_record(self, bib):

        modified = 0
        for step in self.steps:
            modified += step.run(bib.marc_record)

        if modified == 0:
            return

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
        if self.action in ['delete', 'list']:
            return

        self.source_concept.authorize()
        self.target_concepts[0].authorize()
        if self.target_concepts[0].sf['0'] is None:
            # Use the source term identifier (if we just moved a concept)
            self.target_concepts[0].sf['0'] = self.source_concept.sf['0']
        if self.target_concepts[0].sf['0'] is None:
            log.warning('Neither the source term nor the (first) target term could be authorized in Skosmos.')
        for target_concept in self.target_concepts[1:]:
            target_concept.authorize()
            if target_concept.sf['0'] is None:
                log.warning('The target term "%s" could not be authorized in Skosmos.', target_concept)

    def start(self):

        if self.alma.name is not None:
            log.info('Alma environment: %s', self.alma.name)

        for i, step in enumerate(self.steps):
            log.info('Step %d of %d: %s', i + 1, len(self.steps), step)

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

                log.debug('Checking record %s', marc_record.id)

                for step in self.steps:
                    if step.match(marc_record):
                        valid_records.append(marc_record.id)
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
        elif self.action in ['interactive', 'list']:
            log.info('%d catalog records found', len(valid_records))
        else:
            log.info('%d catalog records will be updated', len(valid_records))

            if self.interactive and not yesno('Continue?', default='yes'):
                log.info('Bye')
                return []

        # ------------------------------------------------------------------------------------
        # Del 2: Nå har vi en liste over MMS-IDer for bibliografiske poster vi vil endre.
        # Vi går gjennom dem én for én, henter ut posten med Bib-apiet, endrer og poster tilbake.

        for i, mms_id in enumerate(valid_records):
            if self.action not in ['list', 'interactive']:
                print(' %3d/%d: %s' % (i + 1, len(valid_records), mms_id))
            bib = self.alma.bibs(mms_id)
            self.update_record(bib)

        n_posts = '{:d} {}'.format(len(valid_records), 'record' if len(valid_records) == 1 else 'records')

        subject = None

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

        if subject is not None:
            log.info(subject)

        return valid_records
