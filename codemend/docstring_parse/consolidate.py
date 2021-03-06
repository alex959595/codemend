"""Resolves the references generated by parse.py and generates one
"flat" mapping table that contains:
  func_id -> utter
  func_id + arg -> utter

Usage:
    RUN parse.py FIRST
    THEN,
        python consolidate.py

Rules:
1. (func_id, utter) mappings are preserved.
2. (func_id, arg, utter) mappings are preserved.
3. For (func_id, ref) mappings:
   (1) if ref is a method, then
       a) if the method is set_XXX, then a new (func_id, arg, utter) mapping
          will be created, where XXX will be the new arg, and utter will be
          the utter associated with the method.
       b) otherwise, all the (arg, utter) associated with the ref (if any)
          are added to the current func_id as new (func_id, arg, utter) 
          mappings. For example, some methods accept all the keyword arguments
          that are accepted by axes.Axes.plot().
   (2) if ref is a class, then
       a) all the set_XXX method that belongs to the class will be added
          as new (func_id, arg, utter) mapping to this func_id, in which utter
          is the original utter associated with set_XXX method.
4. Finally, for each (func_id) and (func_id, arg), the utter's should be deduped
   and concatenated as one string.

The inputs will be read from the `mapping` and `reference` tables of api.sqlite3.

The output will be written into the `fu` and `fau` tables of the same xml file.
"""
import sqlite3
from collections import defaultdict

def get_method(func_id):
  """
  Example input: matplotlib.patches.Patch.set_linestyle
  Example output: set_linestyle
  """
  return func_id.split('.')[-1]

def is_setXXX(func_id):
  """Returns XXX, or False"""
  method_name = get_method(func_id)
  if method_name.startswith('set_'):
    return method_name[4:]
  return False

def get_class(func_id):
  """
  Example input: matplotlib.patches.Patch.set_linestyle
  Example output: set_linestyle
  """
  return '.'.join(func_id.split('.')[:-1])


if __name__ == '__main__':
  fu_map = defaultdict(set)  # [func_id] = set(utterance)
  fau_map = defaultdict(set)  # [(func_id, arg)] = set(utterance)
  fa_map = defaultdict(set)  # [func_id] = set(arg)
  cf_map = defaultdict(set)  # [class] = set(func_id)

  db = sqlite3.connect('api.sqlite3')
  cursor = db.cursor()

  # RULE 1
  cursor.execute("SELECT func_id, utter FROM mapping WHERE arg IS NULL")
  for func_id, utter in cursor.fetchall():
    fu_map[func_id].add(utter)

  print '%d entries in fu_map after applying RULE 1'%(len(fu_map))

  # RULE 2
  cursor.execute("SELECT func_id, arg, utter FROM mapping WHERE arg IS NOT NULL")
  for func_id, arg, utter in cursor.fetchall():
    fau_map[(func_id, arg)].add(utter)

  print '%d entries in fau_map after applying RULE 2'%len(fau_map)

  # RULE 3
  """In our actual implementation, we won't try to distinguish whether a ref is
  a method or a class. We just try both options. For each one, only one sub-rule
  should apply anyway.""" 

  for func_id, arg in fau_map.keys():
    fa_map[func_id].add(arg)

  for func_id in fa_map:
    cf_map[get_class(func_id)].add(func_id)

  cursor.execute("SELECT func_id, ref FROM reference")
  # Since some func_id's args depend on another func_id's, we do this twice.
  for it in range(2):
    for func_id, ref in cursor.fetchall():
      XXX = is_setXXX(ref)
      if XXX:
        """ref is a set_XXX() method. Rule 3-1-a.
        An example: add the NL desc of set_hatch to (axes.Axes.barh, hatch).
        """
        if ref in fu_map:
          fau_map[(func_id, XXX)] |= fu_map[ref]
      elif ref in fa_map:
        """ref is a regular method. Rule 3-1-b."""
        for arg in fa_map[ref]:
          if (ref, arg) in fau_map:
            fau_map[(func_id, arg)] |= fau_map[(ref, arg)]
      elif ref in cf_map:
        """ref is a class. Rule 3-2."""
        ref_func_ids = cf_map[ref]
        ref_func_ids = filter(is_setXXX, ref_func_ids)
        ref_func_names = map(is_setXXX, ref_func_ids)
        for rfi, rfn in zip(ref_func_ids, ref_func_names):
          if rfi in fu_map:
            fau_map[(func_id, rfn)] |= fu_map[rfi]
    print '%d entries in fau_map after %d times applying Rule 3'%(len(fau_map),it+1)

  # RULE 4
  cursor.executescript("""
    DROP TABLE IF EXISTS fu;
    DROP TABLE IF EXISTS fau;

    CREATE TABLE fu (
      func_id TEXT PRIMARY KEY NOT NULL,
      utter TEXT
      );

    CREATE TABLE fau (
      func_id TEXT NOT NULL,
      arg TEXT NOT NULL,
      utter TEXT,
      PRIMARY KEY (func_id, arg)
      );
    """)

  for f, u_set in fu_map.items():
    u = '|||'.join(u_set)
    cursor.execute("INSERT INTO fu VALUES (?, ?)", (f,u))

  for (f, a), u_set in fau_map.items():
    u = '|||'.join(u_set)
    cursor.execute("INSERT INTO fau VALUES (?, ?, ?)", (f, a, u))

  db.commit()
  db.close()
