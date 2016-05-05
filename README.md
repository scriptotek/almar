## LOKAR

[![Travis](https://img.shields.io/travis/scriptotek/lokar.svg?maxAge=2592000)](https://travis-ci.org/scriptotek/lokar)
[![Codecov](https://img.shields.io/codecov/c/github/scriptotek/lokar.svg?maxAge=2592000)](https://codecov.io/gh/scriptotek/lokar)
[![Code Health](https://landscape.io/github/scriptotek/lokar/master/landscape.svg?style=flat)](https://landscape.io/github/scriptotek/lokar/master)

Sript for å gjøre gjennomgående endringer i 648/650/651/655 i bibliografiske poster.
Testet med Python 2.7, 3.4 og 3.5.

### Oppsett

Opprett en fil `lokar.cfg` med følgende innhold:

```
[general]
vocabulary=noubomn
skosmos_vocab=realfagstermer
user=FYLL INN NAVN

[mailgun]
api_key=FYLL INN API-NØKKEL
domain=FYLL INN AVSENDER-DOMENE
sender=FYLL INN AVSENDER-EPOST
recipient=FYLL INN MOTTAKER-EPOST

[nz_sandbox]
api_key=FYLL INN API-NØKKEL
api_region=eu
sru_url=https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK

[nz_prod]
api_key=FYLL INN API-NØKKEL
api_region=eu
sru_url=https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK
```

Kjør `pip install -e .` for å installere avhengigheter.

### Bruk

* `python lokar.py -h` for hjelp.
* `python lokar.py 'Gammelt emneord' 'Nytt emneord'` for å erstatte "Gammelt emneord" med "Nytt emneord" i 650-felt.
* `python lokar.py 'Gammelt emneord' 'Nytt emneord' -d` for å gjøre en tørrkjøring uten å faktisk endre noen poster.
* `python lokar.py 'Gammelt emneord' 'Nytt emneord' -t 655` for å gjøre endringer i 655-felt.
* `python lokar.py 'Gammelt emneord'` for å slette "Gammelt emneord" fra alle poster

For emneord som består av mer enn ett ord må du bruke enkle eller doble anførselstegn rundt emneordet.
For emneord som kun består av ett ord er dette valgfritt.

Første bokstav er ikke signifikant; Både `gammelt emneord` og
`Gammelt emneord` vil bli erstattet. Og uansett om du skriver
`Nytt emneord` eller `nytt emneord`, vil `Nytt emneord` bli lagt på posten.

Tre streng-operasjoner støttes:
* `python lokar.py 'aaa : bbb'` vil slette forekomster av `$a Aaa $x Bbb`
* `python lokar.py 'aaa : bbb' 'ccc : ddd'` vil erstatte `$a Aaa $x Bbb` med `$a Ccc $x Ddd`
* `python lokar.py 'aaa : bbb' 'ccc'` vil erstatte `$a Aaa $x Bbb` med `$a Ccc` (delfelt `$x` fjernes)

Merk: Det må være mellomrom før og etter kolon for at termen skal gjenkjennes som en streng.

[![asciicast](https://asciinema.org/a/4hpi7n6s6ll3b5djykuqs2y8f.png)](https://asciinema.org/a/4hpi7n6s6ll3b5djykuqs2y8f)

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