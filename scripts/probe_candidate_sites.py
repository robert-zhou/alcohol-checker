import requests

urls = [
    'https://www.totalwine.com/search?search=vodka',
    'https://www.totalwine.com/search?search=whiskey',
    'https://www.wine.com/search/searchList.aspx?searchString=vodka',
    'https://www.drizly.com/search?q=vodka',
    'https://www.liquor.com/search?q=vodka',
]
for u in urls:
    try:
        r = requests.get(u, timeout=20, headers={'User-Agent':'Mozilla/5.0'})
        print('URL', u)
        print('STATUS', r.status_code)
        print(r.text[:300].replace('\n',' ')[:300])
        print('---')
    except Exception as e:
        print('URL', u, 'ERR', e)
