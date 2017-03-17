from six import text_type, binary_type
import difflib
import vkbeautify
import sys
from colorama import Fore, Back, Style, init

# coding=utf-8
try:
    # Use lxml if installed, since it's faster ...
    from lxml import etree
except ImportError:
    # ... but also support standard ElementTree, since installation of lxml can be cumbersome
    import xml.etree.ElementTree as etree


def parse_xml(txt):
    if isinstance(txt, text_type):
        return etree.fromstring(txt.encode('utf-8'))
    elif isinstance(txt, binary_type):
        return etree.fromstring(txt)
    return txt


def normalize_term(term):
    # Normalize term so it starts with a capital letter. If the term is a subject string
    # fused by " : ", normalize all components.
    if term is None or len(term) == 0:
        return term

    return ' : '.join([component[0].upper() + component[1:] for component in term.strip().split(' : ')])


def term_match(term1, term2):
    return normalize_term(term1) == normalize_term(term2)


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


def show_diff(src, dst):
    src = vkbeautify.xml(src).splitlines(True)
    dst = vkbeautify.xml(dst).splitlines(True)

    for line in color_diff(difflib.unified_diff(src, dst, fromfile='Original', tofile='Modified')):
        sys.stdout.write(line)
