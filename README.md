## LOKAR

Kode for gjennomgående endringer i bibliografiske poster

Skal bli: Funksjonalitet som henter ut gitte emneord fra Alma, og legger oppdaterte emneord tilbake i postene. 

### Bruk

Opprett en fil `lokar.cfg` med følgende innhold:

```
[alma]
apikey_iz=FYLL INN API-NØKKEL
apikey_nz_sandbox=FYLL INN API-NØKKEL
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
