# coding=utf-8
from __future__ import print_function
from six.moves import input
import requests
import xml.etree.ElementTree as ET 

gammelord = input('Det gamle emneordet: ')
nyord = input('Det nye emneordet: ')

ns = {'e20' : 'http://explain.z3950.org/dtd/2.0/',
     'e21' : 'http://explain.z3950.org/dtd/2.1/'}
    
searchUrl='https://bibsys-k.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO'
mineparametre={
    'version': '1.2',
            'operation': 'searchRetrieve',
            'query': 'alma.subjects=' + gammelord,
            'maximumRecords': '50',
    }

response = requests.get(searchUrl, params=mineparametre)
root = ET.fromstring(response.text.encode('utf-8'))
records = root.findall('.//record')

mms_ids = []
print(len(records))
for n, record in enumerate(records):    
    mms_id = record.find('./controlfield[@tag="001"]').text
    
    emner = record.findall('./datafield[@tag="650"]')
    for emne in emner:
        if emne.find('subfield[@code="2"]') is not None and emne.find('subfield[@code="2"]').text == 'noubomn':
            print(' - ', emne.find('subfield[@code="a"]').text.encode('utf-8'))
            if emne.find('subfield[@code="a"]').text == gammelord:
                mms_ids.append(mms_id)
                emne.find('subfield[@code="a"]').text = nyord

print('Poster som vil bli endret: {:d}'.format(len(mms_ids)))                    
        
# print(ET.tostring(record))