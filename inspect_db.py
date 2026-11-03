import sqlite3
c = sqlite3.connect('portfolio.db')
for name, sql in c.execute("select name, sql from sqlite_master where type='table'").fetchall():
    print(name)
    print(sql)
    print(c.execute(f'select count(*) from {name}').fetchone()[0], 'rows')
    print('-' * 40)
