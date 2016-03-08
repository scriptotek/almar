import xmlwitch
import requests
import xml.etree.ElementTree as ET

explainUrl='https://sandbox02-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO?version=1.2&operation=explain'
response = requests.get(explainUrl)

root = ET.fromstring(response.text)

ns = {'e20' : 'http://explain.z3950.org/dtd/2.0/',
     'e21' : 'http://explain.z3950.org/dtd/2.1/'}

indexes = root.findall('.//{http://explain.z3950.org/dtd/2.0/}index')
len(indexes)

print '%40s %s' % ('NAME', 'DESCRIPTION')
for index in indexes:
    title = index.find('e21:title' , ns).text
    name = index.find('.//e20:name' , ns).text
    print ' %40s %s' % (name,title)
    
searchUrl='https://sandbox02-eu.alma.exlibrisgroup.com/view/sru/47BIBSYS_UBO'
mineparametre={
    'version': '1.2',
            'operation': 'searchRetrieve',
            'query': 'alma.subjects=Monstre',
            'maximumRecords': '20',
    }

response = requests.get(searchUrl, params=mineparametre)

root = ET.fromstring(response.text.encode('utf-8'))

response.url

records = root.findall('.//record')
len(records)

for n, record in enumerate(records):
    
    title = record.find('./datafield[@tag="245"]/subfield[@code="a"]').text
    print n, title
    
    emner = record.findall('./datafield[@tag="650"]')
    for emne in emner:
            if emne.find('subfield[@code="2"]') is not None and emne.find('subfield[@code="2"]').text == 'noubomn':
                print ' - ', emne.find('subfield[@code="a"]').text
                if emne.find('subfield[@code="a"]').text == u'Monstre':
                    # print ' ---> Ja, monstre!'
                    emne.find('subfield[@code="a"]').text = u'Monsterbibliotekarer'
                elif emne.find('subfield[@code="a"]').text == u'Mønstre':
                    print ' --> Nei, mønstre!'
                    
            elif emne.find('subfield[@code="2"]') is not None and emne.find('subfield[@code="2"]').text != 'noubomn':
                print ' - ', emne.find('subfield[@code="a"]').text, ' : ', emne.find('subfield[@code="2"]').text
                
            elif emne.find('subfield[@code="2"]') is None and record.findall('./datafield[@ind2="0"]'):
                print ' - ', emne.find('subfield[@code="a"]').text, ' : LCSH '
                
            elif emne.find('subfield[@code="2"]') is None and record.findall('./datafield[@ind2="2"]'):
                print ' - ', emne.find('subfield[@code="a"]').text, ' : MeSH '
                
                
            elif emne.find('subfield[@code="2"]') is None:
                print ' -  UKJENT : ', emne.find('subfield[@code="a"]').text
                
    frie = record.findall('./datafield[@tag="653"]')
    for emne in frie:
        print u' -  FRITT NØKKELORD : ', emne.find('subfield[@code="a"]').text
        
  print ET.tostring(record)
