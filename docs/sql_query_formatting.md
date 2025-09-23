# Formatting SQL Queries with Quoted Column Names in Python

When working with datasets that contain column identifiers such as `"BO No"`, keep the following conventions in mind to ensure Codex (or any AI assistant) generates valid SQL when embedded inside Python code:

## Use Triple-Single-Quoted Python Strings

Wrap multiline SQL statements in triple-single quotes so that embedded double quotes remain untouched:

```python
query = '''
SELECT
  "BO No",
  COUNT(*) AS count
FROM BackorderedParts
WHERE "BO No" IS NOT NULL
GROUP BY "BO No"
LIMIT 10;
'''
```

This keeps the SQL readable and prevents Python (or Codex) from misinterpreting the double quotes as string delimiters.

## Keep Double Quotes for Identifiers with Spaces

SQLite and many other engines require double quotes around identifiers that include spaces. Avoid single quotes because they turn the identifier into a literal string:

```sql
SELECT 'BO No' FROM BackorderedParts;  -- returns the literal text 'BO No'
```

## Avoid Unnecessary Escaping

Triple-quoted strings already allow you to embed double quotes without escaping. Prefer the clean version below instead of escaping each quote:

```python
query = """
SELECT "BO No" FROM BackorderedParts;
"""
```

Although this works, it becomes harder to maintain in longer queries, so the triple-single-quoted style above is recommended.

## Recommended Query Template

Use the following template when you need Codex to expand or customize a query that references quoted identifiers:

```python
query = '''
SELECT
  "BO No",
  MIN(report_date) AS first_seen,
  MAX(report_date) AS last_seen
FROM BackorderedParts
WHERE
  "Sub Priority" = 'AK0'
  AND "BO No" IS NOT NULL
GROUP BY "BO No"
ORDER BY last_seen DESC;
'''

cursor.execute(query)
```

By keeping double quotes around spaced identifiers and enclosing the SQL in triple-single-quoted strings, you give Codex the clearest pattern to follow while generating or editing queries.
