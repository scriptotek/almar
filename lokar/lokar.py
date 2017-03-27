# coding=utf-8
from __future__ import unicode_literals
import argparse
import logging.handlers
from io import open
import io
import sys
import os
import re
import getpass

from raven import Client

from email.mime.text import MIMEText
from email.header import Header
from email.mime.multipart import MIMEMultipart
from subprocess import Popen, PIPE

import requests
import yaml
from six import text_type, binary_type

from . import __version__
from .job import Job, Concept
from .alma import Alma
from .sru import SruClient
from .util import normalize_term


logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger('requests').setLevel(logging.WARNING)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S')

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

supported_tags = ['084', '648', '650', '651', '655']


class Vocabulary(object):

    marc_code = ''
    skosmos_code = ''
    marc_prefix = ''

    def __init__(self, marc_code, skosmos_code=None, marc_prefix=None):
        self.marc_code = marc_code
        self.skosmos_code = skosmos_code
        self.marc_prefix = marc_prefix


class Mailer(object):

    def __init__(self, config):
        self.config = config

    def send(self, subject, body):
        if self.config['driver'] == 'sendmail':
            self.send_using_sendmail(subject, body)
        elif self.config['driver'] == 'mailgun':
            self.send_using_mailgun(subject, body)
        else:
            raise RuntimeError('Unknown mail driver')

    def send_using_sendmail(self, subject, body):
        msg = MIMEText(body.encode('utf-8'), 'plain', 'utf-8')
        if self.config.get('sender') is not None:
            msg['From'] = self.config.get('sender')
        msg['To'] = self.config.get('recipient')
        msg['Subject'] = Header(subject, 'utf-8')
        p = Popen(['sendmail', '-t'], stdin=PIPE)
        p.communicate(msg.as_string())

    def send_using_mailgun(self, subject, body):
        request_url = 'https://api.mailgun.net/v2/{0}/messages'.format(self.config['domain'])
        request = requests.post(request_url, auth=('api', self.config['api_key']), data={
            'from': self.config.get('sender'),
            'to': self.config.get('recipient'),
            'subject': subject,
            'text': body
        })
        request.raise_for_status()


def parse_args(args, default_env=None):
    parser = argparse.ArgumentParser(prog='lokar', description='''
            Edit or remove subject fields in Alma catalog records.
            Supported fields: {}
            '''.format(', '.join(supported_tags)))
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    parser.add_argument('-e', '--env', dest='env', nargs='?',
                        help='Environment from config file. Default: {}'.format(default_env or '(none)'),
                        default=default_env)

    parser.add_argument('-d', '--dry_run', dest='dry_run', action='store_true',
                        help='Dry run without doing any edits.')

    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='Show more output')

    parser.add_argument('-n', '--non-interactive', dest='non_interactive', action='store_true',
                        help='Non-interactive mode. Always use defaults rather than asking.')

    parser.add_argument('--diffs', dest='show_diffs', action='store_true',
                        help='Show diffs before saving.')

    subparsers = parser.add_subparsers(title='subcommands')

    # Create parser for the "move" command
    parser_move = subparsers.add_parser('rename', help='Rename/move term')
    parser_move.add_argument('term', nargs=1, help='Term to search for')
    parser_move.add_argument('new_term', nargs=1, default='', help='Replacement term')
    parser_move.add_argument('new_term2', nargs='?', default='', help='Second replacement term')
    parser_move.set_defaults(action='rename')

    # Create parser for the "delete" command
    parser_del = subparsers.add_parser('delete', help='Delete term')
    parser_del.add_argument('term', nargs=1, help='Term to delete')
    parser_del.set_defaults(action='delete')

    # Parse
    args = parser.parse_args(args)

    if args.env is not None:
        args.env = args.env.strip()

    args.term = args.term[0]

    if args.action == 'delete':
        args.new_term = ''
        args.new_term2 = ''
    else:
        args.new_term = args.new_term[0]

    if type(args.term) == binary_type:
        args.term = args.term.decode('utf-8')
    if type(args.new_term) == binary_type:
        args.new_term = args.new_term.decode('utf-8')
    if type(args.new_term2) == binary_type:
        args.new_term2 = args.new_term2.decode('utf-8')
    if type(args.env) == binary_type:
        args.env = args.env.decode('utf-8')

    return args


def get_concept(term, vocabulary, default_tag='650', default_term=None):
    m = re.match('^({})$'.format('|'.join(supported_tags)), term)
    if m:
        if default_term is None:
            raise RuntimeError('No source term specified')
        return Concept(default_term, vocabulary, m.group(1))

    m = re.match('^({}) (.+)$'.format('|'.join(supported_tags)), term)
    if m:
        return Concept(m.group(2), vocabulary, m.group(1))

    return Concept(term, vocabulary, default_tag)


def job_args(config=None, args=None):
    vocabulary = Vocabulary(config['vocabulary']['marc_code'],
                            config['vocabulary'].get('skosmos_code'),
                            config['vocabulary'].get('marc_prefix', ''))

    source_concept = get_concept(args.term, vocabulary)
    target_concept = None
    target_concept2 = None

    if args.action == 'rename':
        target_concept = get_concept(args.new_term, vocabulary, default_term=args.term)

        if args.new_term2 != '':
            target_concept2 = get_concept(args.new_term2, vocabulary)

    return {
        'source_concept': source_concept,
        'target_concept': target_concept,
        'target_concept2': target_concept2,
    }


def main(config=None, args=None):

    try:
        with config or open('lokar.yml') as f:
            config = yaml.load(f)
    except IOError:
        logger.error('Fant ikke lokar.yml. Se README.md for mer info.')
        return

    username = getpass.getuser()
    logger.info('Running as {}'.format(username))
    try:
        if config.get('sentry') is not None:
            raven = Client(config['sentry']['dsn'])
            raven.context.merge({'user': {
                'username': username
            }})

        args = parse_args(args or sys.argv[1:], config.get('default_env'))
        jargs = job_args(config, args)

        if args.verbose:
            logger.setLevel(logging.DEBUG)

        if not args.dry_run:
            file_handler = logging.FileHandler('lokar.log')
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO)
            logger.addHandler(file_handler)

        if args.env is None:
            raise RuntimeError('No environment specified in config file')

        env = config['env'][args.env]

        sru = SruClient(env['sru_url'], args.env)
        alma = Alma(env['api_region'], env['api_key'], args.env)
        mailer = Mailer(config['mail'])

        job = Job(sru=sru, alma=alma, mailer=mailer, **jargs)
        job.dry_run = args.dry_run
        job.interactive = not args.non_interactive
        job.verbose = args.verbose
        job.show_diffs = args.show_diffs

        job.start()
        logger.info('{:=^70}'.format(' Job complete '))

    except Exception as e:
        if config.get('sentry') is not None:
            raven.captureException()
        logger.exception('Uncaught exception:')


if __name__ == '__main__':
    main()
