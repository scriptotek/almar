# coding=utf-8
from __future__ import unicode_literals
import argparse
import logging.handlers
from io import open
import io
import sys
import os
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
from .job import Job
from .alma import Alma
from .sru import SruClient


logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger('requests').setLevel(logging.WARNING)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S')

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


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


def parse_args(args, config):
    parser = argparse.ArgumentParser(prog='lokar',
                                     description='Edit or remove subject fields in Alma catalog records.')
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    parser.add_argument('-e', '--env', dest='env', nargs='?',
                        help='Environment from config file. Default: {}'.format(config.get('default_env') or '(none)'),
                        default=config.get('default_env'))

    parser.add_argument('-d', '--dry_run', dest='dry_run', action='store_true',
                        help='Dry run without doing any edits.')

    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='Show more output')

    parser.add_argument('-n', '--non-interactive', dest='non_interactive', action='store_true',
                        help='Non-interactive mode. Always use defaults rather than asking.')

    parser.add_argument('--diffs', dest='show_diffs', action='store_true',
                        help='Show diffs before saving.')

    parser.add_argument('-t', '--tag', dest='tag', nargs='?',
                        help='MARC tag (648/650/651/655). Default: 650',
                        default='650', choices=['648', '650', '651', '655'])

    subparsers = parser.add_subparsers(title='subcommands')

    # Create parser for the "move" command
    parser_move = subparsers.add_parser('rename', help='Rename/move term')
    parser_move.add_argument('term', nargs=1, help='Term to search for')
    parser_move.add_argument('new_term', nargs='?', default='', help='Replacement term')
    parser_move.add_argument('-T', '--to_tag', dest='dest_tag', nargs='?',
                             help='Destination MARC tag if you want to move to another tag (648/650/651/655).',
                             choices=['648', '650', '651', '655'])
    parser_move.set_defaults(action='rename')

    # Create parser for the "delete" command
    parser_del = subparsers.add_parser('delete', help='Delete term')
    parser_del.add_argument('term', nargs=1, help='Term to delete')
    parser_del.set_defaults(action='delete')

    # Parse
    args = parser.parse_args(args)

    if args.env is None:
        parser.error('no environment specified')

    args.env = args.env.strip()
    args.term = args.term[0]

    if args.action == 'rename' and args.new_term == '' and args.dest_tag is None:
        parser.error('too few arguments (at least one of "new_term" and "--to_tag" must be specified)')

    if args.action == 'delete':
        args.new_term = ''
        args.dest_tag = None

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if type(args.term) == binary_type:
        args.term = args.term.decode('utf-8')
    if type(args.new_term) == binary_type:
        args.new_term = args.new_term.decode('utf-8')
    if type(args.env) == binary_type:
        args.env = args.env.decode('utf-8')

    return args


def main(config=None, args=None):

    username = getpass.getuser()

    try:
        with config or open('lokar.yml') as f:
            config = yaml.load(f)
    except IOError:
        logger.error('Fant ikke lokar.yml. Se README.md for mer info.')
        return

    args = parse_args(args or sys.argv[1:], config=config)

    if config.get('sentry') is not None:
        raven = Client(config['sentry']['dsn'])
        raven.context.merge({'user': {
            'username': username
        }})

    try:
        env = config['env'][args.env]

        if not args.dry_run:
            file_handler = logging.FileHandler('lokar.log')
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO)
            logger.addHandler(file_handler)

        sru = SruClient(env['sru_url'], args.env)
        alma = Alma(env['api_region'], env['api_key'], args.env)

        vocabulary = Vocabulary(config['vocabulary']['marc_code'],
                                config['vocabulary'].get('skosmos_code'),
                                config['vocabulary'].get('marc_prefix'))
        mailer = Mailer(config['mail'])

        # if args.action == 'rename':

        job = Job(sru, alma, vocabulary, mailer, args.tag, args.term, args.new_term, dest_tag=args.dest_tag)
        job.start(args.dry_run, args.non_interactive, not args.verbose, args.show_diffs)

    except Exception as e:
        if config.get('sentry') is not None:
            raven.captureException()
        logger.exception('Uncaught exception:')


if __name__ == '__main__':
    main()
