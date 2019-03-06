# coding=utf-8
from __future__ import unicode_literals
import difflib
import sys
from collections import OrderedDict
import vkbeautify
from colorama import Fore
from lxml import etree
from six import text_type
import questionary
import logging
import re
import pkg_resources  # part of setuptools
__version__ = pkg_resources.require('almar')[0].version

ANY_VALUE = '{ANY_VALUE}'


def utf8print(txt=None):
    if txt is None:
        sys.stdout.write('\n')
    else:
        if sys.version_info < (3, 0):
            sys.stdout.write(('%s\n' % txt).encode('utf-8'))
        else:
            sys.stdout.write('%s\n' % txt)


def pick(msg, options, alpha_options=None):
    choices = OrderedDict()
    for i, option in enumerate(options):
        choice_text = text_type(option)
        choices[choice_text] = option
    if alpha_options is not None:
        for k, v in alpha_options.items():
            choices[v] = k

    answer = questionary.checkbox(msg, choices=[
        {'name': x} for x in choices.keys()
    ]).ask()

    return [choices[x] for x in answer]


def pick_one(msg, options, alpha_options=None):
    choices = OrderedDict()
    for i, option in enumerate(options):
        choice_text = text_type(option)
        choices[choice_text] = option
    if alpha_options is not None:
        for k, v in alpha_options.items():
            choices[v] = k

    answer = questionary.select(msg, choices.keys()).ask()

    return choices[answer]


def parse_xml(txt):
    if isinstance(txt, text_type):
        return etree.fromstring(txt.encode('utf-8'))
    return etree.fromstring(txt)


def normalize_term(term):
    # Normalize term so it starts with a capital letter. If the term is a subject string
    # fused by " : ", normalize all components.

    if term is None or len(term) == 0:
        return term

    return ' : '.join([component[0].upper() + component[1:] for component in term.strip().split(' : ')])


def term_match(term1, term2):
    return term1 == ANY_VALUE or term2 == ANY_VALUE or normalize_term(term1) == normalize_term(term2)


def color_diff(diff):
    for line in diff:
        if line.startswith('+'):
            yield Fore.GREEN + line + Fore.RESET
        elif line.startswith('-'):
            yield Fore.RED + line + Fore.RESET
        elif line.startswith('^'):
            yield Fore.BLUE + line + Fore.RESET
        else:
            yield line


def line_marc(root):

    st = []
    for node in root.xpath('//datafield'):
        t = '%s %s%s' % (node.get('tag'), node.get('ind1').replace(' ', '#'), node.get('ind2').replace(' ', '#'))
        for sf in node.findall('subfield'):
            t += ' $%s %s' % (sf.get('code'), sf.text)
        t += '\n'
        st.append(t)

    return st


def get_diff(src, dst):
    src = line_marc(etree.fromstring(src.encode('utf-8')))
    dst = line_marc(etree.fromstring(dst.encode('utf-8')))

    # src = vkbeautify.xml(src).splitlines(True)
    # dst = vkbeautify.xml(dst).splitlines(True)

    # returns list of unicode strings
    return list(color_diff(difflib.unified_diff(src, dst, fromfile='Original', tofile='Modified')))


class ColorStripFormatter(logging.Formatter):

    def format(self, record):
        s = super(ColorStripFormatter, self).format(record)
        s = re.sub(r'\x1b\[[0-9;]*m', '', s)

        return s


class JobNameFilter(logging.Filter):

    jobname = ''

    def filter(self, record):
        record.jobname = self.jobname
        return True
