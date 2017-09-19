# coding=utf-8
from __future__ import unicode_literals, print_function

import logging
from copy import deepcopy
from datetime import datetime

from prompter import yesno
from tqdm import tqdm

from .sru import TooManyResults
from .task import AddTask, ReplaceTask, InteractiveReplaceTask, ListTask, DeleteTask

log = logging.getLogger(__name__)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S')


class Job(object):
    def __init__(self, action, source_concept, target_concepts=None, sru=None, ils=None,
                 list_options=None, authorities=None, cql_query=None):

        self.dry_run = False
        self.interactive = True
        self.show_progress = True
        self.show_diffs = False
        self.list_options = list_options or {}

        self.sru = sru
        self.ils = ils
        self.authorities = authorities

        self.action = action
        self.source_concept = source_concept
        self.target_concepts = target_concepts or []

        self.job_name = datetime.now().isoformat()

        if self.source_concept.tag == '648' and self.source_concept.sf.get('2') == 'noubomn':
            raise RuntimeError('Editing 648 for noubomn is disabled until we get rid of the 650 duplicates')
            # log.info('Note: For the 648 field, we will also fix the 650 duplicate')

        self.authorize()
        log.debug('Source concept: %s', source_concept)
        for target_concept in target_concepts:
            log.debug('Target concept: %s', target_concept)

        cql_query = cql_query or 'alma.subjects = "{term}" AND alma.authority_vocabulary = "{vocabulary}"'
        self.cql_query = cql_query.format(term=self.source_concept.term, vocabulary=self.source_concept.sf['2'])

        self.steps = []
        self.generate_steps()

    @staticmethod
    def generate_replace_tasks(src, dst):
        """
        :type src: Concept
        :type dst: Concept
        """
        if len(src.components) == 1 and len(dst.components) == 1:
            if 'a_or_x' in src.sf and 'a_or_x' in dst.sf:
                tasks = []
                for code in ['a', 'x']:
                    src_copy = deepcopy(src)
                    dst_copy = deepcopy(dst)
                    src_copy.set_a_or_x_to(code)
                    dst_copy.set_a_or_x_to(code)
                    if code == 'a':
                        tasks.append(ReplaceTask(src_copy, dst_copy, False))  # exact match
                    tasks.append(ReplaceTask(src_copy, dst_copy, True))   # ignore extra subfields

                return tasks

        return [
            ReplaceTask(src, dst, False)
        ]

    def generate_steps(self):

        if self.action == 'remove':
            # Delete
            self.steps.append(DeleteTask(self.source_concept))

        elif self.action == 'interactive':
            self.steps.append(InteractiveReplaceTask(self.source_concept, self.target_concepts))

        elif self.action == 'list':
            self.steps.append(ListTask(self.source_concept, **self.list_options))

        elif self.action == 'replace':

            # Rename source concept to first target concept
            for step in self.generate_replace_tasks(self.source_concept,
                                                    self.target_concepts[0]):
                self.steps.append(step)

            # Add remaining target concepts
            for target_concept in self.target_concepts[1:]:
                self.steps.append(AddTask(target_concept))

    def update_record(self, record):
        modified = 0
        for step in self.steps:
            modified += step.run(record.marc_record)

        if modified == 0:
            return

        self.ils.put_record(record, interactive=self.interactive, diff=self.show_diffs)

    def authorize(self):
        if self.action in ['remove']:
            return

        # self.source_concept.authorize()
        if len(self.target_concepts) == 0:
            return
        self.authorities.authorize_concept(self.target_concepts[0])

        if '0' not in self.target_concepts[0].sf:
            log.warning('The (first) target term could not be authorized.')

        for target_concept in self.target_concepts[1:]:
            self.authorities.authorize_concept(target_concept)

    def start(self):

        if self.ils.name is not None:
            log.info('Alma environment: %s', self.ils.name)

        log.debug('Planned steps:')
        for i, step in enumerate(self.steps):
            log.debug(' %d. %s' % ((i + 1), step))

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

        valid_records = set()
        pbar = None

        try:
            for marc_record in self.sru.search(self.cql_query):
                if pbar is None and self.show_progress and self.sru.num_records > 50:
                    pbar = tqdm(total=self.sru.num_records, desc='Filtering SRU results')

                log.debug('Checking record %s', marc_record.id)
                for field in marc_record.fields:
                    if field.tag.startswith('6'):
                        matched = False
                        for step in self.steps:
                            if step.match_field(field):
                                matched = True
                                break  # no need to check rest of the steps
                        if matched:
                            log.debug('> %s', field)
                            valid_records.add(marc_record.id)
                        else:
                            log.debug('  %s', field)

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

        for idx, mms_id in enumerate(valid_records):
            if self.action not in ['list', 'interactive']:
                log.info('Updating record %d/%d: %s', idx + 1, len(valid_records), mms_id)
            record = self.ils.get_record(mms_id)
            self.update_record(record)

        return valid_records
