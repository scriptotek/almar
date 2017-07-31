# Almar &middot; [![Travis](https://img.shields.io/travis/scriptotek/almar.svg)](https://travis-ci.org/scriptotek/almar) [![Codecov](https://img.shields.io/codecov/c/github/scriptotek/almar.svg)](https://codecov.io/gh/scriptotek/almar) [![Code Health](https://landscape.io/github/scriptotek/almar/master/landscape.svg?style=flat)](https://landscape.io/github/scriptotek/almar/master)

Almar (formerly Lokar) is a script for batch editing and removing controlled classification and
subject heading fields (084/648/650/651/655) in bibliographic records in Alma
using the Alma APIs. Tested with Python 2.7 and Python 3.4+.

It will use an SRU service to search for records, fetch and modify the MARCXML
records and use the Alma Bibs API to write the modified records back to Alma.

The script will only work with fields having a vocabulary code defined in `$2`.
Since the SRU service does not provide search indexes for any vocabulary, almar
does a search using the `alma.subjects` + the `alma.authority_vocabulary` indices
to find all records having a subject field A with the given term and a
subject field B with the given vocabulary code, but where A is not necessarily
equal to B. It then filters the result list to find the records where A is
actually the same as B.

[![asciicast](https://asciinema.org/a/4hpi7n6s6ll3b5djykuqs2y8f.png)](https://asciinema.org/a/4hpi7n6s6ll3b5djykuqs2y8f)

## Installation and configuration

1. Run `pip install -e .` to install `almar` and its dependencies.
2. Create a `almar.yml` configuration file in the directory you're planning to run `almar` from.

Here's a minimal `almar.yml` file to start with:

```
---
vocabulary:
  marc_code: INSERT MARC VOCABULARY CODE HERE

default_env: prod

env:
  prod:
    api_key: INSERT API KEY HERE
    api_region: eu
    sru_url: INSERT SRU URL HERE
```

1. Replace `INSERT MARC VOCABULARY CODE HERE` with the vocabulary code of
   your vocabulary (the `$2` value). The script uses this value as a filter,
   to ensure it only edits subject fields from the specified vocabulary.
2. Replace `INSERT API KEY HERE` with the API key of your Alma instance. If
   you'r connected to a network zone, you should probably use a network zone key.
   Otherwise the edits will be stored as local edits in the institution zone.
3. Optionally: Change api_region to 'na' (North America) or 'ap' (Asia Pacific).
4. Replace `INSERT SRU URL HERE` with the URL to your SRU endpoint. Again: use
   the network zone endpoint if you're connected to a network zone. For Bibsys
   institutions, use `https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK`

Note: In the file above, we've configured a single Alma environment called "prod".
It's possible to add multiple environments (for instance a sandbox and a
production environment) and switch between them using the `-e` command line option:

```
---
vocabulary:
  marc_code: noubomn
  id_service: http://data.ub.uio.no/microservices/authorize.php?vocabulary=realfagstermer&term={term}&tag={tag}
  marc_prefix: (NO-TrBIB)

default_env: nz_prod

env:
  nz_sandbox:
    api_key: FYLL INN API-NØKKEL
    api_region: eu
    sru_url: https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK
  nz_prod:
    api_key: FYLL INN API-NØKKEL
    api_region: eu
    sru_url: https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK
```

## Usage

Before using the tool, make sure you hve set the vocabulary code
(`vocabulary.marc_code`) for the vocabulary you want to work with in `almar.yml`.

Note: The tool will only make changes to fields having a `$2` value that matches
the `vocabulary.marc_code` code set in your `almar.yml` file.

Getting help:

* `almar -h` to show help
* `almar rename -h` to show help for the "rename" subcommand

### Rename a subject heading

To replace "Term" with "New term" in 650 fields:

    almar rename '650 Term' 'New term'

or, since 650 is defined as the default field, you can also use the shorthand:

    almar rename 'Term' 'New term'

To work with any other field than the 650 field, the field number must be explicit:

    almar rename '655 Term' 'New term'`

Supported fields are 084, 648, 650, 651 and 655.

### Diffs and dry run

To see the changes made to each catalog record, add the `--diffs` flag. Combined
with the `--dry_run` flag (or `-d`), you will see the changes that would be made
to the records without actually touching any records:

    almar rename --diffs --dry_run 'Term' 'New term'

This way, you can easily get a feel for how the tool works.

### Moving a subject to another MARC tag

To move a subject heading from 650 to 651:

    almar rename '650 Term' '651 Term'

or you can use the shorthand

    almar rename '650 Term' '651'

if the term itself is the same. You can also move and change a heading in
one operation:

    almar rename '650 Term' '651 New term'

### Deleting a subject heading

To delete all 650 fields having either `$a Term` or `$x Term`:

    almar delete '650 Term'

or, since 650 is the default field, the shorthand:

    almar delete 'Term'


## Notes

* For terms consisting of more than one word, you must add quotation marks (single or double)
  around the term, as in the examples above. For single word terms, this is optional.
* In search, the first letter is case insensitive. If you search for "old term", both
  "old term" and "Old term" will be replaced (but not "old Term").
* Identifiers (`$0`) are added/updated only if you configure a ID lookup URL in `almar.yml`.


## Limited support for subject strings

Four kinds of string operations are currently supported:

* `almar delete 'Aaa : Bbb'` deletes occurances of `$a Aaa $x Bbb`
* `almar rename 'Aaa : Bbb' 'Ccc : Ddd'` replaces `$a Aaa $x Bbb` with `$a Ccc $x Ddd`
* `almar rename 'Aaa : Bbb' 'Ccc'` replaces `$a Aaa $x Bbb` with `$a Ccc` (replacing subfield `$a` and removing subfield `$x`)
* `almar rename 'Aaa' 'Bbb : Ccc'` replaces `$a Aaa` with `$a Bbb $x $Ccc` (replacing subfield `$a` and adding subfield `$x`)

Note: A term is only recognized as a string if there is space before and after colon (` : `).

## Interactive usage

```python
from almar import SruClient, Alma

api_region = 'eu'
api_key = 'SECRET'
sru_url = 'https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK'

sru = SruClient(sru_url)
alma = Alma(api_region, api_key)

query = 'alma.authority_vocabulary="noubomn"'
for record in sru.search(query):
    for subject in record.subjects(vocabulary='noubomn'):
        if not subject.find('subfield[@code="0"]'):
            sa = subject.findtext('subfield[@code="a"]')
            sx = subject.findtext('subfield[@code="x"]')
```

## Development

To run tests:

    pip install -r test-requirements.txt
    py.test
