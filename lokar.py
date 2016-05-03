# coding=utf-8
from __future__ import print_function
from __future__ import unicode_literals
from six.moves import input
from six.moves import configparser
import requests
import sys
from requests import Session
import xml.etree.ElementTree as ET

config = configparser.ConfigParser()
config.read(['lokar.cfg'])

gammelord = input('Det gamle emneordet: ')
nyord = input('Det nye emneordet: ')

ns = {
    'e20' : 'http://explain.z3950.org/dtd/2.0/',
    'e21' : 'http://explain.z3950.org/dtd/2.1/',
    'srw': 'http://www.loc.gov/zing/srw/'
}

def finn_realfagstermer(marc_record, emneord):
    fields = []
    for field in marc_record.findall('./datafield[@tag="650"]'):
        if field.find('subfield[@code="2"]') is not None and field.find('subfield[@code="2"]').text == 'noubomn':
            if field.find('subfield[@code="a"]').text == emneord:
                fields.append(field)
            # Husk: Vi må også sjekke om emneord finnes i $x
    return fields

# ------------------------------------------------------------------------------------
# Del 1: Søk mot SRU for å finne over alle bibliografiske poster med emneordet.
# Vi må filtrere resultatlista i etterkant fordi
#  - vi mangler en egen indeks for Realfagstermer, så vi må søke mot `alma.subjects`
#  - søket er ikke presist, så f.eks. "Monstre" vil gi treff i "Mønstre"
#
# I fremtiden, når vi får $0 på alle poster, kan vi bruke indeksen `alma.authority_id`
# i stedet.

# sru_url='https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK'
sru_url = 'https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK'

start_record = 1
valid_records = []
records_checked = 0
sys.stdout.write('Søker..')
sys.stdout.flush()
while True:
    sru_params = {
        'version': '1.2',
        'operation': 'searchRetrieve',
        'query': 'alma.subjects=' + gammelord,
        'maximumRecords': '50',
        'startRecord': start_record
    }

    response = requests.get(sru_url, params=sru_params)
    root = ET.fromstring(response.text.encode('utf-8'))

    for marc_record in root.findall('.//record'):
        records_checked += 1
        mms_id = marc_record.find('./controlfield[@tag="001"]').text
        emner = finn_realfagstermer(marc_record, gammelord)
        if len(emner) != 0:
            valid_records.append(mms_id)

    nextRecordPosition = root.find('.//srw:nextRecordPosition', ns)
    if nextRecordPosition is not None:
        sys.stdout.write('.')
        sys.stdout.flush()
        start_record = nextRecordPosition.text
    else:
        break  # Enden er nær, den er faktisk her!

print('.')
print('Antall poster som vil bli endret: {:d}'.format(len(valid_records)))
if not input('Vil du fortsette? [Y/n] ').lower().startswith('y'):
    sys.exit(0)

# ------------------------------------------------------------------------------------
# Del 2: Nå har vi en liste over MMS-IDer for bibliografiske poster vi vil endre.
# Vi går gjennom dem én for én, henter ut posten med Bib-apiet, endrer og poster tilbake.

apikey_iz = config.get('alma', 'apikey_iz')
apikey_nz_sandbox = config.get('alma', 'apikey_nz_sandbox')

bib_url = 'https://api-{region}.hosted.exlibrisgroup.com/almaws/v1/bibs/{mms_id}'
region = 'eu'

for n, mms_id in enumerate(valid_records):

    # if record['cz'] is None:
    #     print('Posten {} er ikke lenket til NZ. Vi må redigere den i IZ. Ikke implementert enda!'.format(record['iz']))
    #     break

    print('{:d}/{:d} : {}'.format(n + 1, len(valid_records), mms_id))

    response = requests.get(bib_url.format(region=region, mms_id=mms_id),
                            params={'apikey': apikey_nz_sandbox})
    root = ET.fromstring(response.text.encode('utf-8'))
    marc_record = root.find('.//record')
    subject_fields = finn_realfagstermer(marc_record, gammelord)

    if len(subject_fields) == 0:
        print('Snodig, ingen emneord allikevel')
        continue

    strenger = []

    for field in subject_fields:
        streng = []
        for subfield in field.findall('subfield'):
            if subfield.get('code') in ['a', 'x']:
                streng.append(subfield.text)
            elif subfield.get('code') not in ['2', '0']:
                print('Emnefeltet inneholdt uventede delfelt: ' + ET.tostring(subfield))
                sys.exit(1)
        if streng in strenger:
            print('Fjerner duplikat emnefelt: ', streng.join(' : '))
            marc_record.remove(field)
            continue

        strenger.append(streng)
        field.find('subfield[@code="a"]').text = nyord

    response = requests.put(bib_url.format(region=region, mms_id=mms_id),
                            params={'apikey': apikey_nz_sandbox},
                            data=ET.tostring(root),
                            headers={'Content-Type': 'application/xml'})

    if response.status_code != 200:
        print(' -> Kunne ikke lagre post. Status: {}'.format(response.status_code))
        print(response.text)
        break
