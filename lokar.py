# coding=utf-8
from __future__ import print_function
from six.moves import input
from six.moves import configparser
import requests
from requests import Session
import xml.etree.ElementTree as ET

config = configparser.ConfigParser()
config.read(['lokar.cfg'])

gammelord = input('Det gamle emneordet: ')
nyord = input('Det nye emneordet: ')

ns = {'e20' : 'http://explain.z3950.org/dtd/2.0/',
     'e21' : 'http://explain.z3950.org/dtd/2.1/',
     'srw': 'http://www.loc.gov/zing/srw/'}


def finn_realfagstermer(record, emneord):
    emner = []
    for emne in record.findall('./datafield[@tag="650"]'):
        if emne.find('subfield[@code="2"]') is not None and emne.find('subfield[@code="2"]').text == 'noubomn':
            if emne.find('subfield[@code="a"]').text == emneord:
                if emne.find('subfield[@code="x"]') is not None:
                    print('Vi har funnet en emnestreng! Hjelp!')
                else:
                    emner.append(emne)

    return emner

    
# searchUrl='https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO'
searchUrl='https://sandbox-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO'
start_record = 1
mms_ids = []
antall_sjekket = 0
while True:
    mineparametre={
        'version': '1.2',
                'operation': 'searchRetrieve',
                'query': 'alma.subjects=' + gammelord,
                'maximumRecords': '50',
                'startRecord': start_record
        }

    response = requests.get(searchUrl, params=mineparametre)
    root = ET.fromstring(response.text.encode('utf-8'))
    records = root.findall('.//record')

    antall_sjekket += len(records)

    for n, record in enumerate(records):    
        mms_id = record.find('./controlfield[@tag="001"]').text
        title = record.find('./datafield[@tag="245"]/subfield[@code="a"]').text
        emner = finn_realfagstermer(record, gammelord)
        if len(emner) != 0:
            mms_ids.append(mms_id)
            # print('- ', title)

    print('Poster som vil bli endret: {:d} av {:d}'.format(len(mms_ids), antall_sjekket))                                

    nextRecordPosition = root.find('.//srw:nextRecordPosition', ns)
    if nextRecordPosition is not None:
        start_record = nextRecordPosition.text
    else:
        break  # Enden er nær, den er faktisk her!


# Del 2: Hente ut én og én post fra Bib-apiet og endre dem

apikey_iz = config.get('alma', 'apikey_iz')
apikey_nz_sandbox = config.get('alma', 'apikey_nz_sandbox')

bib_url = 'https://api-eu.hosted.exlibrisgroup.com/almaws/v1/bibs/{mms_id}'
# session = Session()
# session.headers.update({'Authorization': 'apikey l7xx6ec2066dade54a03893c9a9847f42eb9'})

for mms_id in mms_ids:
    response = requests.get(bib_url.format(mms_id=mms_id), params={'apikey': apikey_iz})
    root = ET.fromstring(response.text.encode('utf-8'))
    linked_record = root.find('.//linked_record_id[@type="NZ"]')
    if linked_record is None:
        print('Oi, fant ikke NZ record for ' + mms_id)
        break

    mms_id_nz = linked_record.text

    print('IZ: ', mms_id, ' NZ: ', mms_id_nz)

    response = requests.get(bib_url.format(mms_id=mms_id_nz),
                            params={'apikey': apikey_nz_sandbox})
    root = ET.fromstring(response.text.encode('utf-8'))
    record = root.find('.//record')
    emner = finn_realfagstermer(record, gammelord)

    if len(emner) != 1:
        print('Oi, vi har dubletter')
        break

    emner[0].find('subfield[@code="a"]').text = nyord

    response = requests.put(bib_url.format(mms_id=mms_id_nz),
                            params={'apikey': apikey_nz_sandbox},
                            data=ET.tostring(root),
                            headers={'Content-Type': 'application/xml'})

    if response.status_code == 200:
        print(' -> det gikk bra')
    else:
        print(' -> det gikk ikke bra')
        break
