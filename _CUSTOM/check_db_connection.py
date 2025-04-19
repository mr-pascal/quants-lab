import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="optimization_database",
    user="admin",
    password="admin"
)

cur = conn.cursor()
cur.execute("SELECT * FROM studies;")
print(cur.fetchall())

cur.close()
conn.close()
