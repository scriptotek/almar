# coding=utf-8
from __future__ import unicode_literals
import logging
from io import BytesIO
from prompter import yesno
from requests import Session, HTTPError
from textwrap import dedent

from .util import get_diff, format_diff
from .bib import Bib

log = logging.getLogger(__name__)


class LibrarySystem(object):

    def get_record(self, record_id):
        raise NotImplementedError()

    def put_record(self, record):
        raise NotImplementedError()


class Alma(LibrarySystem):

    name = None

    def __init__(self, api_region, api_key, name=None, dry_run=False):
        self.api_region = api_region
        self.api_key = api_key
        self.name = name
        self.dry_run = dry_run
        self.session = Session()
        self.session.headers.update({'Authorization': 'apikey %s' % api_key})
        self.base_url = 'https://api-{region}.hosted.exlibrisgroup.com/almaws/v1'.format(region=self.api_region)

    def url(self, path, **kwargs):
        return self.base_url.rstrip('/') + '/' + path.lstrip('/').format(**kwargs)

    def get_record(self, record_id):
        """
        Get a Bib record from Alma

        :type record_id: string
        """
        response = self.session.get(self.url('/bibs/{mms_id}', mms_id=record_id))
        response.raise_for_status()
        record = Bib(response.text)
        if record.id != record_id:
            raise RuntimeError('Response does not contain the requested MMS ID. %s != %s'
                               % (record.id, record_id))
        return record

    def put_record(self, record, interactive=True, show_diff=False):
        """
        Store a Bib record to Alma

        :param show_diff: bool
        :param interactive: bool
        :type record: Bib
        """
        if record.cz_link is not None:
            log.warning(dedent(
                '''\
                Encountered a Community Zone record. Updating such records through the API will
                currently cause them to be de-linked from CZ, which is probably not what you want.
                Until Ex Libris fixes this, you're best off editing the record manually in Alma.\
                '''))

            if not interactive or yesno('Do you want to update the record and break CZ linkage?', default='no'):
                log.warning(' -> Skipping this record. You should update it manually in Alma!')
                return

            log.warning(' -> Updating the record. The CZ connection will be lost!')

        post_data = record.xml()
        diff = get_diff(record.orig_xml, post_data)
        additions = len([x for x in diff[2:] if x[0] == '+'])
        deletions = len([x for x in diff[2:] if x[0] == '-'])
        if show_diff:
            log.info('%d line(s) removed, %d line(s) added:\n%s', deletions, additions, format_diff(diff))
        else:
            log.debug('%d line(s) removed, %d line(s) added:\n%s', deletions, additions, format_diff(diff))

        if not self.dry_run:
            try:
                response = self.session.put(self.url('/bibs/{mms_id}', mms_id=record.id),
                                            data=BytesIO(post_data.encode('utf-8')),
                                            headers={'Content-Type': 'application/xml'})
                response.raise_for_status()
                record.init(response.text)

            except HTTPError:
                msg = '*** Failed to save record %s --- Please try to edit the record manually in Alma ***'
                log.error(msg, record.id)
