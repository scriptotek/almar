## LOKAR

[![Travis](https://img.shields.io/travis/scriptotek/lokar.svg?maxAge=2592000)](https://travis-ci.org/scriptotek/lokar)
[![Codecov](https://img.shields.io/codecov/c/github/scriptotek/lokar.svg?maxAge=2592000)](https://codecov.io/gh/scriptotek/lokar)
[![Code Health](https://landscape.io/github/scriptotek/lokar/master/landscape.svg?style=flat)](https://landscape.io/github/scriptotek/lokar/master)

Kode for gjennomgående endringer i bibliografiske poster

Skal bli: Funksjonalitet som henter ut gitte emneord fra Alma, og legger oppdaterte emneord tilbake i postene. 

@TODO: avgrens til alma.authority_vocabulary="noubomn"
@TODO: Første bokstav bør være case-insentiv..

### Bruk

Opprett en fil `lokar.cfg` med følgende innhold:

```
[general]
vocabulary=noubomn
user=MITT BRUKERNAVN

[nz_sandbox]
api_key=FYLL INN API-NØKKEL
api_region=eu
sru_url=https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK

[nz_prod]
api_key=FYLL INN API-NØKKEL
api_region=eu
sru_url=https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK
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

* Emneord som består av flere ord, f.eks. "Åpen kildekode"
