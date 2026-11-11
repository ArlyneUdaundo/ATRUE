with open('templates/dashboard_base.html','r',encoding='utf-8',errors='ignore') as f:
    s=f.read()

i=s.find('hotels:list')
if i>=0:
    print(s[max(0,i-40):i+80])
else:
    print('no')