## Lokar

[![Travis](https://img.shields.io/travis/scriptotek/lokar.svg?maxAge=2592000)](https://travis-ci.org/scriptotek/lokar)
[![Codecov](https://img.shields.io/codecov/c/github/scriptotek/lokar.svg?maxAge=2592000)](https://codecov.io/gh/scriptotek/lokar)
[![Code Health](https://landscape.io/github/scriptotek/lokar/master/landscape.svg?style=flat)](https://landscape.io/github/scriptotek/lokar/master)

Lokar is a script for editing or removing subject fields (648/650/651/655) in bibliographic
records in Alma using the Alma APIs. Tested with Python 2.7, 3.4 and 3.5.

### Setup and configuration

1. Run `pip install -e .` to install `lokar` and its dependencies.
2. Create a `lokar.yml` configuration file in the directory you're planning to run `lokar` from.

Here's a minimal `lokar.yml` file to start with:

```
---
vocabulary:
  marc_code: INSERT MARC VOCABULARY CODE HERE

env:
  prod:
    api_key: INSERT API KEY HERE
    api_region: eu
    sru_url: INSERT SRU URL HERE
```

1. Replace `INSERT MARC VOCABULARY CODE HERE` with the vocabulary code of
   your vocabulary (the one that goes in `6XX $2`).
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
  skosmos_code: realfagstermer

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

### Usage

Note: The tool will only work with subject fields where the `$2` value matches the `vocabulary.marc_code` code in
`lokar.yml`. If you've set `vocabulary.marc_code` to e.g. `noubomn`, the tool will never make any changes to
subject fields that do not have `$2 noubomn`.

* `lokar -h` to show help
* `lokar rename -h` to show help for the move subcommand

#### Renaming/moving

* `lokar rename 'Term' 'New term'` to replace "Term" with "New term" in 650 fields (default).
* `lokar rename -t 655 'Term' 'New term'` to replace "Term" with "New term" in 655 fields.

Dry run:

* `lokar rename -d 'Term' 'New term'` to do a dry run to see what records would be modified without actually modifying them.

Moving a subject to another MARC tag:

* `lokar rename -t 650 'Term' --to_tag 651` to move "Term" from 650 to 651 (replacing `650 $a Term` with `651 Term`).

#### Deleting

* `lokar delete 'Term'` to remove 650 fields having "$a Term" or "$x Term".
* `lokar -t 651 delete 'Term'` to remove 651 fields having "$a Term" or "$x Term".

For emneord som består av mer enn ett ord må du bruke enkle eller doble anførselstegn rundt emneordet.
For emneord som kun består av ett ord er dette valgfritt.

Første bokstav er ikke signifikant; Både `gammelt emneord` og
`Gammelt emneord` vil bli erstattet. Og uansett om du skriver
`Nytt emneord` eller `nytt emneord`, vil `Nytt emneord` bli lagt på posten.

Tre streng-operasjoner støttes:
* `lokar 'aaa : bbb'` vil slette forekomster av `$a Aaa $x Bbb`
* `lokar 'aaa : bbb' 'ccc : ddd'` vil erstatte `$a Aaa $x Bbb` med `$a Ccc $x Ddd`
* `lokar 'aaa : bbb' 'ccc'` vil erstatte `$a Aaa $x Bbb` med `$a Ccc` (delfelt `$x` fjernes)

Merk: Det må være mellomrom før og etter kolon for at termen skal gjenkjennes som en streng.

[![asciicast](https://asciinema.org/a/4hpi7n6s6ll3b5djykuqs2y8f.png)](https://asciinema.org/a/4hpi7n6s6ll3b5djykuqs2y8f)


### Interactive usage

```python
from lokar import SruClient, Alma

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

### Utforske SRU-endepunktet

For en oversikt over hvilke indekser som er tilgjengelig fra SRU-endepunktet:

```python
import requests

explain_url = 'https://sandbox02-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO?version=1.2&operation=explain'
response = requests.get(explain_url)

ns = {
    'e20': 'http://explain.z3950.org/dtd/2.0/',
    'e21': 'http://explain.z3950.org/dtd/2.1/',
}

root = ET.fromstring(response.text)
indexes = root.findall('.//e20:index')

print('%40s %s' % ('NAME', 'DESCRIPTION'))
for index in indexes:
    title = index.find('e21:title' , ns).text
    name = index.find('.//e20:name' , ns).text
    print(' %40s %s' % (name,title))
```

### Testing

    pip install -r test-requirements.txt
    py.test
