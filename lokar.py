# coding=utf-8
from __future__ import print_function
import requests
import xml.etree.ElementTree as ET

ns = {'e20' : 'http://explain.z3950.org/dtd/2.0/',
     'e21' : 'http://explain.z3950.org/dtd/2.1/'}
    
searchUrl='https://sandbox02-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO'
mineparametre={
    'version': '1.2',
            'operation': 'searchRetrieve',
            'query': 'alma.subjects=Monstre',
            'maximumRecords': '20',
    }

response = requests.get(searchUrl, params=mineparametre)
root = ET.fromstring(response.text.encode('utf-8'))
records = root.findall('.//record')

for n, record in enumerate(records):    
    title = record.find('./datafield[@tag="245"]/subfield[@code="a"]').text.encode('utf-8')
    print(n, title)
    
    emner = record.findall('./datafield[@tag="650"]')
    for emne in emner:
        if emne.find('subfield[@code="2"]') is not None and emne.find('subfield[@code="2"]').text == 'noubomn':
            print(' - ', emne.find('subfield[@code="a"]').text.encode('utf-8'))
            if emne.find('subfield[@code="a"]').text == u'Monstre':
                emne.find('subfield[@code="a"]').text = u'Monsterbibliotekarer'
                    
        
# print(ET.tostring(record))