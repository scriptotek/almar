# coding=utf-8
from __future__ import unicode_literals
import logging
import os
import io
import getpass
from textwrap import dedent
from datetime import datetime
from prompter import yesno
from tqdm import tqdm
from .util import normalize_term
from .skosmos import Skosmos
from .marc import Subjects

log = logging.getLogger(__name__)

formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S')

log_capture_string = io.StringIO()
capture_handler = logging.StreamHandler(log_capture_string)
capture_handler.setLevel(logging.INFO)
capture_handler.setFormatter(formatter)
log.addHandler(capture_handler)


class Job(object):

    def __init__(self, sru, alma, vocabulary, mailer, tag, old_term, new_term, dest_tag=None):
        self.sru = sru
        self.alma = alma
        self.tag = tag
        self.dest_tag = dest_tag
        self.vocabulary = vocabulary
        self.mailer = mailer
        self.old_term = normalize_term(old_term)
        self.new_term = normalize_term(new_term)
        self.job_name = datetime.now().isoformat()
        self.skosmos = Skosmos(self.vocabulary.skosmos_code)

    def start(self, dry_run=False, non_interactive=False, show_progress=True, show_diffs=False):

        username = getpass.getuser()
        heading = ' {}: Starting job '.format(username)
        if self.alma.name is not None:
            heading += 'in env: {} '.format(self.alma.name)

        log.info('{:=^70}'.format(heading))
        if dry_run:
            log.info('Dry run: No catalog records will be touched!')

        if self.dest_tag is not None or self.new_term != '':
            self.skosmos.check(self.tag, self.old_term, self.new_term, self.dest_tag)

        # if not skosmos.check(self.vocabulary.skosmos_code, self.tag, self.old_term, self.new_term):
        #     if non_interative or yesno('Vil du fortsette allikevel?', default='no'):
        #         return

        tags = [self.tag]
        if self.tag == '648' and self.vocabulary.marc_code == 'noubomn':
            tags.append('650')
            log.info('Note: For the 648 field, we will also fix the 650 duplicate')

        oc = self.old_term.split(' : ')
        nc = self.new_term.split(' : ')

        reporting_info = {'t': ','.join(tags), 'v': self.vocabulary.marc_code, 'o': oc[0], 'n': nc[0]}
        if self.dest_tag is not None:
            # Move to another tag
            reporting_info['ot'] = self.old_term
            reporting_info['t'] = self.tag
            reporting_info['dt'] = self.dest_tag
            log.info('Will move "%(ot)s" from %(t)s to %(dt)s', reporting_info)

        elif len(oc) == 2 and len(nc) == 2:
            # $a : $x -> $a : $x
            reporting_info['o2'] = oc[1]
            reporting_info['n2'] = nc[1]
            log.info('Will replace "$a %(o)s $x %(o2)s" with "$a %(n)s $x %(n2)s"' +
                     ' in %(t)s fields having $2 %(v)s', reporting_info)

        elif len(oc) == 1 and len(nc) == 1:
            # $a -> $a
            if self.new_term == '':
                log.info('Will remove %(t)s fields having "$a %(o)s $2 %(v)s"', reporting_info)
            else:
                log.info('Will replace "%(o)s" with "%(n)s" in subfields $a and $x' +
                         ' in %(t)s fields having $2 %(v)s', reporting_info)

        elif len(oc) == 2 and len(nc) == 1:
            # $a : $x -> $a
            reporting_info['o2'] = oc[1]
            if self.new_term == '':
                log.info('Will remove %(t)s fields having "$a %(o)s $x %(o2)s $2 %(v)s"', reporting_info)
            else:
                log.info('Will replace "$a %(o)s $x %(o2)s" with "$a %(n)s"' +
                         ' in %(t)s fields having $2 %(v)s"', reporting_info)

        elif len(oc) == 1 and len(nc) == 2:
            # $a -> $a : $x
            reporting_info['n2'] = nc[1]
            log.info('Will replace "$a %(o)s" with "$a %(n)s $x %(n2)s"' +
                     ' in %(t)s fields having $2 %(v)s"', reporting_info)

        else:
            log.error('Strings with more than two components are not yet supported! Got %d:%d' % (len(oc), len(nc)))
            return

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
        cql_query = 'alma.subjects=="%s" AND alma.authority_vocabulary = "%s"' % (self.old_term,
                                                                                  self.vocabulary.marc_code)

        for marc_record in self.sru.search(cql_query):
            if pbar is None and show_progress and self.sru.num_records > 50:
                pbar = tqdm(total=self.sru.num_records, desc='Filtering SRU results')

            log.debug('Checking record %s', marc_record.id())

            subjects = Subjects(marc_record)
            fields = subjects.find(vocabulary=self.vocabulary.marc_code, term=self.old_term, tags=tags)

            if len(list(fields)) != 0:
                valid_records.append(marc_record.id())

            if pbar is not None:
                pbar.update()
        if pbar is not None:
            pbar.close()

        if len(valid_records) == 0:
            log.info('No matching catalog records found')
            return
        else:
            log.info('%d catalog records will be updated' % len(valid_records))

        if not non_interactive and not yesno('Continue?', default='yes'):
            log.info('Bye')
            return

        # ------------------------------------------------------------------------------------
        # Del 2: Nå har vi en liste over MMS-IDer for bibliografiske poster vi vil endre.
        # Vi går gjennom dem én for én, henter ut posten med Bib-apiet, endrer og poster tilbake.

        for n, mms_id in enumerate(valid_records):
            log.info(' {:3d}/{:d}: {}'.format(n + 1, len(valid_records), mms_id))
            bib = self.alma.bibs(mms_id)

            subjects = Subjects(bib.marc_record)
            if self.dest_tag is not None:
                subjects.move(self.vocabulary.marc_code, self.old_term, self.tag, self.dest_tag)
            elif self.new_term == '':
                subjects.remove(self.vocabulary.marc_code, self.old_term, tags)
            else:
                subjects.rename(self.vocabulary.marc_code, self.old_term, self.new_term, tags)

            if not dry_run:
                if bib.linked_to_cz is True:

                    log.warning(dedent(
                        '''\
                        Encountered a Community Zone record. Updating such records through the API will
                        currently cause them to be de-linked from CZ, which is probably not what you want.
                        Until Ex Libris fixes this, you're best off editing the record manually in Alma.
                        '''))

                    if non_interactive or yesno('Do you want to update the record and break CZ linkage?', default='no'):
                        log.warning(' -> Skipping this record. You should update it manually in Alma!')
                        continue

                    log.warning(' -> Updating the record. The CZ connection will be lost!')

                bib.save(show_diffs)

        log.info('{:=^70}'.format(' Job complete '))

        if not dry_run:
            n_posts = '{:d} {}'.format(len(valid_records), 'record' if len(valid_records) == 1 else 'records')
            if self.new_term == '':
                subject = '{}: Removed "{}" in {}'.format(self.tag, self.old_term, n_posts)
            else:
                subject = '{}: Changed "{}" to "{}" in {}'.format(self.tag, self.old_term, self.new_term, n_posts)
            body = log_capture_string.getvalue()

            self.mailer.send(subject, body)

        return valid_records
