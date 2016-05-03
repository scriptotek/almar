# coding=utf-8
from __future__ import print_function
from six.moves import input
import requests
import xml.etree.ElementTree as ET 

gammelord = input('Det gamle emneordet: ')
nyord = input('Det nye emneordet: ')

ns = {'e20' : 'http://explain.z3950.org/dtd/2.0/',
     'e21' : 'http://explain.z3950.org/dtd/2.1/',
     'srw': 'http://www.loc.gov/zing/srw/'}
    
searchUrl='https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO'
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
        
        emner = record.findall('./datafield[@tag="650"]')
        for emne in emner:
            if emne.find('subfield[@code="2"]') is not None and emne.find('subfield[@code="2"]').text == 'noubomn':
                if emne.find('subfield[@code="a"]').text == gammelord:
                    mms_ids.append(mms_id)
                    emne.find('subfield[@code="a"]').text = nyord

    nextRecordPosition = root.find('.//srw:nextRecordPosition', ns)
    if nextRecordPosition is not None:
        start_record = nextRecordPosition.text
    else:
        break  # Enden er nær, den er faktisk her!

    print('Poster som vil bli endret: {:d} av {:d}'.format(len(mms_ids), antall_sjekket))                                

# print(ET.tostring(record))
