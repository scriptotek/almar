# coding=utf-8
from __future__ import unicode_literals

import argparse
import getpass
from collections import OrderedDict

import colorama
import time
from coloredlogs import ColoredFormatter
import logging
import logging.config
import re
import os
import sys
from io import open  # pylint: disable=redefined-builtin
from hashlib import sha1
import tempfile
from diskcache import Cache

import yaml
from six import text_type
from raven import Client
from six import binary_type

from . import __version__
from .authorities import Vocabulary, Authorities
from .alma import Alma
from .concept import Concept
from .job import Job
from .sru import SruClient
from .util import ANY_VALUE, INTERACTIVITY_NONE, INTERACTIVITY_STANDARD, INTERACTIVITY_INCREASED
from .util import ColorStripFormatter, JobNameFilter

raven_client = None


def configure_logging(config, jobname, verbose=False):
    use_colors = sys.stdout.isatty()
    level = logging.DEBUG if verbose else logging.INFO
    formatter_options = {
        'fmt': '%(asctime)s %(levelname)-8s %(message)s',
        'datefmt': '%Y-%m-%d %H:%I:%S',
    }

    if use_colors:
        colorama.init(autoreset=True)
    else:
        # We're being piped, so skip colors
        colorama.init(strip=True)

    logging.config.dictConfig(config)

    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Add stream handler and formatter
    handler = logging.StreamHandler()
    handler.setLevel(level)
    formatter_type = ColoredFormatter if use_colors else ColorStripFormatter
    handler.setFormatter(formatter_type(**formatter_options))

    # Configure JobNameFilter
    JobNameFilter.jobname = jobname[:10]

    logger.addHandler(handler)

    # Increase logging level for dependencies
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)


def ensure_unicode(arg):
    if isinstance(arg, binary_type):
        return arg.decode('utf-8')
    return arg


def parse_args(args, default_env=None):
    parser = argparse.ArgumentParser(prog='almar',
                                     description='Edit or remove subject fields in Alma catalog records. '
                                     'By default, almar will ask you once to confirm before making any edits. '
                                     'This can be changed by using the -n or -i flags, see below.')
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    parser.add_argument('-e', '--env', dest='env', nargs='?',
                        help='Environment from config file. Default: {}'.format(default_env or '(none)'),
                        default=default_env)

    parser.add_argument('-d', '--dry-run', '--dry_run', dest='dry_run', action='store_true',
                        help='Dry run without doing any edits.')

    parser.add_argument('-v', '--verbose', '--debug', dest='verbose', action='store_true',
                        help='Show more output')

    parser.add_argument('-n', '--non-interactive', '--non_interactive', dest='non_interactive', action='store_true',
                        help='Non-interactive mode: Never ask for confirmation, always use defaults.')

    parser.add_argument('-i', '--interactive', dest='interactive', action='store_true',
                        help='Interactive mode: ask to confirm each change.')

    parser.add_argument('--diffs', dest='show_diffs', action='store_true',
                        help='Show diffs (deprecated option, now enabled by default).')

    parser.add_argument('--cql', dest='cql_query', nargs='?',
                        help=('Custom CQL query to specify which records to be checked. '
                              'Example: --cql \'alma.all_for_ui = "some identifier"\'')
                        )

    parser.add_argument('--titles', dest='show_titles', action='store_true',
                        help='Show titles (deprecated option, now enabled by default)')
    parser.add_argument('--subjects', dest='show_subjects', action='store_true', help='Show subject fields')

    parser.add_argument('--grep', dest='grep', nargs='?',
                        help=('Filter the result list by some string.'
                              'Example: --grep \'some text\'')
                        )

    parser.add_argument('--rem', dest='remove', action='append', default=[], help='Term to remove (can be repeated).')
    parser.add_argument('--add', dest='add', action='append', default=[], help='Term to add (can be repeated).')

    subparsers = parser.add_subparsers(title='subcommands')

    # Create parser for the "replace" command
    parser_move = subparsers.add_parser('replace', help='Replace/rename/move subject field')
    # TODO: , aliases=['rename', 'move'] added in Python 3.5

    parser_move.add_argument('term', nargs=1, help='Term to search for')
    parser_move.add_argument('new_terms', nargs='+', default='', help='Replacement terms')
    parser_move.set_defaults(action='replace')

    # Create parser for the "remove" command
    parser_del = subparsers.add_parser('remove', help='Remove subject field')
    # TODO: # , aliases=['delete'] added in Python 3.5

    parser_del.add_argument('term', nargs=1, help='Term to remove')
    parser_del.set_defaults(action='remove')

    # Create parser for the "add" command
    parser_add = subparsers.add_parser('add', help='Add subject fields')
    parser_add.add_argument('new_terms', nargs='+', help='Terms to add')
    parser_add.set_defaults(action='add')

    # Create parser for the "interactive" command
    parser_int = subparsers.add_parser('interactive', help='Interactive reclassification')
    parser_int.add_argument('term', nargs=1, help='Term to search for')
    parser_int.add_argument('new_terms', nargs='+', default='', help='Replacement terms')
    parser_int.set_defaults(action='interactive')

    # Create parser for the "list" command
    parser_list = subparsers.add_parser('list', help='List documents')
    parser_list.add_argument('term', nargs=1, help='Term to search for')
    parser_list.set_defaults(action='list')

    # Parse
    args = parser.parse_args(args)

    # Deprecated options
    args.show_diffs = True
    args.show_titles = True

    if 'new_terms' not in args:
        args.new_terms = []

    if 'action' not in args:
        if len(args.remove) == 0 and len(args.add) == 0:
            parser.error('Please specify an action or one or more --rem or --add clauses.')
        args.action = 'custom'
    else:
        if len(args.remove) != 0 or len(args.add) != 0:
            parser.error('--rem or --add cannot be used when an action is specified.')

    if args.interactive and args.non_interactive:
        parser.error('-n and -i are mutually exclusive')

    if args.env is not None:
        args.env = args.env.strip()

    args.env = ensure_unicode(args.env)

    args.terms = [ensure_unicode(x) for x in args.remove]
    if 'term' in args:
        args.terms.append(ensure_unicode(args.term[0]))

    args.new_terms = [ensure_unicode(x) for x in args.add] + [ensure_unicode(x) for x in args.new_terms]

    return args


def normalize_ind(value):
    if value == '#':
        return ' '
    return value


def parse_advanced_input(value):
    log = logging.getLogger()
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


def get_concept(term, default_vocabulary, default_tag=None, default_term=None):

    default_tag = default_tag or '650'

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

    source_concepts = [
        get_concept(term, default_vocabulary)
        for term in args.terms
    ]

    target_concepts = []
    if args.action == 'replace':
        target_concepts.append(get_concept(args.new_terms[0], default_vocabulary,
                                           default_term=source_concepts[0].term,
                                           default_tag=source_concepts[0].tag))

        for new_term in args.new_terms[1:]:
            target_concepts.append(get_concept(new_term, default_vocabulary,
                                               default_tag=source_concepts[0].tag))

    elif args.action in ['interactive', 'custom', 'add']:
        target_concepts = [
            get_concept(term, default_vocabulary)
            for term in args.new_terms
        ]

    list_options = {}

    """ Caveat 1:

    We will do fuzzy matching (matching either $a or $x) only if both the source
    and target supports it
    """
    log = logging.getLogger()

    if len(source_concepts) == 1 and len(target_concepts) > 0:
        if 'a_or_x' in source_concepts[0].sf and 'a_or_x' not in target_concepts[0].sf:
            source_concepts[0].set_a_or_x_to('a')

        if 'a_or_x' in target_concepts[0].sf and 'a_or_x' not in source_concepts[0].sf:
            target_concepts[0].set_a_or_x_to('a')

    """ Caveat 2:

    If more than one source or target concept is involved, don't do fuzzy matching.
    """
    if len(source_concepts) > 1 or len(target_concepts) > 1:
        for source_concept in source_concepts:
            source_concept.set_a_or_x_to('a')
        for target_concept in target_concepts:
            target_concept.set_a_or_x_to('a')

    """ Caveat 3:

    If a tag move is involved, don't do fuzzy matching
    """
    if len(source_concepts) == 1 and len(target_concepts) > 0:
        if source_concepts[0].tag != target_concepts[0].tag:
            if 'a_or_x' in source_concepts[0].sf:
                source_concepts[0].set_a_or_x_to('a')
            if 'a_or_x' in target_concepts[0].sf:
                target_concepts[0].set_a_or_x_to('a')

    """ Caveat 4a:

    If a subfield exists in the source query, but not in the target query,
    we interpret that as a request for removing the subfield.
    As an example, the command

        almar replace '650 $$a TermA $$b TermB' '650 $$a TermC'

    should replace 'TermA' with 'TermC' in $$a and remove $$b.

    Developer note: This should be run before caveat 4 below, since we don't
    want to remove identifiers! (This is covered by tests)
    """
    if len(source_concepts) == 1:
        for target_concept in target_concepts:
            # loop over all target concepts because of InteractiveReplaceTask
            for code in source_concepts[0].sf:
                if not target_concept.has_subfield(code) and code != '0':
                    log.debug('Adding explicit "%s: None" to target concept %s', code, target_concept)
                    target_concept.sf[code] = None  # meaning NO_VALUE

    """ Caveat 4b:

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
    if len(source_concepts) == 1:
        for target_concept in target_concepts:
            # loop over all target concepts because of InteractiveReplaceTask
            for code in target_concept.sf:
                if not source_concepts[0].has_subfield(code) and code != '0':
                    log.debug('Adding explicit "%s: None" to source concept %s', code, source_concepts[0])
                    source_concepts[0].sf[code] = None  # meaning NO_VALUE

    """ Caveat 5:

    Some fields will have $0 values, but many won't, so we cannot require
    a $0 value at this point. If you want to match only fields with a given
    $0 value, use the advanced syntax:

        almar replace '650 $$a Test $$b Test $$0 identifer' ...

    """
    for source_concept in source_concepts:
        if '0' not in source_concept.sf:
            source_concept.sf['0'] = ANY_VALUE

    list_options['show_titles'] = args.show_titles
    list_options['show_subjects'] = args.show_subjects

    return {
        'action': args.action,
        'source_concepts': source_concepts,
        'target_concepts': target_concepts,
        'list_options': list_options,
        'cql_query': args.cql_query,
        'grep': args.grep,
        'authorities': Authorities(vocabularies)
    }


def get_config_filename():
    possible_file_locations = ['./almar.yml', './lokar.yml', os.path.expanduser('~/.almar.yml')]

    for filename in possible_file_locations:
        if os.path.exists(filename):
            return filename


def get_config():
    log = logging.getLogger()

    filename = get_config_filename()
    if filename is None:
        log.error('Could not find "almar.yml" configuration file. See https://github.com/scriptotek/almar for help.')
        sys.exit(1)
    try:
        with open(filename) as fp:
            config = yaml.load(fp, Loader=yaml.SafeLoader)
    except IOError:
        log.error('Could not read configuration file "%s"', filename)
        sys.exit(1)

    return config


def run(config, cache, argv):
    global raven_client

    username = getpass.getuser()

    logging_defaults = {
        'version': 1,
        'disable_existing_loggers': False,
        'root': {
            'level': 'INFO',
        }
    }

    # Python 2/3: normalize to unicode strings
    argv = [x.decode('utf-8') if isinstance(x, binary_type) else x for x in argv]

    sha_input = u' '.join([config.get('default_env'), text_type(time.time())] + argv)
    jobname = sha1(sha_input.encode('utf-8')).hexdigest()

    # Note: configure_logging will add a StreamHandler for stdout
    args = parse_args(argv, config.get('default_env'))

    configure_logging(config.get('logging', logging_defaults), jobname, args.verbose)
    log = logging.getLogger()
    if sys.version_info < (3, 5):
        log.error('Sorry, Python < 3.5 is not supported.')
        sys.exit(1)
    log.debug('Starting job %s as %s', jobname, username)
    log.debug('Using cache dir: %s', cache.directory)

    jargs = job_args(config, args)

    if config.get('sentry') is not None:
        raven_client = Client(config['sentry']['dsn'])
        raven_client.context.merge({'user': {
            'username': username
        }})
    try:
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

        sru = SruClient(
            env['sru_url'],
            cache,
            name=args.env,
            cache_time=os.environ.get('CACHE_TIME', 300)  # in seconds
        )

        alma = Alma(
            env['api_region'],
            env['api_key'],
            cache,
            name=args.env,
            dry_run=args.dry_run,
            cache_time=os.environ.get('CACHE_TIME', 300)  # in seconds
        )

        job = Job(sru=sru, ils=alma, **jargs)
        job.dry_run = args.dry_run
        if args.non_interactive:
            job.interactivity = INTERACTIVITY_NONE
        elif args.interactive:
            job.interactivity = INTERACTIVITY_INCREASED
        else:
            job.interactivity = INTERACTIVITY_STANDARD

        job.verbose = args.verbose
        job.show_diffs = args.show_diffs

        concepts = jargs['source_concepts'] + jargs['target_concepts']
        jobdesc = '%s %s' % (jargs['action'], ' '.join(["'%s'" % text_type(x) for x in concepts]))

        log.debug('Job arguments: %s', jobdesc)

        job.start()

        if job.changes_made > 0:
            log.info('Job %s completed. Made %d changes to %d records', jobname, job.changes_made, job.records_changed)

            summary = logging.getLogger('summary')
            summary.info('%s - %s - %s - Made %d changes to %d records',
                         jobname, username, jobdesc, job.changes_made, job.records_changed)

    except Exception:  # # pylint: disable=broad-except
        if raven_client is not None:
            raven_client.captureException()
        log.exception('Uncaught exception:')


def main():
    username = getpass.getuser()
    cache_dir = os.path.join(tempfile.gettempdir(), 'almar-cache-%s' % username)
    with Cache(cache_dir) as cache:
        run(get_config(), cache, sys.argv[1:])


if __name__ == '__main__':
    main()
