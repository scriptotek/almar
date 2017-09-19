# coding=utf-8
from __future__ import unicode_literals

import argparse
import getpass
from collections import OrderedDict

import colorlog
import colorama
import logging.handlers
import re
import os
import sys
from io import open  # pylint: disable=redefined-builtin

import yaml
from raven import Client
from six import binary_type

from . import __version__
from .authorities import Vocabulary, Authorities
from .alma import Alma
from .concept import Concept
from .job import Job
from .sru import SruClient
from .util import ANY_VALUE

raven_client = None

log = logging.getLogger()
log.setLevel(logging.INFO)
logging.getLogger('requests').setLevel(logging.WARNING)
console_handler = logging.StreamHandler()
if sys.stdout.isatty():
    colorama.init(autoreset=True)
    console_handler.setFormatter(colorlog.ColoredFormatter(
        '%(asctime)s %(log_color)s%(levelname)-8s%(reset)s %(message)s',
        datefmt='%Y-%m-%d %H:%I:%S',
        reset=True,
        log_colors={
            'DEBUG':    'cyan',
            'INFO':     'white',
            'WARNING':  'red',
            'ERROR':    'red',
            'CRITICAL': 'red,bg_white',
        }))
else:
    # We're being piped, so skip colors
    colorama.init(strip=True)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%I:%S'
    ))
log.addHandler(console_handler)


def ensure_unicode(arg):
    if isinstance(arg, binary_type):
        return arg.decode('utf-8')
    return arg


def parse_args(args, default_env=None):
    parser = argparse.ArgumentParser(prog='almar',
                                     description='Edit or remove subject fields in Alma catalog records.')
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

    parser.add_argument('--cql', dest='cql_query', nargs='?',
                        help='Custom CQL query to specify which records to be checked. ' +
                        'Example: --cql \'alma.all_for_ui = "some identifier"\''
                        )

    subparsers = parser.add_subparsers(title='subcommands')

    # Create parser for the "replace" command
    parser_move = subparsers.add_parser('replace', help='Replace/rename/move subject field')
    # TODO: , aliases=['rename', 'move'] added in Python 3.5

    parser_move.add_argument('term', nargs=1, help='Term to search for')
    parser_move.add_argument('new_term', nargs=1, default='', help='Replacement term')
    parser_move.add_argument('new_term2', nargs='?', default='', help='Second replacement term')
    parser_move.set_defaults(action='replace')

    # Create parser for the "remove" command
    parser_del = subparsers.add_parser('remove', help='Remove subject field')
    # TODO: # , aliases=['delete'] added in Python 3.5

    parser_del.add_argument('term', nargs=1, help='Term to remove')
    parser_del.set_defaults(action='remove')

    # Create parser for the "interactive" command
    parser_int = subparsers.add_parser('interactive', help='Interactive reclassification')
    parser_int.add_argument('term', nargs=1, help='Term to search for')
    parser_int.add_argument('new_terms', nargs='+', default='', help='Replacement terms')
    parser_int.set_defaults(action='interactive')

    # Create parser for the "list" command
    parser_list = subparsers.add_parser('list', help='List documents')
    parser_list.add_argument('term', nargs=1, help='Term to search for')
    parser_list.add_argument('--titles', dest='show_titles', action='store_true', help='Show titles')
    parser_list.add_argument('--subjects', dest='show_subjects', action='store_true', help='Show subject fields')
    parser_list.set_defaults(action='list')

    # Parse
    args = parser.parse_args(args)

    if 'action' not in args:
        parser.error('No action specified')

    if args.env is not None:
        args.env = args.env.strip()

    args.term = args.term[0]

    if args.action in ['remove', 'list']:
        args.new_terms = []
    elif args.action == 'replace':
        args.new_terms = [args.new_term[0]]
        if args.new_term2 != '':
            args.new_terms.append(args.new_term2)

    args.term = ensure_unicode(args.term)
    args.env = ensure_unicode(args.env)
    args.new_terms = [ensure_unicode(x) for x in args.new_terms]

    return args


def normalize_ind(value):
    if value == '#':
        return ' '
    return value


def parse_advanced_input(value):
    m = re.match(r'^(?P<tag>[0-9]{3}) (?P<ind1>[0-9#])(?P<ind2>[0-9#]) (?P<sf>\$\$.*)$', value)
    if not m:
        log.error('Invalid input format')
        sys.exit(1)
    sf = OrderedDict()
    for m2 in re.finditer(r'(?P<code>[a-z0-9]) (?P<val>[^\$]+)', m.group('sf')):
        sf[m2.group('code')] = m2.group('val').strip()

    if len(sf) == 0:
        log.error('Invalid input format')
        sys.exit(1)

    return {
        'tag': m.group('tag'),
        'ind1': normalize_ind(m.group('ind1')),
        'ind2': normalize_ind(m.group('ind2')),
        'sf': sf,
    }


def parse_components(streng):
    components = streng.split(' : ')
    sf = OrderedDict()
    if len(components) == 1:
        sf['a_or_x'] = components[0]
    elif len(components) == 2:
        sf['a'] = components[0]
        sf['x'] = components[1]
    if len(components) > 2:
        raise RuntimeError('Strings with more than two components are not supported')
    return sf


def get_concept(term, default_vocabulary, default_tag='650', default_term=None):

    # 1) Advanced syntax
    if '$$' in term:
        return Concept(**parse_advanced_input(term))

    # 2) Just tag
    match = re.match('^([0-9]{3})$', term)
    if match:
        if default_term is None:
            raise RuntimeError('No source term specified')
        sf = parse_components(default_term)
        sf['2'] = default_vocabulary
        return Concept(match.group(1), sf)

    # 3) Tag and term
    match = re.match('^([0-9]{3}) (.+)$', term)
    if match:
        sf = parse_components(match.group(2))
        sf['2'] = default_vocabulary
        return Concept(match.group(1), sf)

    # 4) Just term
    sf = parse_components(term)
    sf['2'] = default_vocabulary
    return Concept(default_tag, sf)


def job_args(config=None, args=None):

    vocabularies = {}
    for vocab in config.get('vocabularies', []):
        vocabularies[ensure_unicode(vocab['marc_code'])] = Vocabulary(
            ensure_unicode(vocab['marc_code']),
            ensure_unicode(vocab.get('id_service')),
        )
    default_vocabulary = ensure_unicode(config['default_vocabulary'])

    source_concept = get_concept(args.term, default_vocabulary)
    target_concepts = []
    list_options = {}

    if args.action == 'replace':
        target_concepts.append(get_concept(args.new_terms[0], default_vocabulary,
                                           default_term=source_concept.term,
                                           default_tag=source_concept.tag))

        if len(args.new_terms) > 1:
            target_concepts.append(get_concept(args.new_terms[1], default_vocabulary,
                                               default_tag=source_concept.tag))

    elif args.action == 'interactive':
        target_concepts = [
            get_concept(term, default_vocabulary, default_tag=source_concept.tag)
            for term in args.new_terms
        ]

    """ Caveat 1:

    We will do fuzzy matching (matching either $a or $x) only if both the source
    and target supports it
    """
    if len(target_concepts) > 0:
        if 'a_or_x' in source_concept.sf and 'a_or_x' not in target_concepts[0].sf:
            source_concept.set_a_or_x_to('a')

        if 'a_or_x' in target_concepts[0].sf and 'a_or_x' not in source_concept.sf:
            target_concepts[0].set_a_or_x_to('a')

    """ Caveat 2:

    If a tag move is involved, avoid fuzzy matching
    """
    if len(target_concepts) > 0:
        if source_concept.tag != target_concepts[0].tag:
            if 'a_or_x' in source_concept.sf:
                source_concept.set_a_or_x_to('a')
            if 'a_or_x' in target_concepts[0].sf:
                target_concepts[0].set_a_or_x_to('a')

    """ Caveat 3a:

    If a subfield exists in the source query, but not in the target query,
    we interpret that as a request for removing the subfield.
    As an example, the command

        almar replace '650 $$a TermA $$b TermB' '650 $$a TermC'

    should replace 'TermA' with 'TermC' in $$a and remove $$b.

    Developer note: This should be run before caveat 4 below, since we don't
    want to remove identifiers! (This is covered by tests)
    """
    for target_concept in target_concepts:
        # loop over all target concepts because of InteractiveReplaceTask
        for code in source_concept.sf:
            if not target_concept.has_subfield(code) and code != '0':
                log.debug('Adding explicit "%s: None" to target concept %s', code, target_concept)
                target_concept.sf[code] = None  # meaning NO_VALUE

    """ Caveat 3b:

    If a subfield (except for $0) exists in the target query, but not in the
    source query, we should not match fields already having some value for
    that subfield. As an example, the command

        almar replace '650 $$a TermA' '650 $$a TermB $$b TermC'

    should not match fields having '650 $$a TermA $$b SomeValue'

    Note: If there are multiple targets with varying number of components,
    this still applies for any subfield found in *any* of the targets. E.g.

        almar replace '650 $$a TermA' '650 $$a TermB' '650 $$a TermB $$b TermC'

    would not match '650 $$a TermA $$b SomeValue' Could this be counterintuitive?

    Developer note: This should be run before caveat 4 below
    """
    for target_concept in target_concepts:
        # loop over all target concepts because of InteractiveReplaceTask
        for code in target_concept.sf:
            if not source_concept.has_subfield(code) and code != '0':
                log.debug('Adding explicit "%s: None" to source concept %s', code, source_concept)
                source_concept.sf[code] = None  # meaning NO_VALUE

    """ Caveat 4:

    Some fields will have $0 values, but many won't, so we cannot require
    a $0 value at this point. If you want to match only fields with a given
    $0 value, use the advanced syntax:

        almar replace '650 $$a Test $$b Test $$0 identifer' ...

    """
    if '0' not in source_concept.sf:
        source_concept.sf['0'] = ANY_VALUE

    if args.action == 'list':
        list_options['show_titles'] = args.show_titles
        list_options['show_subjects'] = args.show_subjects

    return {
        'action': args.action,
        'source_concept': source_concept,
        'target_concepts': target_concepts,
        'list_options': list_options,
        'cql_query': args.cql_query,
        'authorities': Authorities(vocabularies)
    }


def get_config_filename():
    possible_file_locations = ['./almar.yml', './lokar.yml', os.path.expanduser('~/.almar.yml')]

    for filename in possible_file_locations:
        if os.path.exists(filename):
            return filename


def get_config(config=None):
    if config is not None:
        return config
    filename = get_config_filename()
    if filename is None:
        log.error('Could not find "almar.yml" configuration file. See https://github.com/scriptotek/almar for help.')
        sys.exit(1)

    try:
        return open(filename)
    except IOError:
        log.error('Could not read configuration file "%s"', filename)
        sys.exit(1)


def main(config=None, args=None):
    global raven_client

    with get_config(config) as fp:
        config = yaml.load(fp)

    username = getpass.getuser()
    log.info('Running as %s', username)
    try:
        if config.get('sentry') is not None:
            raven_client = Client(config['sentry']['dsn'])
            raven_client.context.merge({'user': {
                'username': username
            }})

        args = parse_args(args or sys.argv[1:], config.get('default_env'))

        if args.verbose:
            # Do this as early as possible
            log.setLevel(logging.DEBUG)

        jargs = job_args(config, args)

        if not args.dry_run:
            file_handler = logging.FileHandler('almar.log')
            file_handler.setFormatter(logging.Formatter(
                '[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S'))
            file_handler.setLevel(logging.INFO)
            log.addHandler(file_handler)

        def get_env(config, args):
            if args.env is None:
                log.error('No environment specified and no default environment found in configuration file')
                sys.exit(1)

            for env in config.get('env', []):
                if env['name'] == args.env:
                    return env

            log.error('Environment "%s" not found in configuration file', args.env)
            sys.exit(1)

        env = get_env(config, args)

        sru = SruClient(env['sru_url'], args.env)
        alma = Alma(env['api_region'], env['api_key'], args.env, dry_run=args.dry_run)

        job = Job(sru=sru, ils=alma, **jargs)
        job.dry_run = args.dry_run
        job.interactive = not args.non_interactive
        job.verbose = args.verbose
        job.show_diffs = args.show_diffs

        job.start()
        log.info('Job complete')

    except Exception:  # # pylint: disable=broad-except
        if raven_client is not None:
            raven_client.captureException()
        log.exception('Uncaught exception:')


if __name__ == '__main__':
    main()
