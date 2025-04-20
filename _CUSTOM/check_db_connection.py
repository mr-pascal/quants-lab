import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="optimization_database",
    user="admin",
    password="admin"
)

cur = conn.cursor()

cur.execute(
    """
    SELECT
    t.study_id,
    s.study_name,
    count(*)
    FROM trials t
    JOIN studies s ON s.study_id = t.study_id
    GROUP BY t.study_id, s.study_name
    ORDER BY t.study_id DESC
    """
)
rows = cur.fetchall()


rows = sorted(rows, key = lambda x:x[0])
for row in rows:
    print(row)

cur.close()
conn.close()
